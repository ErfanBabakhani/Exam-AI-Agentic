from __future__ import annotations

import logging
import uuid
from datetime import date

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.grading.models import GradingRun
from apps.grading.pdf_export import render_runs_pdf_bytes
from apps.grading.runtime_cleanup import normalize_grading_run_statuses
from apps.grading.serializers import (
    BatchGradingCreateRequestSerializer,
    BatchGradingCreateResponseSerializer,
    BulkDeleteGradingsRequestSerializer,
    BulkDeleteGradingsResponseSerializer,
    GradingCancellationResponseSerializer,
    GradingCreateRequestSerializer,
    GradingExportRequestSerializer,
    GradingRunStatusSerializer,
    GradingRunDetailSerializer,
    GradingRunSummarySerializer,
    TeacherOverrideResponseSerializer,
    TeacherOverrideRequestSerializer,
)
from apps.grading.services import (
    GradingProgressStore,
    apply_teacher_override,
    delete_grading_runs,
    request_grading_cancellation,
    run_batch_grading_jobs_inline,
    run_grading_job_inline,
    start_batch_grading_jobs,
    start_grading_job,
)
from common.api import build_error_payload
from common.logging import log_event


logger = logging.getLogger(__name__)


class PdfRenderer(BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"
    charset = None
    render_style = "binary"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b""
        if isinstance(data, bytes):
            return data
        if isinstance(data, str):
            return data.encode("utf-8")
        return b""


def build_export_file_name(run_count: int) -> str:
    return f"grading-runs-{run_count}-{date.today().isoformat()}.pdf"


def normalize_stale_grading_rows() -> None:
    # Run legacy status cleanup lazily during request handling, not during Django app startup.
    normalize_grading_run_statuses()


def assert_pdf(upload, label: str) -> None:
    filename = getattr(upload, "name", "")
    if not filename.lower().endswith(".pdf"):
        raise ValueError(f"{label} must be a PDF file")
    if getattr(upload, "size", 0) <= 0:
        raise ValueError(f"{label} is empty")
    signature = upload.read(5)
    upload.seek(0)
    if signature != b"%PDF-":
        raise ValueError(f"{label} does not look like a valid PDF file")


def get_user_run_or_404(user, grading_id: str) -> GradingRun:
    normalize_stale_grading_rows()
    return get_object_or_404(GradingRun, id=grading_id, user=user)


def initialize_progress(run: GradingRun, runtime_settings) -> None:
    progress_store = GradingProgressStore(runtime_settings, str(run.id))
    progress_store.save(
        {
            "status": "pending",
            "stage": "pending",
            "progress_percent": 0,
            "status_message": "Pending",
            "started_at": None,
            "completed_at": None,
        }
    )


class GradingListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["gradings"],
        summary="List grading runs",
        responses={200: GradingRunSummarySerializer(many=True)},
    )
    def get(self, request):
        normalize_stale_grading_rows()
        runs = GradingRun.objects.filter(user=request.user).order_by("-created_at")
        return Response(GradingRunSummarySerializer(runs, many=True).data)

    @extend_schema(
        tags=["gradings"],
        summary="Create a grading run",
        request=GradingCreateRequestSerializer,
        responses={
            200: GradingRunDetailSerializer,
            202: GradingRunDetailSerializer,
        },
    )
    def post(self, request):
        from grading_engine.file_storage import FileStorageService
        from grading_engine.runtime import get_grading_settings

        exam_pdf = request.FILES.get("exam_pdf")
        student_pdf = request.FILES.get("student_pdf")
        if exam_pdf is None or student_pdf is None:
            return Response(
                build_error_payload(
                    detail="Both exam_pdf and student_pdf are required",
                    code="missing_files",
                ),
                status=400,
            )
        try:
            assert_pdf(exam_pdf, "exam_pdf")
            assert_pdf(student_pdf, "student_pdf")
        except ValueError as exc:
            return Response(
                build_error_payload(
                    detail=str(exc),
                    code="invalid_pdf",
                ),
                status=400,
            )

        runtime_settings = get_grading_settings()
        run = GradingRun.objects.create(
            user=request.user,
            status="pending",
            exam_filename=exam_pdf.name,
            exam_storage_path="pending",
            student_filename=student_pdf.name,
            student_storage_path="pending",
            model_deployment=settings.AZURE_OPENAI_DEPLOYMENT,
        )

        storage = FileStorageService(runtime_settings)
        try:
            exam_path = storage.save_upload(str(run.id), "exam", exam_pdf)
            student_path = storage.save_upload(str(run.id), "student", student_pdf)
        except RuntimeError as exc:
            run.status = "failed"
            run.error_message = str(exc)
            run.save(update_fields=["status", "error_message", "updated_at"])
            return Response(
                build_error_payload(
                    detail=str(exc),
                    code="upload_failed",
                ),
                status=400,
            )

        run.exam_storage_path = str(exam_path)
        run.student_storage_path = str(student_path)
        run.save(update_fields=["exam_storage_path", "student_storage_path", "updated_at"])
        initialize_progress(run, runtime_settings)

        log_event(logger, "grading.submitted", run_id=run.id, user_id=request.user.id)
        if settings.GRADING_INLINE_MODE:
            run_grading_job_inline(
                run_id=str(run.id),
                runtime_settings=runtime_settings,
            )
            run.refresh_from_db()
            return Response(GradingRunDetailSerializer(run).data)

        start_grading_job(
            run_id=str(run.id),
            runtime_settings=runtime_settings,
        )
        serializer = GradingRunDetailSerializer(run)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        tags=["gradings"],
        summary="Delete grading runs",
        request=BulkDeleteGradingsRequestSerializer,
        responses={200: BulkDeleteGradingsResponseSerializer},
    )
    def delete(self, request):
        from grading_engine.runtime import get_grading_settings

        normalize_stale_grading_rows()
        serializer = BulkDeleteGradingsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        runtime_settings = get_grading_settings()
        try:
            payload = delete_grading_runs(
                user=request.user,
                grading_ids=[str(grading_id) for grading_id in serializer.validated_data["grading_ids"]],
                runtime_settings=runtime_settings,
            )
        except LookupError as exc:
            return Response(
                build_error_payload(
                    detail=str(exc),
                    code="grading_not_found",
                ),
                status=404,
            )
        except ValueError as exc:
            return Response(
                build_error_payload(
                    detail=str(exc),
                    code="invalid_delete_request",
                ),
                status=409,
            )
        log_event(
            logger,
            "grading.bulk_deleted",
            user_id=request.user.id,
            deleted_count=payload["deleted_count"],
            deleted_ids=payload["deleted_ids"],
        )
        return Response(payload)


class BatchGradingCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["gradings"],
        summary="Create a batch of grading runs",
        request=BatchGradingCreateRequestSerializer,
        responses={202: BatchGradingCreateResponseSerializer},
    )
    def post(self, request):
        from grading_engine.file_storage import FileStorageService
        from grading_engine.runtime import get_grading_settings

        exam_pdf = request.FILES.get("exam_pdf")
        student_pdfs = request.FILES.getlist("student_pdfs")
        if exam_pdf is None or not student_pdfs:
            return Response(
                build_error_payload(
                    detail="exam_pdf and at least one student_pdfs entry are required",
                    code="missing_files",
                ),
                status=400,
            )
        try:
            assert_pdf(exam_pdf, "exam_pdf")
            for index, student_pdf in enumerate(student_pdfs, start=1):
                assert_pdf(student_pdf, f"student_pdfs[{index}]")
        except ValueError as exc:
            return Response(
                build_error_payload(
                    detail=str(exc),
                    code="invalid_pdf",
                ),
                status=400,
            )

        runtime_settings = get_grading_settings()
        storage = FileStorageService(runtime_settings)
        batch_id = str(uuid.uuid4())
        batch_dir = runtime_settings.uploads_root / f"batch_{batch_id}"
        try:
            exam_path = storage.save_upload_to_directory(batch_dir, "exam", exam_pdf)
        except RuntimeError as exc:
            return Response(
                build_error_payload(
                    detail=str(exc),
                    code="upload_failed",
                ),
                status=400,
            )

        runs: list[GradingRun] = []
        for student_pdf in student_pdfs:
            run = GradingRun.objects.create(
                user=request.user,
                status="pending",
                exam_filename=exam_pdf.name,
                exam_storage_path=str(exam_path),
                student_filename=student_pdf.name,
                student_storage_path="pending",
                model_deployment=settings.AZURE_OPENAI_DEPLOYMENT,
            )
            try:
                student_path = storage.save_upload(str(run.id), "student", student_pdf)
            except RuntimeError as exc:
                run.status = "failed"
                run.error_message = str(exc)
                run.save(update_fields=["status", "error_message", "updated_at"])
                return Response(
                    build_error_payload(
                        detail=str(exc),
                        code="upload_failed",
                    ),
                    status=400,
                )
            run.student_storage_path = str(student_path)
            run.save(update_fields=["student_storage_path", "updated_at"])
            initialize_progress(run, runtime_settings)
            runs.append(run)
            log_event(logger, "grading.submitted", run_id=run.id, user_id=request.user.id)

        run_ids = [str(run.id) for run in runs]
        if settings.GRADING_INLINE_MODE:
            run_batch_grading_jobs_inline(run_ids=run_ids, runtime_settings=runtime_settings)
            for run in runs:
                run.refresh_from_db()
        else:
            start_batch_grading_jobs(run_ids=run_ids, runtime_settings=runtime_settings)

        serializer = GradingRunDetailSerializer(runs, many=True)
        return Response(
            {
                "queue_size": len(runs),
                "runs": serializer.data,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class GradingExportPdfView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    renderer_classes = [PdfRenderer, JSONRenderer]

    @extend_schema(
        tags=["gradings"],
        summary="Export grading runs as PDF",
        request=GradingExportRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="PDF export",
            )
        },
    )
    def post(self, request):
        normalize_stale_grading_rows()
        serializer = GradingExportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grading_ids = [str(grading_id) for grading_id in serializer.validated_data["grading_ids"]]
        runs_by_id = {
            str(run.id): run
            for run in GradingRun.objects.filter(user=request.user, id__in=grading_ids).order_by("-created_at")
        }
        missing_ids = [grading_id for grading_id in grading_ids if grading_id not in runs_by_id]
        if missing_ids:
            return Response(
                build_error_payload(
                    detail="One or more grading runs were not found.",
                    code="grading_not_found",
                ),
                status=404,
            )
        runs = [runs_by_id[grading_id] for grading_id in grading_ids]
        try:
            pdf_bytes = render_runs_pdf_bytes(runs)
        except Exception:
            return Response(
                build_error_payload(
                    detail="PDF export could not be generated.",
                    code="pdf_export_failed",
                ),
                status=500,
            )

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{build_export_file_name(len(runs))}"'
        return response


class GradingDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["gradings"],
        summary="Get grading run details",
        responses={200: GradingRunDetailSerializer},
    )
    def get(self, request, grading_id: str):
        run = get_user_run_or_404(request.user, grading_id)
        return Response(GradingRunDetailSerializer(run).data)


class GradingStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["gradings"],
        summary="Get grading run status",
        responses={200: GradingRunStatusSerializer},
    )
    def get(self, request, grading_id: str):
        run = get_user_run_or_404(request.user, grading_id)
        return Response(GradingRunStatusSerializer(run).data)


class GradingCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["gradings"],
        summary="Cancel a grading run",
        request=None,
        responses={200: GradingCancellationResponseSerializer},
    )
    def patch(self, request, grading_id: str):
        from grading_engine.runtime import get_grading_settings

        run = get_user_run_or_404(request.user, grading_id)
        runtime_settings = get_grading_settings()
        try:
            payload = request_grading_cancellation(settings=runtime_settings, run=run)
        except ValueError as exc:
            return Response(
                build_error_payload(
                    detail=str(exc),
                    code="invalid_cancel_request",
                ),
                status=409,
            )
        log_event(
            logger,
            "grading.cancelled_by_user",
            run_id=run.id,
            user_id=request.user.id,
        )
        return Response(payload)


class GradingOverrideView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        tags=["gradings"],
        summary="Apply a teacher override",
        request=TeacherOverrideRequestSerializer,
        responses={200: TeacherOverrideResponseSerializer},
    )
    def patch(self, request, grading_id: str):
        run = get_user_run_or_404(request.user, grading_id)
        if run.result_json is None:
            return Response(
                build_error_payload(
                    detail="No grading result is available to override",
                    code="missing_result",
                ),
                status=409,
            )
        serializer = TeacherOverrideRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = apply_teacher_override(run=run, user=request.user, **serializer.validated_data)
        except LookupError as exc:
            return Response(
                build_error_payload(
                    detail=str(exc),
                    code="question_not_found",
                ),
                status=404,
            )
        except ValueError as exc:
            return Response(
                build_error_payload(
                    detail=str(exc),
                    code="invalid_override",
                ),
                status=400,
            )
        log_event(
            logger,
            "grading.override.created",
            run_id=run.id,
            user_id=request.user.id,
            question_id=payload["question_id"],
            new_score=payload["new_score"],
        )
        return Response(payload)
