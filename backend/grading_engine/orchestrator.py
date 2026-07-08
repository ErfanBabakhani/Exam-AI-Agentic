from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable

from grading_engine.cost_logger import ModelCallTrace
from grading_engine.runtime import GradingSettings
from grading_engine.schemas import (
    CriterionScore,
    Evidence,
    ExamQuestion,
    ExamUnderstandingResult,
    GradingResult,
    LowScoreRecheckQuestion,
    QuestionGradeResult,
    RubricCriterionItem,
    RubricQuestion,
    StudentAnswer,
    StudentInspectionResult,
)
from grading_engine.trace_logger import append_run_trace


@dataclass(slots=True)
class GradingExecution:
    result: GradingResult
    exam: ExamUnderstandingResult
    rubric_questions: list[RubricQuestion]
    student_inspection: StudentInspectionResult
    model_calls: list[ModelCallTrace]
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float | None


class BaseGradingOrchestrator:
    async def grade(
        self,
        *,
        run_id: str,
        exam_pdf_path: Path,
        student_pdf_path: Path,
        progress_hook: Callable[[str, int, str], None] | None = None,
    ) -> GradingExecution:
        raise NotImplementedError


class RealGradingOrchestrator(BaseGradingOrchestrator):
    def __init__(self, settings: GradingSettings) -> None:
        from grading_engine.agents.exam_understanding import ExamUnderstandingAgent
        from grading_engine.agents.grader import GradingAgent
        from grading_engine.agents.low_score_recheck import LowScoreRecheckAgent
        from grading_engine.agents.rubric_inference import RubricInferenceAgent
        from grading_engine.agents.student_inspection import StudentInspectionAgent
        from grading_engine.exam_cache import ExamAnalysisCache
        from grading_engine.agents.validator import GradingValidator
        from grading_engine.azure_client import AzureGraderClient
        from grading_engine.pdf_preprocessor import PDFPreprocessor

        self._settings = settings
        self._preprocessor = PDFPreprocessor(settings)
        self._exam_cache = ExamAnalysisCache(settings)
        self._client = AzureGraderClient(settings)
        self._exam_agent = ExamUnderstandingAgent(self._client)
        self._rubric_agent = RubricInferenceAgent(self._client)
        self._inspection_agent = StudentInspectionAgent(
            self._client,
            artifacts_root=settings.artifacts_root,
            question_batch_size=settings.inspection_batch_size,
        )
        self._grading_agent = GradingAgent(self._client)
        self._low_score_recheck_agent = LowScoreRecheckAgent(self._client, artifacts_root=settings.artifacts_root)
        self._validator = GradingValidator()

    async def grade(
        self,
        *,
        run_id: str,
        exam_pdf_path: Path,
        student_pdf_path: Path,
        progress_hook: Callable[[str, int, str], None] | None = None,
    ) -> GradingExecution:
        from grading_engine.agents.equivalence import build_equivalence_seeds

        started = perf_counter()
        append_run_trace(
            self._settings,
            run_id,
            "grading.execution_started",
            exam_pdf_path=str(exam_pdf_path),
            student_pdf_path=str(student_pdf_path),
        )
        if progress_hook is not None:
            progress_hook("extracting_exam", 14, "Extracting exam content")
        exam_document = self._preprocessor.process(run_id=run_id, document_kind="exam", pdf_path=exam_pdf_path)
        if progress_hook is not None:
            progress_hook("processing_student_pdf", 28, "Reading student answer PDF")
        student_document = self._preprocessor.process(
            run_id=run_id,
            document_kind="student",
            pdf_path=student_pdf_path,
        )

        if progress_hook is not None:
            progress_hook("calling_ai", 42, "Understanding exam and mark scheme")
        cached_exam_bundle = self._exam_cache.load(
            exam_pdf_path=exam_pdf_path,
            default_question_max_marks=self._settings.default_question_max_marks,
        )
        traces: list[ModelCallTrace] = []
        if cached_exam_bundle is None:
            append_run_trace(self._settings, run_id, "exam_cache.miss")
            exam_completion = await self._exam_agent.run(run_id=run_id, exam_document=exam_document)
            exam_result = exam_completion.parsed
            traces.append(exam_completion.trace)
        else:
            append_run_trace(self._settings, run_id, "exam_cache.hit")
            exam_result = cached_exam_bundle.exam
            traces.append(
                cached_exam_bundle.as_trace(
                    stage="exam_understanding_cache",
                    deployment=self._client.deployment,
                    run_id=run_id,
                )
            )
        if not exam_result.questions:
            raise RuntimeError("The exam parser did not return any questions.")

        if progress_hook is not None:
            progress_hook("calling_ai", 56, "Building grading rubric")
        if cached_exam_bundle is None:
            rubric_completion = await self._rubric_agent.run(
                run_id=run_id,
                questions=exam_result.questions,
                default_question_max_marks=self._settings.default_question_max_marks,
            )
            rubric_result = rubric_completion.parsed
            traces.append(rubric_completion.trace)
            self._exam_cache.save(
                exam_pdf_path=exam_pdf_path,
                default_question_max_marks=self._settings.default_question_max_marks,
                exam=exam_result,
                rubric=rubric_result,
            )
        else:
            rubric_result = cached_exam_bundle.rubric
            traces.append(
                cached_exam_bundle.as_trace(
                    stage="rubric_inference_cache",
                    deployment=self._client.deployment,
                    run_id=run_id,
                )
            )
        if not rubric_result.questions:
            raise RuntimeError("The rubric builder did not return any grading criteria.")

        if progress_hook is not None:
            progress_hook("calling_ai", 70, "Reading the student answer PDF")
        student_inspection, inspection_traces = await self._inspection_agent.run(
            run_id=run_id,
            student_document=student_document,
            exam_questions=exam_result.questions,
        )

        equivalence_seeds = build_equivalence_seeds(rubric_result.questions)
        if progress_hook is not None:
            progress_hook("calling_ai", 84, "Asking the AI grader")
        grading_completion = await self._grading_agent.run(
            run_id=run_id,
            exam_questions=exam_result.questions,
            rubric_questions=rubric_result.questions,
            student_answers=student_inspection.answers,
            equivalence_seeds=equivalence_seeds,
        )

        duration_ms = int((perf_counter() - started) * 1000)
        if progress_hook is not None:
            progress_hook("validating_result", 96, "Validating structured result")
        result = self._validator.run(
            grading_id=run_id,
            model_deployment=self._client.deployment,
            duration_ms=duration_ms,
            exam_questions=exam_result.questions,
            rubric_questions=rubric_result.questions,
            student_answers=student_inspection.answers,
            grading_draft=grading_completion.parsed,
        )
        recheck_updates, recheck_traces = await self._low_score_recheck_agent.run(
            run_id=run_id,
            exam_questions=exam_result.questions,
            rubric_questions=rubric_result.questions,
            student_answers=student_inspection.answers,
            current_result=result,
            student_document=student_document,
            equivalence_seeds=equivalence_seeds,
        )
        if recheck_updates:
            self._apply_recheck_updates(result=result, updates=recheck_updates)
            result = self._validator.normalize_existing_result(
                result=result,
                exam_questions=exam_result.questions,
                rubric_questions=rubric_result.questions,
                student_answers=student_inspection.answers,
            )
        traces.extend([*inspection_traces, grading_completion.trace])
        traces.extend(recheck_traces)
        costs = [trace.cost_usd for trace in traces if trace.cost_usd is not None]
        append_run_trace(
            self._settings,
            run_id,
            "grading.execution_completed",
            duration_ms=duration_ms,
            model_call_count=len(traces),
            total_prompt_tokens=sum(trace.prompt_tokens or 0 for trace in traces),
            total_completion_tokens=sum(trace.completion_tokens or 0 for trace in traces),
        )
        return GradingExecution(
            result=result,
            exam=exam_result,
            rubric_questions=rubric_result.questions,
            student_inspection=student_inspection,
            model_calls=traces,
            total_prompt_tokens=sum(trace.prompt_tokens or 0 for trace in traces),
            total_completion_tokens=sum(trace.completion_tokens or 0 for trace in traces),
            total_cost_usd=round(sum(costs), 6) if costs else None,
        )

    @staticmethod
    def _apply_recheck_updates(*, result: GradingResult, updates: dict[str, LowScoreRecheckQuestion]) -> None:
        for question in result.questions:
            update = updates.get(question.question_id)
            if update is None:
                continue
            original_marks = question.awarded_marks
            revised_marks = round(min(question.max_marks, max(original_marks, update.awarded_marks)), 2)
            question.awarded_marks = revised_marks
            if update.score_rationale:
                question.feedback = update.score_rationale
                question.score_rationale = update.score_rationale
            if update.correct_elements:
                question.correct_elements = update.correct_elements[:4]
            if update.missing_or_incorrect_elements:
                question.missing_or_incorrect_elements = update.missing_or_incorrect_elements[:4]
            if update.improvement_suggestions:
                question.improvement_suggestions = update.improvement_suggestions[:3]
            if update.visible_evidence:
                question.visible_evidence = update.visible_evidence[:3]
            if update.confidence is not None:
                question.confidence = update.confidence
            question.needs_human_review = question.needs_human_review or update.needs_human_review or revised_marks != original_marks
        result.total_score = round(sum(question.awarded_marks for question in result.questions), 2)


