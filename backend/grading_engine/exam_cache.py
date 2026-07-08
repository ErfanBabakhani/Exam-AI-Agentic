from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from grading_engine.cost_logger import ModelCallTrace
from grading_engine.runtime import GradingSettings
from grading_engine.schemas import ExamUnderstandingResult, RubricResult


CACHE_SCHEMA_VERSION = 1


def compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class CachedExamBundle:
    exam: ExamUnderstandingResult
    rubric: RubricResult

    def as_trace(self, *, stage: str, deployment: str, run_id: str) -> ModelCallTrace:
        return ModelCallTrace(
            stage=stage,
            deployment=deployment,
            prompt_tokens=0,
            completion_tokens=0,
            duration_ms=0,
            cost_usd=0.0,
            status="cached",
            error_message=None,
            run_id=run_id,
        )


class ExamAnalysisCache:
    def __init__(self, settings: GradingSettings) -> None:
        self._settings = settings
        self._root = settings.artifacts_root / "_cache" / "exam_analysis"

    def load(self, *, exam_pdf_path: Path, default_question_max_marks: float) -> CachedExamBundle | None:
        cache_path = self._cache_path(exam_pdf_path)
        if not cache_path.exists():
            return None
        try:
            payload = json.loads(cache_path.read_text())
        except json.JSONDecodeError:
            return None

        if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
            return None
        if payload.get("deployment") != self._settings.azure_openai_deployment:
            return None
        if payload.get("default_question_max_marks") != default_question_max_marks:
            return None

        try:
            return CachedExamBundle(
                exam=ExamUnderstandingResult.model_validate(payload["exam"]),
                rubric=RubricResult.model_validate(payload["rubric"]),
            )
        except Exception:
            return None

    def save(
        self,
        *,
        exam_pdf_path: Path,
        default_question_max_marks: float,
        exam: ExamUnderstandingResult,
        rubric: RubricResult,
    ) -> None:
        cache_path = self._cache_path(exam_pdf_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "deployment": self._settings.azure_openai_deployment,
            "default_question_max_marks": default_question_max_marks,
            "exam": exam.model_dump(mode="json"),
            "rubric": rubric.model_dump(mode="json"),
        }
        cache_path.write_text(json.dumps(payload))

    def _cache_path(self, exam_pdf_path: Path) -> Path:
        return self._root / f"{compute_file_sha256(exam_pdf_path)}.json"
