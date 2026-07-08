from __future__ import annotations

from grading_engine.azure_client import AzureGraderClient, StructuredCompletion
from grading_engine.pdf_preprocessor import PDFPreprocessor
from grading_engine.schemas import ExamQuestion, RubricResult


class RubricInferenceAgent:
    def __init__(self, client: AzureGraderClient) -> None:
        self._client = client

    async def run(
        self,
        *,
        run_id: str,
        questions: list[ExamQuestion],
        default_question_max_marks: float,
    ) -> StructuredCompletion[RubricResult]:
        prompt = (
            "You are a rubric builder. Convert each official solution into grading criteria. "
            "If explicit marks are present, preserve them and set rubric_source='official_explicit'. "
            "If marks are absent, infer a defensible criterion breakdown and set max_marks_source "
            "to 'system_default' when you use the provided default question total. Keep criterion wording "
            "compact and return only strict JSON."
        )
        payload = {
            "default_question_max_marks": default_question_max_marks,
            "questions": [question.model_dump(mode="json") for question in questions],
        }
        return await self._client.complete_structured(
            stage="rubric_inference",
            run_id=run_id,
            system_prompt=prompt,
            user_text=PDFPreprocessor.to_json(payload),
            response_model=RubricResult,
        )
