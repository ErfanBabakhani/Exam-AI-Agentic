from __future__ import annotations

import asyncio
import importlib.util
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.grading.models import GradingRun
from apps.grading.services import _run_batch_grading_jobs, cancellation_request_path, get_progress_snapshot, update_run_progress, GradingProgressStore
from apps.grading.views import initialize_progress
from grading_engine.orchestrator import MockGradingOrchestrator
from grading_engine.runtime import get_grading_settings


REPORTLAB_AVAILABLE = importlib.util.find_spec("reportlab") is not None


class GradingApiFlowTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.temp_dir = tempfile.TemporaryDirectory()
        storage_root = Path(self.temp_dir.name) / "storage"
        uploads_root = storage_root / "uploads"
        artifacts_root = storage_root / "artifacts"
        self.artifacts_root = artifacts_root
        for path in (storage_root, uploads_root, artifacts_root):
            path.mkdir(parents=True, exist_ok=True)
        self.override = override_settings(
            ALLOW_MOCK_GRADING=True,
            GRADING_INLINE_MODE=True,
            STORAGE_ROOT=storage_root,
            UPLOADS_ROOT=uploads_root,
            ARTIFACTS_ROOT=artifacts_root,
        )
        self.override.enable()
        self.client = Client()

    def tearDown(self) -> None:
        self.override.disable()
        self.temp_dir.cleanup()
        super().tearDown()

    def test_required_flow(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)

        health_with_slash = self.client.get("/api/health/")
        self.assertEqual(health_with_slash.status_code, 200)

        preflight = self.client.options(
            "/api/auth/register",
            HTTP_ORIGIN="http://localhost:3000",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
        )
        self.assertNotEqual(preflight.status_code, 404)
        self.assertEqual(preflight["Access-Control-Allow-Origin"], "http://localhost:3000")

        login_preflight = self.client.options(
            "/api/auth/login",
            HTTP_ORIGIN="http://127.0.0.1:3000",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
        )
        self.assertNotEqual(login_preflight.status_code, 404)
        self.assertEqual(login_preflight["Access-Control-Allow-Origin"], "http://127.0.0.1:3000")

        register = self.client.post(
            "/api/auth/register/",
            data=json.dumps({"email": "teacher@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        self.assertEqual(register.status_code, 201)

        login = self.client.post(
            "/api/auth/login/",
            data=json.dumps({"email": "teacher@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        self.assertEqual(login.status_code, 200)
        token = login.json()["access_token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        unauthenticated_listing = self.client.get("/api/gradings")
        self.assertEqual(unauthenticated_listing.status_code, 401)

        root = Path(__file__).resolve().parents[3]
        exam_path = root / "docs" / "samples" / "Q&A" / "Homework_3_sols.pdf"
        student_path = root / "docs" / "samples" / "studentAnswers" / "2.pdf"
        exam_upload = SimpleUploadedFile(
            "Homework_3_sols.pdf",
            exam_path.read_bytes(),
            content_type="application/pdf",
        )
        student_upload = SimpleUploadedFile(
            "2.pdf",
            student_path.read_bytes(),
            content_type="application/pdf",
        )

        create = self.client.post(
            "/api/gradings",
            data={"exam_pdf": exam_upload, "student_pdf": student_upload},
            **auth,
        )
        self.assertEqual(create.status_code, 200)
        self.assertEqual(create.json()["status"], "completed")
        self.assertEqual(create.json()["stage"], "completed")

        listing = self.client.get("/api/gradings/", **auth)
        self.assertEqual(listing.status_code, 200)
        grading_id = listing.json()[0]["id"]
        self.assertEqual(listing.json()[0]["stage"], "completed")
        self.assertEqual(listing.json()[0]["exam_filename"], "Homework_3_sols.pdf")
        self.assertEqual(listing.json()[0]["student_filename"], "2.pdf")
        self.assertIsNotNone(listing.json()[0]["duration_ms"])

        detail = self.client.get(f"/api/gradings/{grading_id}", **auth)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["result"]["grading_id"], grading_id)
        self.assertEqual(detail.json()["progress_percent"], 100)

        status_detail = self.client.get(f"/api/gradings/{grading_id}/status", **auth)
        self.assertEqual(status_detail.status_code, 200)
        self.assertEqual(status_detail.json()["status"], "completed")
        self.assertEqual(status_detail.json()["stage"], "completed")

        trace_path = self.artifacts_root / grading_id / "debug_trace.jsonl"
        self.assertTrue(trace_path.exists())
        trace_content = trace_path.read_text()
        self.assertIn("grading.job_started", trace_content)
        self.assertIn("grading.job_completed", trace_content)

        override = self.client.patch(
            f"/api/gradings/{grading_id}/override",
            data=json.dumps(
                {
                    "question_id": create.json()["result"]["questions"][0]["question_id"],
                    "new_score": 1.0,
                    "reason": "Teacher adjustment",
                }
            ),
            content_type="application/json",
            **auth,
        )
        self.assertEqual(override.status_code, 200)
        self.assertEqual(override.json()["new_score"], 1.0)

        delete_response = self.client.delete(
            "/api/gradings",
            data=json.dumps({"grading_ids": [grading_id]}),
            content_type="application/json",
            **auth,
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["deleted_count"], 1)

        listing_after_delete = self.client.get("/api/gradings/", **auth)
        self.assertEqual(listing_after_delete.status_code, 200)
        self.assertEqual(listing_after_delete.json(), [])

        detail_after_delete = self.client.get(f"/api/gradings/{grading_id}", **auth)
        self.assertEqual(detail_after_delete.status_code, 404)

        self.assertFalse((settings.UPLOADS_ROOT / grading_id).exists())
        self.assertFalse((self.artifacts_root / grading_id).exists())

    def test_api_docs_exposed(self) -> None:
        schema = self.client.get("/api/schema/?format=json")
        self.assertEqual(schema.status_code, 200)
        payload = schema.json()
        self.assertIn("/api/auth/login/", payload["paths"])
        self.assertIn("/api/gradings/", payload["paths"])

        swagger = self.client.get("/api/docs/")
        self.assertEqual(swagger.status_code, 200)
        self.assertContains(swagger, "swagger-ui")

    def test_batch_flow(self) -> None:
        register = self.client.post(
            "/api/auth/register/",
            data=json.dumps({"email": "batch@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        self.assertEqual(register.status_code, 201)

        login = self.client.post(
            "/api/auth/login/",
            data=json.dumps({"email": "batch@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        token = login.json()["access_token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        root = Path(__file__).resolve().parents[3]
        exam_path = root / "docs" / "samples" / "Q&A" / "Homework_3_sols.pdf"
        student_a = root / "docs" / "samples" / "studentAnswers" / "2.pdf"
        student_b = root / "docs" / "samples" / "studentAnswers" / "3.pdf"

        response = self.client.post(
            "/api/gradings/batch",
            data={
                "exam_pdf": SimpleUploadedFile(
                    "Homework_3_sols.pdf",
                    exam_path.read_bytes(),
                    content_type="application/pdf",
                ),
                "student_pdfs": [
                    SimpleUploadedFile("2.pdf", student_a.read_bytes(), content_type="application/pdf"),
                    SimpleUploadedFile("3.pdf", student_b.read_bytes(), content_type="application/pdf"),
                ],
            },
            **auth,
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["queue_size"], 2)
        self.assertEqual(len(payload["runs"]), 2)
        self.assertEqual({run["student_filename"] for run in payload["runs"]}, {"2.pdf", "3.pdf"})

    def test_pdf_export_returns_rendered_pdf(self) -> None:
        if not REPORTLAB_AVAILABLE:
            self.skipTest("reportlab is not installed in this environment")

        register = self.client.post(
            "/api/auth/register/",
            data=json.dumps({"email": "pdf-export@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        self.assertEqual(register.status_code, 201)

        login = self.client.post(
            "/api/auth/login/",
            data=json.dumps({"email": "pdf-export@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        token = login.json()["access_token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        user = get_user_model().objects.get(email="pdf-export@example.com")

        run = GradingRun.objects.create(
            user=user,
            status="completed",
            exam_filename="exam.pdf",
            exam_storage_path="exam.pdf",
            student_filename="student.pdf",
            student_storage_path="student.pdf",
            total_score=4.5,
            max_score=5.0,
            duration_ms=12345,
            result_json={
                "grading_id": "demo",
                "status": "completed",
                "total_score": 4.5,
                "max_score": 5.0,
                "questions": [
                    {
                        "question_id": "1",
                        "awarded_marks": 4.5,
                        "max_marks": 5.0,
                        "feedback": "Strong answer overall.",
                        "score_rationale": "The response is substantially correct, with only a minor notation issue.",
                        "correct_elements": ["Uses the required method.", "Gives the correct final answer."],
                        "missing_or_incorrect_elements": ["Minor notation issue."],
                        "improvement_suggestions": ["Label the final step more clearly."],
                        "visible_evidence": [{"page": 1, "evidence": "Student writes the final answer clearly."}],
                        "evidence_summaries": [{"page": 1, "summary": "Final answer supports the awarded score."}],
                    }
                ],
            },
        )

        response = self.client.post(
            "/api/gradings/export",
            data=json.dumps({"grading_ids": [str(run.id)]}),
            content_type="application/json",
            HTTP_ACCEPT="application/pdf",
            **auth,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 500)
        pdf_text = response.content.decode("latin-1", errors="ignore")
        self.assertIn("student.pdf", pdf_text)
        self.assertIn("exam.pdf", pdf_text)
        self.assertIn("substantially correct", pdf_text)

    def test_pdf_export_handles_missing_optional_fields(self) -> None:
        if not REPORTLAB_AVAILABLE:
            self.skipTest("reportlab is not installed in this environment")

        register = self.client.post(
            "/api/auth/register/",
            data=json.dumps({"email": "pdf-missing@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        self.assertEqual(register.status_code, 201)

        login = self.client.post(
            "/api/auth/login/",
            data=json.dumps({"email": "pdf-missing@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        token = login.json()["access_token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        user = get_user_model().objects.get(email="pdf-missing@example.com")

        run_a = GradingRun.objects.create(
            user=user,
            status="failed",
            exam_filename="exam-a.pdf",
            exam_storage_path="exam-a.pdf",
            student_filename="student-a.pdf",
            student_storage_path="student-a.pdf",
            error_message="Export still needs to show the failure message.",
            result_json={"grading_id": "a", "status": "failed", "questions": []},
        )
        run_b = GradingRun.objects.create(
            user=user,
            status="completed",
            exam_filename="exam-b.pdf",
            exam_storage_path="exam-b.pdf",
            student_filename="student-b.pdf",
            student_storage_path="student-b.pdf",
            total_score=2.0,
            max_score=3.0,
            result_json={
                "grading_id": "b",
                "status": "completed",
                "questions": [
                    {
                        "question_id": "2",
                        "awarded_marks": 2.0,
                        "max_marks": 3.0,
                        "score_rationale": "Partial credit is awarded for the valid setup.",
                        "correct_elements": ["Valid setup."],
                        "missing_or_incorrect_elements": [],
                        "improvement_suggestions": [],
                    }
                ],
            },
        )

        response = self.client.post(
            "/api/gradings/export",
            data=json.dumps({"grading_ids": [str(run_a.id), str(run_b.id)]}),
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        pdf_text = response.content.decode("latin-1", errors="ignore")
        self.assertIn("student-a.pdf", pdf_text)
        self.assertIn("student-b.pdf", pdf_text)
        self.assertIn("Export still needs to show the failure message.", pdf_text)

    def test_delete_rejects_non_terminal_runs(self) -> None:
        register = self.client.post(
            "/api/auth/register/",
            data=json.dumps({"email": "delete-check@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        self.assertEqual(register.status_code, 201)

        login = self.client.post(
            "/api/auth/login/",
            data=json.dumps({"email": "delete-check@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        token = login.json()["access_token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        user = get_user_model().objects.get(email="delete-check@example.com")
        run = GradingRun.objects.create(
            user=user,
            status="pending",
            exam_filename="exam.pdf",
            exam_storage_path="pending",
            student_filename="student.pdf",
            student_storage_path="pending",
        )

        response = self.client.delete(
            "/api/gradings",
            data=json.dumps({"grading_ids": [str(run.id)]}),
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Only completed, failed, or canceled grading runs can be removed", response.json()["detail"])

    def test_stale_timeout_status_is_exposed_as_failed(self) -> None:
        register = self.client.post(
            "/api/auth/register/",
            data=json.dumps({"email": "stale-timeout@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        self.assertEqual(register.status_code, 201)

        login = self.client.post(
            "/api/auth/login/",
            data=json.dumps({"email": "stale-timeout@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        token = login.json()["access_token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        user = get_user_model().objects.get(email="stale-timeout@example.com")
        run = GradingRun.objects.create(
            user=user,
            status="timed_out",
            exam_filename="exam.pdf",
            exam_storage_path="pending",
            student_filename="student.pdf",
            student_storage_path="pending",
            error_message="Grading timed out",
            result_json={"grading_id": "demo", "status": "timed_out", "questions": []},
        )

        listing = self.client.get("/api/gradings", **auth)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["status"], "failed")
        self.assertEqual(listing.json()[0]["stage"], "failed")

        detail = self.client.get(f"/api/gradings/{run.id}", **auth)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["status"], "failed")
        self.assertEqual(detail.json()["result"]["status"], "failed")

    def test_cancel_pending_run(self) -> None:
        register = self.client.post(
            "/api/auth/register/",
            data=json.dumps({"email": "cancel-pending@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        self.assertEqual(register.status_code, 201)

        login = self.client.post(
            "/api/auth/login/",
            data=json.dumps({"email": "cancel-pending@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        token = login.json()["access_token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        user = get_user_model().objects.get(email="cancel-pending@example.com")
        run = GradingRun.objects.create(
            user=user,
            status="pending",
            exam_filename="exam.pdf",
            exam_storage_path="pending",
            student_filename="student.pdf",
            student_storage_path="pending",
        )
        initialize_progress(run, get_grading_settings())

        response = self.client.patch(f"/api/gradings/{run.id}/cancel", content_type="application/json", **auth)
        self.assertEqual(response.status_code, 200)

        run.refresh_from_db()
        self.assertEqual(run.status, "canceled")

        delete_response = self.client.delete(
            "/api/gradings",
            data=json.dumps({"grading_ids": [str(run.id)]}),
            content_type="application/json",
            **auth,
        )
        self.assertEqual(delete_response.status_code, 200)

    def test_pending_run_has_no_started_at_until_processing_begins(self) -> None:
        register = self.client.post(
            "/api/auth/register/",
            data=json.dumps({"email": "pending-start@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        self.assertEqual(register.status_code, 201)

        user = get_user_model().objects.get(email="pending-start@example.com")
        run = GradingRun.objects.create(
            user=user,
            status="pending",
            exam_filename="exam.pdf",
            exam_storage_path="pending",
            student_filename="student.pdf",
            student_storage_path="pending",
        )
        runtime_settings = get_grading_settings()
        initialize_progress(run, runtime_settings)

        pending_snapshot = get_progress_snapshot(run)
        self.assertIsNone(pending_snapshot["started_at"])

        update_run_progress(
            run=run,
            store=GradingProgressStore(runtime_settings, str(run.id)),
            status="processing",
            stage="processing",
            progress_percent=15,
            status_message="Processing",
        )
        run.refresh_from_db()
        processing_snapshot = get_progress_snapshot(run)
        self.assertIsNotNone(processing_snapshot["started_at"])

    def test_processing_cancellation_in_batch_allows_next_pending_run(self) -> None:
        register = self.client.post(
            "/api/auth/register/",
            data=json.dumps({"email": "cancel-processing@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        self.assertEqual(register.status_code, 201)

        login = self.client.post(
            "/api/auth/login/",
            data=json.dumps({"email": "cancel-processing@example.com", "password": "strong-password"}),
            content_type="application/json",
        )
        token = login.json()["access_token"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        user = get_user_model().objects.get(email="cancel-processing@example.com")
        run_a = GradingRun.objects.create(
            user=user,
            status="pending",
            exam_filename="exam.pdf",
            exam_storage_path="exam-a.pdf",
            student_filename="student-a.pdf",
            student_storage_path="student-a.pdf",
            model_deployment="mock",
        )
        run_b = GradingRun.objects.create(
            user=user,
            status="pending",
            exam_filename="exam.pdf",
            exam_storage_path="exam-b.pdf",
            student_filename="student-b.pdf",
            student_storage_path="student-b.pdf",
            model_deployment="mock",
        )
        runtime_settings = get_grading_settings()
        initialize_progress(run_a, runtime_settings)
        initialize_progress(run_b, runtime_settings)

        class SlowMockOrchestrator:
            def __init__(self, settings):
                self._settings = settings
                self._delegate = MockGradingOrchestrator(settings)

            async def grade(self, *, run_id, exam_pdf_path, student_pdf_path, progress_hook=None):
                if progress_hook is not None:
                    for index, progress in enumerate((25, 40, 55, 70, 85), start=1):
                        progress_hook("processing", progress, "Processing")
                        if run_id == str(run_a.id) and index == 1:
                            cancellation_path = cancellation_request_path(self._settings, run_id)
                            cancellation_path.parent.mkdir(parents=True, exist_ok=True)
                            cancellation_path.write_text(json.dumps({"requested_at": time.time()}))
                        await asyncio.sleep(0.05)
                return await self._delegate.grade(
                    run_id=run_id,
                    exam_pdf_path=exam_pdf_path,
                    student_pdf_path=student_pdf_path,
                    progress_hook=progress_hook,
                )

        with patch("grading_engine.orchestrator.build_grading_orchestrator", side_effect=lambda settings: SlowMockOrchestrator(settings)):
            _run_batch_grading_jobs(run_ids=[str(run_a.id), str(run_b.id)], runtime_settings=runtime_settings)

        run_a.refresh_from_db()
        run_b.refresh_from_db()
        self.assertEqual(run_a.status, "canceled")
        self.assertEqual(run_b.status, "completed")
