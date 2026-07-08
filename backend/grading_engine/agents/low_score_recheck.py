from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from mimetypes import guess_type
from pathlib import Path
from textwrap import dedent

from grading_engine.azure_client import AzureGraderClient
from grading_engine.cost_logger import ModelCallTrace
from grading_engine.pdf_preprocessor import PDFPreprocessor, ProcessedDocument
from grading_engine.schemas import (
    ExamQuestion,
    GradingResult,
    LowScoreRecheckQuestion,
    LowScoreRecheckResult,
    QuestionGradeResult,
    RubricQuestion,
    StudentAnswer,
)
from grading_engine.tools.crop_image import crop_image
from grading_engine.tools.zoom_image import zoom_image
from grading_engine.trace_logger import append_run_trace


def _image_to_data_url(path: Path) -> str:
    mime_type, _ = guess_type(str(path))
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _has_math_signal(text: str) -> bool:
    return any(signal in text for signal in ("=", "/", "∫", ">", "<", "+", "-", "*"))


def _has_substantive_visible_work(answer: StudentAnswer | None) -> bool:
    if answer is None:
        return False
    if answer.student_claims or answer.final_answer or answer.derivation_summary or answer.source_pages:
        return True
    transcription = " ".join(answer.transcription.split()).strip().lower()
    return bool(transcription and "no student answer" not in transcription and "no answer was" not in transcription)


def _extract_number_tokens(text: str) -> list[str]:
    return list(dict.fromkeys(token for token in re.findall(r"\d+(?:\.\d+)?(?:\s*/\s*\d+)?", text or "") if token))


def _digits_only(token: str) -> str:
    return "".join(character for character in token if character.isdigit())


def _differs_by_one_missing_digit(expected: str, observed: str) -> bool:
    if len(expected) - len(observed) != 1:
        return False
    for index in range(len(expected)):
        if expected[:index] + expected[index + 1 :] == observed:
            return True
    return False


def _has_possible_digit_drop(question: ExamQuestion, rubric: RubricQuestion, answer: StudentAnswer | None) -> bool:
    if answer is None:
        return False
    official_tokens: list[str] = []
    for text in [question.official_solution, *[item.expected_answer for item in rubric.criteria]]:
        official_tokens.extend(_extract_number_tokens(text))
    if not official_tokens:
        return False
    student_tokens: list[str] = []
    for text in [
        answer.final_answer or "",
        answer.derivation_summary or "",
        answer.transcription or "",
        *[claim.content for claim in answer.student_claims],
    ]:
        student_tokens.extend(_extract_number_tokens(text))
    for official_token in official_tokens:
        official_digits = _digits_only(official_token)
        if len(official_digits) < 3:
            continue
        for student_token in student_tokens:
            student_digits = _digits_only(student_token)
            if len(student_digits) < 2:
                continue
            if _differs_by_one_missing_digit(official_digits, student_digits):
                return True
    return False


@dataclass(slots=True)
class SuspiciousQuestion:
    exam_question: ExamQuestion
    rubric_question: RubricQuestion
    student_answer: StudentAnswer
    current_question: QuestionGradeResult | None


