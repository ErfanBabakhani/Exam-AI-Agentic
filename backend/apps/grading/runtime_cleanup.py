from __future__ import annotations

import json
import logging
from threading import Lock

from django.db.utils import OperationalError, ProgrammingError


logger = logging.getLogger(__name__)

_cleanup_lock = Lock()
_cleanup_completed = False


def _normalize_status(status: str | None) -> str | None:
    if status in {"pending", "processing", "completed", "failed", "canceled"}:
        return status
    if status == "timed_out":
        return "failed"
    if status is None:
        return None
    return "processing"


def normalize_grading_run_statuses() -> None:
    global _cleanup_completed

    with _cleanup_lock:
        if _cleanup_completed:
            return

        try:
            from apps.grading.models import GradingRun
        except Exception:
            return

        try:
            runs = list(GradingRun.objects.all().only("id", "status", "result_json"))
        except (OperationalError, ProgrammingError):
            return

        updated_runs = 0
        updated_results = 0
        for run in runs:
            changed = False
            normalized_status = _normalize_status(run.status)
            if normalized_status != run.status:
                run.status = normalized_status
                changed = True
                updated_runs += 1

            result_json = run.result_json
            if isinstance(result_json, dict):
                result_status = result_json.get("status")
                normalized_result_status = _normalize_status(result_status)
                if normalized_result_status != result_status:
                    result_json = json.loads(json.dumps(result_json))
                    result_json["status"] = normalized_result_status
                    run.result_json = result_json
                    changed = True
                    updated_results += 1

            if changed:
                run.save(update_fields=["status", "result_json", "updated_at"])

        if updated_runs or updated_results:
            logger.info(
                json.dumps(
                    {
                        "event": "grading.status_cleanup_completed",
                        "updated_run_statuses": updated_runs,
                        "updated_result_statuses": updated_results,
                    }
                )
            )

        _cleanup_completed = True
