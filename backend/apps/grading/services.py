from __future__ import annotations

import asyncio
import json
import logging
import shutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from django.db import close_old_connections, transaction
from django.utils import timezone

from apps.grading.models import (
    CriterionGrade,
    EvidenceRegion,
    GradingRun,
    ModelCall,
    Question,
    QuestionGrade,
    RubricCriterion,
    StudentAnswer,
    TeacherOverride,
)
if TYPE_CHECKING:
    from grading_engine.orchestrator import GradingExecution
    from grading_engine.runtime import GradingSettings
from common.logging import log_event
from grading_engine.runtime import get_grading_settings
from grading_engine.trace_logger import append_run_trace


logger = logging.getLogger(__name__)

CANCELLATION_FILENAME = "cancel_requested.json"


class CancellationRequested(Exception):
    pass


DEFAULT_PROGRESS = {
    "stage": "pending",
    "progress_percent": 0,
    "status_message": "Pending",
    "started_at": None,
    "completed_at": None,
}


def normalize_public_status(status: str) -> str:
    if status in {"pending", "processing", "completed", "failed", "canceled"}:
        return status
    if status == "timed_out":
        return "failed"
    return "processing"


def public_status_message(status: str) -> str:
    return normalize_public_status(status).capitalize()


class GradingProgressStore:
    def __init__(self, settings: "GradingSettings", run_id: str) -> None:
        self._path = settings.artifacts_root / run_id / "progress.json"

    def load(self) -> dict:
        if not self._path.exists():
            return dict(DEFAULT_PROGRESS)
        try:
            return json.loads(self._path.read_text())
        except json.JSONDecodeError:
            return dict(DEFAULT_PROGRESS)

    def save(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        merged = {**DEFAULT_PROGRESS, **payload}
        self._path.write_text(json.dumps(merged))

    def update(self, **fields) -> dict:
        payload = self.load()
        payload.update({key: value for key, value in fields.items() if value is not None})
        self.save(payload)
        return payload


def iso_now() -> str:
    return timezone.now().isoformat()


def cancellation_request_path(settings: "GradingSettings", run_id: str) -> Path:
    return settings.artifacts_root / run_id / CANCELLATION_FILENAME


def is_cancellation_requested(settings: "GradingSettings", run_id: str) -> bool:
    return cancellation_request_path(settings, run_id).exists()


def request_grading_cancellation(*, settings: "GradingSettings", run: GradingRun) -> dict:
    if run.status not in {"pending", "processing"}:
        raise ValueError("Only pending or processing grading runs can be canceled")

    request_path = cancellation_request_path(settings, str(run.id))
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps({"requested_at": iso_now()}))

    store = GradingProgressStore(settings, str(run.id))
    mark_run_canceled(
        run=run,
        store=store,
        error_message="Grading canceled",
    )
    append_run_trace(settings, str(run.id), "grading.cancel_requested")
    return {
        "grading_id": str(run.id),
        "status": "canceled",
        "canceled_at": run.updated_at,
    }


def mark_run_canceled(
    *,
    run: GradingRun,
    store: GradingProgressStore,
    error_message: str,
) -> None:
    update_run_progress(
        run=run,
        store=store,
        status="canceled",
        stage="canceled",
        progress_percent=100,
        status_message="Canceled",
        error_message=error_message,
        completed=True,
    )


def get_progress_snapshot(run: GradingRun) -> dict:
    store = GradingProgressStore(get_grading_settings(), str(run.id))
    payload = store.load()
    status = normalize_public_status(run.status)
    payload["status"] = status
    payload["error_message"] = run.error_message or None
    if status == "completed":
        payload["stage"] = "completed"
        payload["progress_percent"] = 100
        payload["status_message"] = public_status_message(status)
        payload["completed_at"] = payload.get("completed_at") or run.updated_at.isoformat()
    elif status == "failed":
        payload["stage"] = "failed"
        payload["status_message"] = public_status_message(status)
        payload["progress_percent"] = 100
        payload["completed_at"] = payload.get("completed_at") or run.updated_at.isoformat()
    elif status == "canceled":
        payload["stage"] = "canceled"
        payload["status_message"] = public_status_message(status)
        payload["progress_percent"] = 100
        payload["completed_at"] = payload.get("completed_at") or run.updated_at.isoformat()
    elif status == "processing":
        payload["stage"] = "processing"
        payload["status_message"] = payload.get("status_message") or public_status_message(status)
    else:
        payload["stage"] = "pending"
        payload["status_message"] = payload.get("status_message") or public_status_message(status)
    return payload


