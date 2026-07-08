from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from django.utils import timezone

from apps.grading.models import GradingRun
from apps.grading.serializers import GradingRunDetailSerializer


logger = logging.getLogger(__name__)


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")


def _format_duration(duration_ms: int | None) -> str:
    if not duration_ms or duration_ms <= 0:
        return "Not recorded"
    return f"{duration_ms / 1000:.1f}s"


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _map_question(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": question.get("question_id") or question.get("number") or "-",
        "score": question.get("awarded_marks") or question.get("score") or 0,
        "max_score": question.get("max_marks") or question.get("max_score") or 0,
        "rationale": _first_non_empty(question.get("score_rationale"), question.get("feedback"), "No rationale recorded."),
        "correct": question.get("correct_elements") or [],
        "missing": question.get("missing_or_incorrect_elements") or [],
        "improve": question.get("improvement_suggestions") or [],
        "visible_evidence": question.get("visible_evidence") or [],
        "evidence_used": question.get("evidence_summaries") or [],
    }


def _map_run(run: GradingRun) -> dict[str, Any]:
    payload = GradingRunDetailSerializer(run).data
    result = payload.get("result") or {}
    questions = result.get("questions") or []
    return {
        "status": payload.get("status") or run.status,
        "student_file": payload.get("student_filename") or run.student_filename,
        "exam_file": payload.get("exam_filename") or run.exam_filename,
        "score": payload.get("total_score") if payload.get("total_score") is not None else result.get("total_score", 0),
        "max_score": payload.get("max_score") if payload.get("max_score") is not None else result.get("max_score", 0),
        "duration": _format_duration(payload.get("duration_ms")),
        "created": _format_timestamp(run.created_at),
        "completed": _format_timestamp(run.updated_at if payload.get("status") in {"completed", "failed", "canceled"} else None)
        or payload.get("completed_at"),
        "message": _first_non_empty(payload.get("error_message"), payload.get("status_message"), payload.get("status"), "No status message recorded."),
        "questions": [_map_question(question) for question in questions],
    }


def build_report_data(runs: list[GradingRun]) -> dict[str, Any]:
    run_count = len(runs)
    now = timezone.localtime()
    subtitle = "Single grading run export" if run_count == 1 else f"{run_count} grading runs exported"
    return {
        "title": "AI Grading Report",
        "subtitle": subtitle,
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "brand": "Zanista AI",
        "runs": [_map_run(run) for run in runs],
    }


def render_runs_pdf_bytes(runs: list[GradingRun]) -> bytes:
    from pdf_them.renderer import render_grading_report_pdf

    report_data = build_report_data(runs)
    with NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
        output_path = Path(tmp_file.name)
    try:
        render_grading_report_pdf(report_data, output_path)
        return output_path.read_bytes()
    except Exception:
        logger.exception("grading.pdf_export_failed", extra={"run_ids": [str(run.id) for run in runs]})
        raise
    finally:
        output_path.unlink(missing_ok=True)
