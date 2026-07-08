from __future__ import annotations

import base64
from collections.abc import Iterator
from mimetypes import guess_type
from pathlib import Path
from textwrap import dedent
from typing import TypeVar

from PIL import Image, ImageDraw, ImageFont

from grading_engine.azure_client import AzureGraderClient
from grading_engine.cost_logger import ModelCallTrace
from grading_engine.pdf_preprocessor import PDFPreprocessor, ProcessedDocument
from grading_engine.schemas import (
    AnswerLocation,
    Evidence,
    ExamQuestion,
    LocationBatchResult,
    StudentAnswer,
    StudentInspectionResult,
)
from grading_engine.trace_logger import append_run_trace


ItemT = TypeVar("ItemT")


def _chunks(items: list[ItemT], size: int) -> Iterator[list[ItemT]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _image_to_data_url(path: Path) -> str:
    mime_type, _ = guess_type(str(path))
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _region_to_bbox(width: int, height: int, region_hint: str) -> list[int]:
    if region_hint == "top":
        return [0, 0, width, height // 2]
    if region_hint == "middle":
        third = height // 3
        return [0, third, width, third * 2]
    if region_hint == "bottom":
        return [0, height // 2, width, height]
    return [0, 0, width, height]


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


class StudentInspectionAgent:
    def __init__(
        self,
        client: AzureGraderClient,
        *,
        artifacts_root: Path,
        question_batch_size: int,
    ) -> None:
        self._client = client
        self._artifacts_root = artifacts_root
        self._question_batch_size = question_batch_size

    async def run(
        self,
        *,
        run_id: str,
        student_document: ProcessedDocument,
        exam_questions: list[ExamQuestion],
    ) -> tuple[StudentInspectionResult, list[ModelCallTrace]]:
        sheet_paths = self._build_contact_sheets(run_id, student_document)
        locations, location_traces = await self._locate_answers(
            run_id=run_id,
            student_document=student_document,
            contact_sheet_paths=sheet_paths,
            exam_questions=exam_questions,
        )
        answers, transcription_traces = await self._transcribe_answers(
            run_id=run_id,
            student_document=student_document,
            exam_questions=exam_questions,
            locations=locations,
        )
        answers, refinement_traces = await self._refine_final_answers(
            run_id=run_id,
            student_document=student_document,
            exam_questions=exam_questions,
            answers=answers,
        )
        return StudentInspectionResult(answers=answers), location_traces + transcription_traces + refinement_traces

    def _build_contact_sheets(self, run_id: str, document: ProcessedDocument) -> list[Path]:
        output_dir = self._artifacts_root / run_id / "inspection"
        output_dir.mkdir(parents=True, exist_ok=True)
        font = ImageFont.load_default()
        sheet_paths: list[Path] = []
        pages = list(document.pages)
        for sheet_index, page_batch in enumerate(_chunks(pages, 2), start=1):
            images = [Image.open(page.thumbnail_path).convert("RGB") for page in page_batch]
            width = max(image.width for image in images)
            height = sum(image.height for image in images) + (60 * len(images))
            sheet = Image.new("RGB", (width, height), color="white")
            draw = ImageDraw.Draw(sheet)
            cursor_y = 0
            for page, image in zip(page_batch, images):
                draw.rectangle((0, cursor_y, width, cursor_y + 32), fill="#EAF2F8")
                draw.text((12, cursor_y + 8), f"Student page {page.page_number}", fill="black", font=font)
                cursor_y += 40
                sheet.paste(image, (0, cursor_y))
                cursor_y += image.height + 20
            path = output_dir / f"sheet_{sheet_index}.png"
            sheet.save(path)
            sheet_paths.append(path)
        return sheet_paths

    def _relevant_page_numbers(
        self,
        *,
        location: AnswerLocation | None,
        page_count: int,
    ) -> list[int]:
        if location is None:
            return []
        ordered_pages: list[int] = []
        for page_number in [location.page_number, *location.page_numbers]:
            if page_number is None:
                continue
            bounded = min(max(page_number, 1), page_count)
            if bounded not in ordered_pages:
                ordered_pages.append(bounded)
        max_pages = max(1, min(3, self._client.settings.max_images_per_request))
        return ordered_pages[:max_pages]

    @staticmethod
    def _fallback_answer(
        *,
        question_id: str,
        status: str,
        transcription: str,
        evidence: Evidence | None,
        source_pages: list[int],
        confidence: float | None,
        needs_human_review: bool,
    ) -> StudentAnswer:
        return StudentAnswer(
            question_id=question_id,
            status=status,
            transcription=transcription,
            final_answer=None,
            derivation_summary=None,
            uncertain_parts=[],
            student_claims=[],
            source_pages=list(source_pages),
            evidence=evidence,
            confidence=confidence,
            needs_human_review=needs_human_review,
        )

    async def _locate_answers(
        self,
        *,
        run_id: str,
        student_document: ProcessedDocument,
        contact_sheet_paths: list[Path],
        exam_questions: list[ExamQuestion],
    ) -> tuple[list[AnswerLocation], list[ModelCallTrace]]:
        traces: list[ModelCallTrace] = []
        locations: list[AnswerLocation] = []
        prompt = dedent(
            """
            You are a student-answer inspection agent for handwritten exam submissions.

            For each question:
            - Inspect every provided student page summary and every contact-sheet image before deciding.
            - Return `status="answered"` if any relevant formula, calculation, text, diagram annotation, or final answer is visible anywhere.
            - Return `status="unclear"` when relevant work is probably present but the exact page, extent, or readability is uncertain.
            - Return `status="missing"` only when no relevant marks, formulas, text, calculations, or annotations are visible on any page.
            - Set `page_number` to the single best page for the answer.
            - Set `page_numbers` to every relevant page in reading order, including continuation pages, up to 3 pages.
            - Choose `region_hint` for the best page only: `top`, `middle`, `bottom`, `full_page`, or `unknown`.
            - Keep `summary` concise and evidence-based, mentioning if the answer appears to continue on another page.

            Do not grade the answer. Return only compact JSON matching the schema.
            """
        )
        for batch in _chunks(exam_questions, self._question_batch_size):
            content: list[dict] = [
                {
                    "type": "text",
                    "text": PDFPreprocessor.to_json(
                        {
                            "questions": [
                                {
                                    "question_id": question.question_id,
                                    "question_text": question.question_text[:1200],
                                }
                                for question in batch
                            ]
                        }
                    ),
                }
            ]
            content.append(
                {
                    "type": "text",
                    "text": PDFPreprocessor.to_json(
                        {
                            "page_summaries": [
                                {
                                    "page_number": page.page_number,
                                    "page_type": page.page_type,
                                    "text_excerpt": page.text[:600],
                                }
                                for page in student_document.pages if page.text
                            ]
                        }
                    ),
                }
            )
            for sheet_path in contact_sheet_paths:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_to_data_url(sheet_path), "detail": "high"},
                    }
                )
            completion = await self._client.complete_structured(
                stage="student_location",
                run_id=run_id,
                system_prompt=prompt,
                user_content=content,
                response_model=LocationBatchResult,
            )
            append_run_trace(
                self._client.settings,
                run_id,
                "student_location.batch_completed",
                question_ids=[question.question_id for question in batch],
                sheet_count=len(contact_sheet_paths),
                located_count=len(completion.parsed.locations),
            )
            traces.append(completion.trace)
            locations.extend(completion.parsed.locations)
        return locations, traces

    async def _transcribe_answers(
        self,
        *,
        run_id: str,
        student_document: ProcessedDocument,
        exam_questions: list[ExamQuestion],
        locations: list[AnswerLocation],
    ) -> tuple[list[StudentAnswer], list[ModelCallTrace]]:
        location_lookup = {location.question_id: location for location in locations}
        traces: list[ModelCallTrace] = []
        answers_by_question_id: dict[str, StudentAnswer] = {}
        prompt = dedent(
            """
            You are a handwriting transcription and interpretation agent for handwritten exam answers.

            For each question:
            - Inspect every supplied page image and text excerpt before writing the result.
            - Treat OCR/text excerpts as hints only. If OCR is uncertain, rely on the page image rather than assuming the work is absent.
            - Transcribe the student's visible work faithfully, preserving uncertainty instead of guessing.
            - Preserve variable names, cases, subscripts, superscripts, operators, and symbols exactly as written whenever possible. Do not merge similar-looking notation into a different symbol.
            - Extract the clearest final answer or final formula when present.
            - Final answers are especially important. Before leaving `final_answer` empty, re-scan the supplied pages for end-of-solution lines, comparison statements, boxed or underlined expressions, terminal equations, and conclusion sentences.
            - If the student gives the final answer in an equivalent numerical or algebraic form, capture that student form in `final_answer` instead of discarding it for not matching another representation.
            - Summarize the supporting derivation or calculations briefly.
            - Record concise `student_claims` for visible evidence such as final answers, formulas, inequalities, numerical values, conclusion sentences, derivation steps, or diagram annotations.
            - For `student_claims`, prefer concise evidence wording such as "appears to write", "likely intended as", or "value is partially unclear but consistent with" when handwriting is ambiguous.
            - If a handwritten number, fraction, or decimal is ambiguous, do not force a single worst-case reading. Note the ambiguity in `uncertain_parts`, and if the surrounding work supports a likely intended value, say that with uncertainty-aware wording.
            - Be especially careful with faint leading digits, superscripts, fraction bars, and inequality signs. A faint leading digit may still be part of the intended value.
            - If the final number, comparison, and written conclusion seem mutually consistent but one digit is unclear, preserve that consistency in the summary instead of treating the number as certainly wrong.
            - If a likely final answer is visible but one symbol or digit is hard to read, still extract the best-supported final answer candidate and describe the uncertainty separately in `uncertain_parts`.
            - Set `source_pages` to every supplied page that contains relevant work.
            - Use `status="unclear"` when work is visible but not fully readable.
            - Use `status="missing"` only when no relevant work is visible on any supplied page.

            Do not grade or compare against the official solution. Do not restate the full question. Return only compact JSON matching the schema.
            """
        )

        pending_questions: list[ExamQuestion] = []
        content: list[dict] = []
        evidence_lookup: dict[str, Evidence] = {}
        source_pages_lookup: dict[str, list[int]] = {}
        pending_image_count = 0

        async def flush_batch() -> None:
            nonlocal content, pending_questions, evidence_lookup, source_pages_lookup, pending_image_count
            if not pending_questions:
                return
            completion = await self._client.complete_structured(
                stage="student_transcription",
                run_id=run_id,
                system_prompt=prompt,
                user_content=content,
                response_model=StudentInspectionResult,
            )
            append_run_trace(
                self._client.settings,
                run_id,
                "student_transcription.batch_completed",
                question_ids=[question.question_id for question in pending_questions],
                item_count=len(content),
            )
            traces.append(completion.trace)
            parsed_by_question = {answer.question_id: answer for answer in completion.parsed.answers}
            for question in pending_questions:
                parsed = parsed_by_question.get(question.question_id)
                source_pages = source_pages_lookup[question.question_id]
                fallback_evidence = evidence_lookup[question.question_id]
                if parsed is None:
                    answers_by_question_id[question.question_id] = self._fallback_answer(
                        question_id=question.question_id,
                        status="unclear",
                        transcription="The transcription call did not return an answer for this question.",
                        evidence=fallback_evidence,
                        source_pages=source_pages,
                        confidence=0.0,
                        needs_human_review=True,
                    )
                else:
                    parsed.evidence = fallback_evidence
                    if not parsed.source_pages:
                        parsed.source_pages = list(source_pages)
                    if parsed.status == "missing" and source_pages:
                        parsed.status = "unclear"
                        parsed.needs_human_review = True
                        if not parsed.transcription.strip():
                            parsed.transcription = (
                                "Visible work may be present on the supplied pages, but it could not be "
                                "transcribed confidently."
                            )
                    answers_by_question_id[question.question_id] = parsed
            content = []
            pending_questions = []
            evidence_lookup = {}
            source_pages_lookup = {}
            pending_image_count = 0

        for question in exam_questions:
            location = location_lookup.get(question.question_id)
            relevant_page_numbers = self._relevant_page_numbers(location=location, page_count=student_document.page_count)
            if location is None or (location.status == "missing" and not relevant_page_numbers):
                answers_by_question_id[question.question_id] = self._fallback_answer(
                    question_id=question.question_id,
                    status="missing",
                    transcription="No student answer was confidently located for this question.",
                    evidence=None,
                    source_pages=[],
                    confidence=location.confidence if location else 0.0,
                    needs_human_review=location.needs_human_review if location else False,
                )
                continue

            if not relevant_page_numbers:
                answers_by_question_id[question.question_id] = self._fallback_answer(
                    question_id=question.question_id,
                    status="unclear",
                    transcription="Possible student work was detected, but the relevant page could not be isolated confidently.",
                    evidence=None,
                    source_pages=[],
                    confidence=location.confidence if location else 0.0,
                    needs_human_review=True,
                )
                continue

            relevant_pages = [student_document.pages[page_number - 1] for page_number in relevant_page_numbers]
            primary_page = relevant_pages[0]
            bbox = _region_to_bbox(primary_page.width, primary_page.height, location.region_hint)
            evidence = Evidence(
                page=primary_page.page_number,
                bbox=bbox,
                crop_path=None,
                zoomed=False,
            )
            if pending_questions and (
                len(pending_questions) >= self._question_batch_size
                or pending_image_count + len(relevant_pages) > self._client.settings.max_images_per_request
            ):
                await flush_batch()
            transcription_payload = {
                "question_id": question.question_id,
                "question_text": question.question_text[:1600],
                "location_summary": location.summary,
                "pages": [
                    {
                        "page_number": page.page_number,
                        "page_type": page.page_type,
                        "region_hint": location.region_hint if page.page_number == primary_page.page_number else "continuation",
                        "text_excerpt": page.text[:2400] if page.text else "",
                    }
                    for page in relevant_pages
                ],
            }
            content.append({"type": "text", "text": PDFPreprocessor.to_json(transcription_payload)})
            for page in relevant_pages:
                content.append(
                    {
                        "type": "text",
                        "text": (
                            f"Question {question.question_id}: attached student page image {page.page_number}. "
                            "Inspect this image before deciding whether any work is present."
                        ),
                    }
                )
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_to_data_url(page.image_path), "detail": "high"},
                    }
                )
            append_run_trace(
                self._client.settings,
                run_id,
                "student_transcription.question_prepared",
                question_id=question.question_id,
                page_numbers=relevant_page_numbers,
                page_types=[page.page_type for page in relevant_pages],
                used_image=bool(relevant_pages),
                bbox=bbox,
            )
            pending_questions.append(question)
            evidence_lookup[question.question_id] = evidence
            source_pages_lookup[question.question_id] = relevant_page_numbers
            pending_image_count += len(relevant_pages)

        await flush_batch()
        return [
            answers_by_question_id.get(
                question.question_id,
                self._fallback_answer(
                    question_id=question.question_id,
                    status="missing",
                    transcription="No answer was returned for this question.",
                    evidence=None,
                    source_pages=[],
                    confidence=0.0,
                    needs_human_review=False,
                ),
            )
            for question in exam_questions
        ], traces

    @staticmethod
    def _dedupe_strings(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            text = " ".join(item.split()).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped

    @staticmethod
    def _dedupe_pages(pages: list[int]) -> list[int]:
        ordered: list[int] = []
        for page in pages:
            if page not in ordered:
                ordered.append(page)
        return ordered

    def _needs_final_answer_refinement(self, answer: StudentAnswer) -> bool:
        if answer.status not in {"answered", "unclear"} or not answer.source_pages:
            return False
        claim_types = {claim.type.lower() for claim in answer.student_claims}
        combined_text = " ".join(
            part
            for part in (
                answer.transcription,
                answer.final_answer or "",
                answer.derivation_summary or "",
                " ".join(claim.content for claim in answer.student_claims),
                " ".join(answer.uncertain_parts),
            )
            if part
        )
        has_final_signal = bool(
            claim_types.intersection(
                {"final_answer", "conclusion", "comparison", "numerical_value", "formula", "inequality"}
            )
        ) or _contains_any(
            combined_text,
            (
                "final answer",
                "therefore",
                "hence",
                "concludes",
                "result",
                "better",
                "greater",
                "less",
                "=",
                ">",
                "<",
                "/",
            ),
        )
        if not has_final_signal:
            return False
        if not answer.final_answer:
            return True
        if answer.uncertain_parts:
            return True
        return (answer.confidence or 0.0) < 0.7

    def _merge_refined_answer(self, *, current: StudentAnswer, refined: StudentAnswer) -> StudentAnswer:
        merged = current.model_copy(deep=True)
        if refined.status == "answered" or (current.status == "missing" and refined.status in {"answered", "unclear"}):
            merged.status = refined.status
        if refined.final_answer:
            merged.final_answer = refined.final_answer
        if refined.derivation_summary and (
            not merged.derivation_summary
            or (not current.final_answer and len(refined.derivation_summary) > len(merged.derivation_summary))
        ):
            merged.derivation_summary = refined.derivation_summary
        if refined.transcription and (
            not merged.transcription
            or (not current.final_answer and len(refined.transcription) > len(merged.transcription))
        ):
            merged.transcription = refined.transcription
        merged.uncertain_parts = self._dedupe_strings([*merged.uncertain_parts, *refined.uncertain_parts])
        if refined.source_pages:
            merged.source_pages = self._dedupe_pages([*merged.source_pages, *refined.source_pages])
        if refined.student_claims:
            seen_claims = {
                (claim.type, claim.content, claim.evidence_page)
                for claim in merged.student_claims
            }
            for claim in refined.student_claims:
                key = (claim.type, claim.content, claim.evidence_page)
                if key not in seen_claims:
                    merged.student_claims.append(claim)
                    seen_claims.add(key)
        if refined.confidence is not None:
            merged.confidence = (
                refined.confidence
                if merged.confidence is None
                else max(merged.confidence, refined.confidence)
            )
        merged.needs_human_review = merged.needs_human_review or refined.needs_human_review
        merged.evidence = current.evidence
        return merged

    async def _refine_final_answers(
        self,
        *,
        run_id: str,
        student_document: ProcessedDocument,
        exam_questions: list[ExamQuestion],
        answers: list[StudentAnswer],
    ) -> tuple[list[StudentAnswer], list[ModelCallTrace]]:
        answer_lookup = {answer.question_id: answer for answer in answers}
        traces: list[ModelCallTrace] = []
        prompt = dedent(
            """
            You are refining the extraction of final answers from handwritten student work.

            Focus only on the final answer, final formula, final condition, comparison, or conclusion for the supplied question.
            Inspect the attached student page images carefully before deciding.

            Rules:
            - Do not grade the work.
            - Re-scan the ending of the solution, conclusion sentences, terminal equations, boxed or underlined expressions, and comparison lines before leaving `final_answer` empty.
            - If the final answer is written in an equivalent numerical or algebraic form, extract the student's form exactly.
            - If one digit, sign, exponent, or symbol is partially unclear, preserve the best-supported final answer candidate and describe the uncertainty in `uncertain_parts`.
            - Preserve notation carefully. Do not merge or swap similar-looking variable names, cases, subscripts, superscripts, or symbols.
            - If the surrounding work and final conclusion support a likely intended final answer, prefer a careful best-supported extraction over dropping the final answer entirely.
            - Use uncertainty-aware wording in `student_claims` and `transcription`, but keep `final_answer` itself to the best-supported answer text when possible.

            Return only compact JSON matching the schema.
            """
        )
        candidates = [
            question
            for question in exam_questions
            if question.question_id in answer_lookup
            and self._needs_final_answer_refinement(answer_lookup[question.question_id])
        ][:2]
        for question in candidates:
            current = answer_lookup[question.question_id]
            relevant_pages = [
                student_document.pages[page_number - 1]
                for page_number in current.source_pages
                if 1 <= page_number <= student_document.page_count
            ][: min(2, self._client.settings.max_images_per_request)]
            if not relevant_pages:
                continue
            content: list[dict] = [
                {
                    "type": "text",
                    "text": PDFPreprocessor.to_json(
                        {
                            "questions": [
                                {
                                    "question_id": question.question_id,
                                    "question_text": question.question_text[:1600],
                                    "current_extraction": current.model_dump(mode="json"),
                                }
                            ]
                        }
                    ),
                }
            ]
            for page in relevant_pages:
                content.append(
                    {
                        "type": "text",
                        "text": (
                            f"Question {question.question_id}: attached student page image {page.page_number}. "
                            "Inspect this image carefully to refine the final answer extraction."
                        ),
                    }
                )
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_to_data_url(page.image_path), "detail": "high"},
                    }
                )
            append_run_trace(
                self._client.settings,
                run_id,
                "student_final_answer_refinement.question_prepared",
                question_id=question.question_id,
                page_numbers=[page.page_number for page in relevant_pages],
            )
            completion = await self._client.complete_structured(
                stage="student_final_answer_refinement",
                run_id=run_id,
                system_prompt=prompt,
                user_content=content,
                response_model=StudentInspectionResult,
                timeout_seconds=min(110.0, self._client.settings.llm_timeout_seconds),
            )
            traces.append(completion.trace)
            parsed = next(
                (item for item in completion.parsed.answers if item.question_id == question.question_id),
                None,
            )
            if parsed is None:
                continue
            parsed.evidence = current.evidence
            if not parsed.source_pages:
                parsed.source_pages = list(current.source_pages)
            answer_lookup[question.question_id] = self._merge_refined_answer(
                current=current,
                refined=parsed,
            )
        return [answer_lookup[question.question_id] for question in exam_questions], traces