def update_run_progress(
    *,
    run: GradingRun,
    store: GradingProgressStore,
    status: str | None = None,
    stage: str | None = None,
    progress_percent: int | None = None,
    status_message: str | None = None,
    error_message: str | None = None,
    completed: bool = False,
) -> None:
    update_fields = ["updated_at"]
    public_status = normalize_public_status(status or run.status)
    existing_payload = store.load()
    existing_started_at = existing_payload.get("started_at")
    if status is not None and run.status != status:
        run.status = status
        update_fields.append("status")
    if error_message is not None and run.error_message != error_message:
        run.error_message = error_message
        update_fields.append("error_message")
    run.save(update_fields=update_fields)
    store.update(
        stage=public_status,
        progress_percent=progress_percent,
        status_message=status_message or public_status_message(public_status),
        started_at=existing_started_at or (iso_now() if public_status == "processing" else None),
        completed_at=iso_now() if completed else None,
    )


def start_grading_job(
    *,
    run_id: str,
    runtime_settings: "GradingSettings",
) -> None:
    thread = threading.Thread(
        target=_run_grading_job,
        kwargs={"run_id": run_id, "runtime_settings": runtime_settings},
        daemon=True,
        name=f"grading-run-{run_id}",
    )
    thread.start()


def start_batch_grading_jobs(
    *,
    run_ids: list[str],
    runtime_settings: "GradingSettings",
) -> None:
    thread = threading.Thread(
        target=_run_batch_grading_jobs,
        kwargs={"run_ids": run_ids, "runtime_settings": runtime_settings},
        daemon=True,
        name=f"grading-batch-{run_ids[0] if run_ids else 'empty'}",
    )
    thread.start()


def run_grading_job_inline(*, run_id: str, runtime_settings: "GradingSettings") -> None:
    _run_grading_job(run_id=run_id, runtime_settings=runtime_settings)


def run_batch_grading_jobs_inline(*, run_ids: list[str], runtime_settings: "GradingSettings") -> None:
    _run_batch_grading_jobs(run_ids=run_ids, runtime_settings=runtime_settings)


def _run_batch_grading_jobs(*, run_ids: list[str], runtime_settings: "GradingSettings") -> None:
    for index, run_id in enumerate(run_ids, start=1):
        append_run_trace(
            runtime_settings,
            run_id,
            "grading.batch_queue_position",
            queue_index=index,
            queue_size=len(run_ids),
        )
        _run_grading_job(run_id=run_id, runtime_settings=runtime_settings)


def ensure_not_canceled(*, runtime_settings: "GradingSettings", run_id: str) -> None:
    if is_cancellation_requested(runtime_settings, run_id):
        raise CancellationRequested("Grading canceled")


