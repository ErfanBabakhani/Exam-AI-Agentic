from __future__ import annotations

from grading_engine.azure_client import AzureGraderClient, StructuredCompletion
from grading_engine.pdf_preprocessor import PDFPreprocessor, ProcessedDocument
from grading_engine.schemas import ExamUnderstandingResult


class ExamUnderstandingAgent:
    def __init__(self, client: AzureGraderClient) -> None:
        self._client = client

    async def run(
        self,
        *,
        run_id: str,
        exam_document: ProcessedDocument,
    ) -> StructuredCompletion[ExamUnderstandingResult]:
        prompt = (
            "You are an exam-structure parser. Extract all questions and the official solution or "
            "mark-scheme content associated with each question. Do not grade the student. Detect "
            "explicit max marks only when they are clearly present. Keep fields concise and return only "
            "strict JSON matching the schema."
        )
        return await self._client.complete_structured(
            stage="exam_understanding",
            run_id=run_id,
            system_prompt=prompt,
            user_text=PDFPreprocessor.to_json({"pages": exam_document.as_page_payload()}),
            response_model=ExamUnderstandingResult,
        )