class LowScoreRecheckAgent:
    def __init__(self, client: AzureGraderClient, *, artifacts_root: Path) -> None:
        self._client = client
        self._artifacts_root = artifacts_root

    async def run(
        self,
        *,
        run_id: str,
        exam_questions: list[ExamQuestion],
        rubric_questions: list[RubricQuestion],
        student_answers: list[StudentAnswer],
        current_result: GradingResult,
        student_document: ProcessedDocument,
        equivalence_seeds: dict[str, list[str]],
    ) -> tuple[dict[str, LowScoreRecheckQuestion], list[ModelCallTrace]]:
        suspicious_questions = self._select_suspicious_questions(
            exam_questions=exam_questions,
            rubric_questions=rubric_questions,
            student_answers=student_answers,
            current_result=current_result,
        )
        if not suspicious_questions:
            return {}, []

        traces: list[ModelCallTrace] = []
        updates: dict[str, LowScoreRecheckQuestion] = {}
        for suspicious in suspicious_questions[:2]:
            prepared_images = self._prepare_question_images(
                run_id=run_id,
                student_document=student_document,
                question_id=suspicious.exam_question.question_id,
                answer=suspicious.student_answer,
            )
            content: list[dict] = [
                {
                    "type": "text",
                    "text": PDFPreprocessor.to_json(
                        {
                            "question": suspicious.exam_question.model_dump(mode="json"),
                            "rubric": suspicious.rubric_question.model_dump(mode="json"),
                            "student_answer": suspicious.student_answer.model_dump(mode="json"),
                            "current_result": suspicious.current_question.model_dump(mode="json") if suspicious.current_question else None,
                            "equivalence_seeds": equivalence_seeds.get(suspicious.exam_question.question_id, []),
                        }
                    ),
                }
            ]
            for image_note, image_path in prepared_images:
                content.append({"type": "text", "text": image_note})
                content.append({"type": "image_url", "image_url": {"url": _image_to_data_url(image_path), "detail": "high"}})
            append_run_trace(
                self._client.settings,
                run_id,
                "low_score_recheck.question_prepared",
                question_id=suspicious.exam_question.question_id,
                page_numbers=suspicious.student_answer.source_pages,
                image_count=len(prepared_images),
            )
            completion = await self._client.complete_structured(
                stage="low_score_recheck",
                run_id=run_id,
                system_prompt=self._prompt(),
                user_content=content,
                response_model=LowScoreRecheckResult,
                timeout_seconds=min(110.0, self._client.settings.llm_timeout_seconds),
            )
            traces.append(completion.trace)
            for question in completion.parsed.questions:
                updates[question.question_id] = question
        return updates, traces

    def _select_suspicious_questions(
        self,
        *,
        exam_questions: list[ExamQuestion],
        rubric_questions: list[RubricQuestion],
        student_answers: list[StudentAnswer],
        current_result: GradingResult,
    ) -> list[SuspiciousQuestion]:
        rubric_lookup = {question.question_id: question for question in rubric_questions}
        answer_lookup = {answer.question_id: answer for answer in student_answers}
        current_lookup = {question.question_id: question for question in current_result.questions}
        suspicious: list[SuspiciousQuestion] = []
        for exam_question in exam_questions:
            rubric_question = rubric_lookup[exam_question.question_id]
            answer = answer_lookup.get(exam_question.question_id)
            current_question = current_lookup.get(exam_question.question_id)
            if answer is None or current_question is None:
                continue
            if not self._is_suspicious_low_score(
                question=exam_question,
                rubric=rubric_question,
                answer=answer,
                current_question=current_question,
            ):
                continue
            suspicious.append(
                SuspiciousQuestion(
                    exam_question=exam_question,
                    rubric_question=rubric_question,
                    student_answer=answer,
                    current_question=current_question,
                )
            )
        return suspicious

    def _is_suspicious_low_score(
        self,
        *,
        question: ExamQuestion,
        rubric: RubricQuestion,
        answer: StudentAnswer,
        current_question,
    ) -> bool:
        if rubric.max_marks <= 0:
            return False
        if current_question.awarded_marks >= round(rubric.max_marks * 0.75, 2):
            return False
        if not _has_substantive_visible_work(answer):
            return False
        if not (
            answer.uncertain_parts
            or answer.final_answer
            or answer.derivation_summary
            or answer.student_claims
            or current_question.visible_evidence
            or current_question.correct_elements
        ):
            return False
        texts = [
            answer.final_answer or "",
            answer.derivation_summary or "",
            answer.transcription or "",
            *[claim.content for claim in answer.student_claims],
            *current_question.correct_elements,
            *current_question.missing_or_incorrect_elements,
            current_question.score_rationale or "",
        ]
        has_setup_or_conclusion = any(
            _contains_any(text, ("therefore", "hence", "concludes", "better", "choose", "integral", "setup", "compare"))
            or _has_math_signal(text)
            for text in texts
        )
        has_digit_uncertainty = any(
            _contains_any(text, ("unclear", "ambiguous", "appears", "likely intended", "partially unclear"))
            for text in texts
        ) or _has_possible_digit_drop(question, rubric, answer)
        has_equivalent_signal = bool(_extract_number_tokens(" ".join(texts))) or any(symbol in " ".join(texts) for symbol in (">", "<", "=", "/"))
        return has_setup_or_conclusion and (has_digit_uncertainty or has_equivalent_signal)

    def _prepare_question_images(
        self,
        *,
        run_id: str,
        student_document: ProcessedDocument,
        question_id: str,
        answer: StudentAnswer,
    ) -> list[tuple[str, Path]]:
        prepared: list[tuple[str, Path]] = []
        seen_paths: set[Path] = set()
        relevant_pages = [
            page_number
            for page_number in answer.source_pages
            if 1 <= page_number <= student_document.page_count
        ][: min(2, self._client.settings.max_images_per_request)]
        for page_number in relevant_pages:
            page = student_document.pages[page_number - 1]
            prepared.append((f"Student page {page.page_number} for question {question_id}.", page.image_path))
            seen_paths.add(page.image_path)
        if answer.evidence is None or answer.evidence.bbox is None:
            return prepared
        if not 1 <= answer.evidence.page <= student_document.page_count:
            return prepared
        primary_page = student_document.pages[answer.evidence.page - 1]
        page_area = max(primary_page.width * primary_page.height, 1)
        left, top, right, bottom = answer.evidence.bbox
        crop_area = max((right - left) * (bottom - top), 1)
        if crop_area >= page_area * 0.9:
            return prepared

        output_dir = self._artifacts_root / run_id / "rechecks" / question_id
        output_dir.mkdir(parents=True, exist_ok=True)
        crop_path = output_dir / f"page_{primary_page.page_number}_crop.png"
        zoom_path = output_dir / f"page_{primary_page.page_number}_crop_zoom.png"
        crop_image(primary_page.image_path, crop_path, answer.evidence.bbox)
        zoom_image(
            crop_path,
            zoom_path,
            scale=1.65,
            max_dimension=min(max(self._client.settings.pdf_max_zoomed_dimension, 1800), 2200),
        )
        if crop_path not in seen_paths:
            prepared.append((f"Focused crop from page {primary_page.page_number} for question {question_id}.", crop_path))
            seen_paths.add(crop_path)
        if zoom_path not in seen_paths:
            prepared.append((f"Zoomed crop from page {primary_page.page_number} for question {question_id}.", zoom_path))
        return prepared[:4]

    @staticmethod
    def _prompt() -> str:
        return dedent(
            """
            You are performing a focused verification on one potentially under-credited handwritten answer with quantitative or symbolic work.

            Check only the provided question, rubric, visible evidence summary, and attached images.
            Do not regrade the entire exam.
            Decide the final user-facing score and explanation for this question by checking for ambiguous handwriting, digit misread, equivalent math, or contradictions between evidence and the current scoring fields.

            Rules:
            - Read handwritten digits cautiously.
            - If a leading digit or numerator digit is faint, treat that as ambiguity rather than certain error when the method, comparison, and conclusion support the intended value.
            - Accept mathematically equivalent fractions, decimals, and rearranged inequalities.
            - Do not heavily penalize a response based only on one uncertain digit, notation issue, or unit issue if the method and conclusion are otherwise correct.
            - Preserve notation carefully. Do not merge or swap similar-looking variable names, subscripts, superscripts, cases, or symbols.
            - Use the provided marks only as a floor. Do not return fewer marks than are already awarded.
            - Write the response as the final grader judgment for the student. Do not mention verification, rechecking, previous scores, earlier grading, adjustment, restoration of credit, or internal review.

            Return updated grading fields for this one question only. Keep the response concise and evidence-based. Return strict JSON matching the schema.
            """
        )