def _run_grading_job(*, run_id: str, runtime_settings: "GradingSettings") -> None:
    from grading_engine.orchestrator import build_grading_orchestrator

    close_old_connections()
    run = GradingRun.objects.select_related("user").filter(id=run_id).first()
    if run is None:
        close_old_connections()
        return
    store = GradingProgressStore(runtime_settings, run_id)
    if run.status == "canceled" or is_cancellation_requested(runtime_settings, run_id):
        mark_run_canceled(
            run=run,
            store=store,
            error_message=run.error_message or "Grading canceled",
        )
        append_run_trace(runtime_settings, run_id, "grading.job_skipped_canceled")
        close_old_connections()
        return
    append_run_trace(runtime_settings, run_id, "grading.job_started")
    update_run_progress(
        run=run,
        store=store,
        status="processing",
        stage="processing",
        progress_percent=8,
        status_message="Processing",
    )

    def progress(stage: str, progress_percent: int, status_message: str) -> None:
        ensure_not_canceled(runtime_settings=runtime_settings, run_id=run_id)
        append_run_trace(
            runtime_settings,
            run_id,
            "grading.progress_updated",
            stage=stage,
            progress_percent=progress_percent,
            status_message=status_message,
        )
        store.update(
            stage="processing",
            progress_percent=progress_percent,
            status_message=status_message,
        )

    try:
        orchestrator = build_grading_orchestrator(runtime_settings)
        ensure_not_canceled(runtime_settings=runtime_settings, run_id=run_id)
        execution = asyncio.run(
            asyncio.wait_for(
                orchestrator.grade(
                    run_id=run_id,
                    exam_pdf_path=Path(run.exam_storage_path),
                    student_pdf_path=Path(run.student_storage_path),
                    progress_hook=progress,
                ),
                timeout=runtime_settings.hard_timeout_seconds,
            )
        )
        run = GradingRun.objects.filter(id=run_id).first()
        if run is None:
            append_run_trace(runtime_settings, run_id, "grading.job_deleted_before_persist")
            return
        ensure_not_canceled(runtime_settings=runtime_settings, run_id=run_id)
        update_run_progress(
            run=run,
            store=store,
            status="processing",
            stage="processing",
            progress_percent=98,
            status_message="Finalizing result",
        )
        ensure_not_canceled(runtime_settings=runtime_settings, run_id=run_id)
        persist_execution(run, execution)
        completed_run = GradingRun.objects.filter(id=run_id).first()
        if completed_run is None:
            append_run_trace(runtime_settings, run_id, "grading.job_deleted_after_persist")
            return
        if completed_run.status == "canceled" or is_cancellation_requested(runtime_settings, run_id):
            mark_run_canceled(
                run=completed_run,
                store=store,
                error_message=completed_run.error_message or "Grading canceled",
            )
            append_run_trace(runtime_settings, run_id, "grading.job_canceled_after_execution")
            return
        update_run_progress(
            run=completed_run,
            store=store,
            status="completed",
            stage="completed",
            progress_percent=100,
            status_message="Completed",
            completed=True,
        )
        append_run_trace(runtime_settings, run_id, "grading.job_completed")
        log_event(
            logger,
            "grading.completed",
            run_id=completed_run.id,
            user_id=completed_run.user_id,
            input_tokens=completed_run.input_tokens,
            output_tokens=completed_run.output_tokens,
            cost_usd=completed_run.cost_usd,
            duration_ms=completed_run.duration_ms,
        )
    except CancellationRequested as exc:
        canceled_run = GradingRun.objects.filter(id=run_id).first()
        if canceled_run is None:
            append_run_trace(runtime_settings, run_id, "grading.job_canceled_after_delete")
            return
        mark_run_canceled(
            run=canceled_run,
            store=store,
            error_message=str(exc),
        )
        append_run_trace(runtime_settings, run_id, "grading.job_canceled")
        log_event(logger, "grading.canceled", run_id=canceled_run.id, user_id=canceled_run.user_id)
    except asyncio.TimeoutError:
        failed_run = GradingRun.objects.filter(id=run_id).first()
        if failed_run is None:
            append_run_trace(runtime_settings, run_id, "grading.job_timed_out_after_delete")
            return
        update_run_progress(
            run=failed_run,
            store=store,
            status="failed",
            stage="failed",
            progress_percent=100,
            status_message="Failed",
            error_message="Grading timed out",
            completed=True,
        )
        append_run_trace(runtime_settings, run_id, "grading.job_timed_out", timeout_seconds=runtime_settings.hard_timeout_seconds)
        log_event(logger, "grading.timeout", run_id=failed_run.id, user_id=failed_run.user_id)
    except Exception as exc:
        failed_run = GradingRun.objects.filter(id=run_id).first()
        if failed_run is None:
            append_run_trace(runtime_settings, run_id, "grading.job_failed_after_delete", error=str(exc))
            return
        update_run_progress(
            run=failed_run,
            store=store,
            status="failed",
            stage="failed",
            progress_percent=100,
            status_message="Failed",
            error_message=str(exc),
            completed=True,
        )
        append_run_trace(runtime_settings, run_id, "grading.job_failed", error=str(exc))
        log_event(logger, "grading.failed", run_id=failed_run.id, user_id=failed_run.user_id, error=str(exc))
    finally:
        close_old_connections()