class MockGradingOrchestrator(BaseGradingOrchestrator):
    def __init__(self, settings: GradingSettings) -> None:
        self._settings = settings

    async def grade(
        self,
        *,
        run_id: str,
        exam_pdf_path: Path,
        student_pdf_path: Path,
        progress_hook: Callable[[str, int, str], None] | None = None,
    ) -> GradingExecution:
        started = perf_counter()
        if progress_hook is not None:
            progress_hook("calling_ai", 70, "Mock grading mode is generating a placeholder result")
        question_ids = re.findall(r"(?m)^\s*(\d+)\.", exam_pdf_path.stem) or ["1"]
        questions = [
            ExamQuestion(
                question_id=question_id,
                question_text=f"Mock question {question_id}",
                official_solution="Mock grading mode does not call Azure OpenAI.",
                source_pages=[1],
                has_diagram_or_formula=False,
                explicit_max_marks_found=False,
                explicit_max_marks=None,
            )
            for question_id in question_ids
        ]
        rubric_questions = [
            RubricQuestion(
                question_id=question.question_id,
                rubric_source="system_default",
                max_marks_source="system_default",
                max_marks=self._settings.default_question_max_marks,
                criteria=[
                    RubricCriterionItem(
                        criterion_id=f"{question.question_id}.1",
                        description="Placeholder criterion for mock mode.",
                        expected_answer=question.official_solution,
                        marks=self._settings.default_question_max_marks,
                        source="system_default",
                    )
                ],
            )
            for question in questions
        ]
        answers = [
            StudentAnswer(
                question_id=question.question_id,
                status="unclear",
                transcription="Mock grading mode is enabled; no Azure call was made.",
                final_answer=None,
                derivation_summary=None,
                uncertain_parts=[],
                student_claims=[],
                source_pages=[1],
                evidence=Evidence(page=1, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                confidence=0.0,
                needs_human_review=True,
            )
            for question in questions
        ]
        question_results = [
            QuestionGradeResult(
                question_id=question.question_id,
                awarded_marks=0.0,
                max_marks=self._settings.default_question_max_marks,
                rubric_source="system_default",
                max_marks_source="system_default",
                feedback="Mock grading mode: grading was intentionally skipped.",
                score_rationale="Mock grading mode is enabled, so this question was not graded by Azure OpenAI.",
                correct_elements=[],
                missing_or_incorrect_elements=["No live model analysis was performed in mock grading mode."],
                improvement_suggestions=["Run with Azure OpenAI enabled to generate question-specific grading rationale."],
                evidence_summaries=[],
                visible_evidence=[],
                confidence=0.0,
                needs_human_review=True,
                criterion_scores=[
                    CriterionScore(
                        criterion_id=f"{question.question_id}.1",
                        awarded=0.0,
                        max=self._settings.default_question_max_marks,
                        match_type="missing",
                        verification_status="inconclusive",
                        feedback="Mock grading mode.",
                        confidence=0.0,
                        needs_human_review=True,
                        evidence=answers[index].evidence,
                    )
                ],
            )
            for index, question in enumerate(questions)
        ]
        duration_ms = int((perf_counter() - started) * 1000)
        result = GradingResult(
            grading_id=run_id,
            status="completed",
            model_deployment="mock-local-mode",
            total_score=0.0,
            max_score=round(self._settings.default_question_max_marks * len(question_results), 2),
            duration_ms=duration_ms,
            questions=question_results,
        )
        trace = ModelCallTrace(
            stage="mock_grading",
            deployment="mock-local-mode",
            prompt_tokens=0,
            completion_tokens=0,
            duration_ms=duration_ms,
            cost_usd=0.0,
            status="ok",
            error_message=None,
            run_id=run_id,
        )
        return GradingExecution(
            result=result,
            exam=ExamUnderstandingResult(questions=questions),
            rubric_questions=rubric_questions,
            student_inspection=StudentInspectionResult(answers=answers),
            model_calls=[trace],
            total_prompt_tokens=0,
            total_completion_tokens=0,
            total_cost_usd=0.0,
        )


def build_grading_orchestrator(settings: GradingSettings) -> BaseGradingOrchestrator:
    if settings.mock_grading_enabled:
        return MockGradingOrchestrator(settings)
    if not settings.azure_configured:
        raise RuntimeError(
            "Azure OpenAI credentials are not configured. Set AZURE_OPENAI_API_KEY, "
            "AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, and AZURE_OPENAI_API_VERSION."
        )
    return RealGradingOrchestrator(settings)