@transaction.atomic
def persist_execution(run: GradingRun, execution: GradingExecution) -> None:
    run.status = execution.result.status
    run.model_deployment = execution.result.model_deployment
    run.total_score = execution.result.total_score
    run.max_score = execution.result.max_score
    run.duration_ms = execution.result.duration_ms
    run.input_tokens = execution.total_prompt_tokens
    run.output_tokens = execution.total_completion_tokens
    run.cost_usd = execution.total_cost_usd
    run.error_message = ""
    run.result_json = execution.result.model_dump(mode="json")
    run.save(
        update_fields=[
            "status",
            "model_deployment",
            "total_score",
            "max_score",
            "duration_ms",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "error_message",
            "result_json",
            "updated_at",
        ]
    )

    rubric_lookup = {item.question_id: item for item in execution.rubric_questions}

    for exam_question in execution.exam.questions:
        rubric_question = rubric_lookup[exam_question.question_id]
        question_record = Question.objects.create(
            grading_run=run,
            question_id=exam_question.question_id,
            question_text=exam_question.question_text,
            official_solution=exam_question.official_solution,
            source_pages=exam_question.source_pages,
            max_marks=rubric_question.max_marks,
            rubric_source=rubric_question.rubric_source,
            max_marks_source=rubric_question.max_marks_source,
        )
        RubricCriterion.objects.bulk_create(
            [
                RubricCriterion(
                    question=question_record,
                    criterion_id=criterion.criterion_id,
                    description=criterion.description,
                    expected_answer=criterion.expected_answer,
                    marks=criterion.marks,
                    source=criterion.source,
                )
                for criterion in rubric_question.criteria
            ]
        )

    StudentAnswer.objects.bulk_create(
        [
            StudentAnswer(
                grading_run=run,
                question_id=answer.question_id,
                page_number=answer.evidence.page if answer.evidence else None,
                bbox=answer.evidence.bbox if answer.evidence else None,
                transcription=answer.transcription,
                final_answer=answer.final_answer,
                derivation_summary=answer.derivation_summary,
                status=answer.status,
                uncertainty_flags=answer.uncertain_parts,
                needs_human_review=answer.needs_human_review,
            )
            for answer in execution.student_inspection.answers
        ]
    )

    for question_result in execution.result.questions:
        question_grade = QuestionGrade.objects.create(
            grading_run=run,
            question_id=question_result.question_id,
            awarded_marks=question_result.awarded_marks,
            max_marks=question_result.max_marks,
            feedback=question_result.feedback,
            confidence=question_result.confidence,
            needs_human_review=question_result.needs_human_review,
        )
        for criterion_result in question_result.criterion_scores:
            criterion_grade = CriterionGrade.objects.create(
                question_grade=question_grade,
                criterion_id=criterion_result.criterion_id,
                awarded=criterion_result.awarded,
                max=criterion_result.max,
                match_type=criterion_result.match_type,
                verification_status=criterion_result.verification_status,
                feedback=criterion_result.feedback,
                confidence=criterion_result.confidence,
                needs_human_review=criterion_result.needs_human_review,
            )
            if criterion_result.evidence is not None:
                EvidenceRegion.objects.create(
                    question_grade=question_grade,
                    criterion_grade=criterion_grade,
                    question_id=question_result.question_id,
                    page_number=criterion_result.evidence.page,
                    bbox=criterion_result.evidence.bbox,
                    crop_path=criterion_result.evidence.crop_path,
                    zoomed=criterion_result.evidence.zoomed,
                )

    ModelCall.objects.bulk_create(
        [
            ModelCall(
                grading_run=run,
                stage=trace.stage,
                deployment=trace.deployment,
                prompt_tokens=trace.prompt_tokens,
                completion_tokens=trace.completion_tokens,
                duration_ms=trace.duration_ms,
                cost_usd=trace.cost_usd,
                status=trace.status,
                error_message=trace.error_message,
            )
            for trace in execution.model_calls
        ]
    )


@transaction.atomic
def apply_teacher_override(
    *,
    run: GradingRun,
    user,
    question_id: str,
    new_score: float,
    reason: str,
) -> dict:
    result = dict(run.result_json or {})
    questions = result.get("questions", [])
    target = next((item for item in questions if item["question_id"] == question_id), None)
    if target is None:
        raise LookupError("Question not found")
    if new_score > float(target["max_marks"]):
        raise ValueError("Override exceeds max marks")

    old_score = float(target["awarded_marks"])
    target["awarded_marks"] = new_score
    target["feedback"] = f"{target['feedback']} Override applied: {reason}".strip()
    result["total_score"] = round(sum(float(item["awarded_marks"]) for item in questions), 2)

    run.total_score = result["total_score"]
    run.result_json = result
    run.save(update_fields=["total_score", "result_json", "updated_at"])

    question_grade = QuestionGrade.objects.filter(grading_run=run, question_id=question_id).first()
    if question_grade is not None:
        question_grade.awarded_marks = new_score
        question_grade.override_applied = True
        question_grade.save(update_fields=["awarded_marks", "override_applied", "updated_at"])

    TeacherOverride.objects.create(
        grading_run=run,
        user=user,
        question_id=question_id,
        old_score=old_score,
        new_score=new_score,
        reason=reason,
    )
    return {
        "grading_id": str(run.id),
        "question_id": question_id,
        "new_score": new_score,
        "total_score": result["total_score"],
        "updated_at": run.updated_at,
    }


@transaction.atomic
def delete_grading_runs(
    *,
    user,
    grading_ids: list[str],
    runtime_settings: "GradingSettings",
) -> dict:
    requested_ids = [str(grading_id) for grading_id in grading_ids]
    runs = list(GradingRun.objects.filter(user=user, id__in=requested_ids))
    found_ids = {str(run.id) for run in runs}
    missing_ids = [grading_id for grading_id in requested_ids if grading_id not in found_ids]
    if missing_ids:
        raise LookupError("One or more grading runs were not found")

    non_terminal_ids = [str(run.id) for run in runs if run.status not in {"completed", "failed", "canceled"}]
    if non_terminal_ids:
        raise ValueError("Only completed, failed, or canceled grading runs can be removed")

    removable_directories: list[Path] = []
    for run in runs:
        removable_directories.append(runtime_settings.uploads_root / str(run.id))
        removable_directories.append(runtime_settings.artifacts_root / str(run.id))

    deleted_count = len(runs)
    GradingRun.objects.filter(user=user, id__in=requested_ids).delete()

    for directory in removable_directories:
        shutil.rmtree(directory, ignore_errors=True)

    return {
        "deleted_count": deleted_count,
        "deleted_ids": requested_ids,
    }
