from __future__ import annotations

import re

from grading_engine.schemas import (
    CriterionScore,
    Evidence,
    EvidenceSummary,
    ExamQuestion,
    GradingDraft,
    GradingResult,
    QuestionGradeResult,
    RubricQuestion,
    StudentAnswer,
    VisibleEvidenceItem,
)


class GradingValidator:
    _INTERNAL_LANGUAGE_PATTERNS = (
        (
            re.compile(
                r"(?i)\b(?:the\s+)?(?:existing|previous|original|old|earlier)\s+score\s+(?:is|was)\s+(?:not\s+)?too harsh because\s*"
            ),
            "",
        ),
        (
            re.compile(
                r"(?i)\b(?:the\s+)?(?:existing|previous|original|old|earlier)\s+score\s+(?:is|was)\s+(?:not\s+)?too harsh\b[.:;,\s-]*"
            ),
            "",
        ),
        (re.compile(r"(?i)\b(?:recheck|repair)\b[.:;,\s-]*"), ""),
        (re.compile(r"(?i)\b(?:existing|previous|old|earlier)\s+scores?\b[.:;,\s-]*"), ""),
        (re.compile(r"(?i)\b(?:earlier|previous|old)\s+grading\b[.:;,\s-]*"), ""),
        (re.compile(r"(?i)\bmodel initially\b[.:;,\s-]*"), ""),
        (re.compile(r"(?i)\bprevious model\b[.:;,\s-]*"), ""),
        (re.compile(r"(?i)\binternal validation\b[.:;,\s-]*"), ""),
        (re.compile(r"(?i)\badjusted from\b[^.]*[.]?"), ""),
        (re.compile(r"(?i)\brestored credit for\b[.:;,\s-]*"), ""),
        (re.compile(r"(?i)\brestored credit\b[.:;,\s-]*"), ""),
        (re.compile(r"(?i)\bworst-?case digit reading\b[.:;,\s-]*"), ""),
        (re.compile(r"(?i)\bmarks?\s+withheld\s+for\s+verification\b[.:;,\s-]*"), ""),
        (re.compile(r"(?i)\bwithheld\s+for\s+verification\b[.:;,\s-]*"), ""),
    )

    def run(
        self,
        *,
        grading_id: str,
        model_deployment: str,
        duration_ms: int,
        exam_questions: list[ExamQuestion],
        rubric_questions: list[RubricQuestion],
        student_answers: list[StudentAnswer],
        grading_draft: GradingDraft,
    ) -> GradingResult:
        rubric_lookup = {question.question_id: question for question in rubric_questions}
        answer_lookup = {answer.question_id: answer for answer in student_answers}
        draft_lookup = {question.question_id: question for question in grading_draft.questions}
        final_questions: list[QuestionGradeResult] = []

        for exam_question in exam_questions:
            rubric = rubric_lookup[exam_question.question_id]
            answer = answer_lookup.get(exam_question.question_id)
            draft = draft_lookup.get(exam_question.question_id)
            if draft is None:
                final_questions.append(self._missing_result(exam_question.question_id, rubric, answer))
                continue
            final_questions.append(
                self._normalize_question_result(
                    exam_question=exam_question,
                    rubric=rubric,
                    answer=answer,
                    draft=draft,
                )
            )

        total_score = round(sum(item.awarded_marks for item in final_questions), 2)
        max_score = round(sum(item.max_marks for item in final_questions), 2)
        return GradingResult(
            grading_id=grading_id,
            status="completed",
            model_deployment=model_deployment,
            total_score=total_score,
            max_score=max_score,
            duration_ms=duration_ms,
            questions=final_questions,
        )

    def normalize_existing_result(
        self,
        *,
        result: GradingResult,
        exam_questions: list[ExamQuestion],
        rubric_questions: list[RubricQuestion],
        student_answers: list[StudentAnswer],
    ) -> GradingResult:
        rubric_lookup = {question.question_id: question for question in rubric_questions}
        answer_lookup = {answer.question_id: answer for answer in student_answers}
        draft_lookup = {question.question_id: question for question in result.questions}
        normalized_questions: list[QuestionGradeResult] = []

        for exam_question in exam_questions:
            rubric = rubric_lookup[exam_question.question_id]
            answer = answer_lookup.get(exam_question.question_id)
            draft = draft_lookup.get(exam_question.question_id)
            if draft is None:
                normalized_questions.append(self._missing_result(exam_question.question_id, rubric, answer))
                continue
            normalized_questions.append(
                self._normalize_question_result(
                    exam_question=exam_question,
                    rubric=rubric,
                    answer=answer,
                    draft=draft,
                )
            )

        return GradingResult(
            grading_id=result.grading_id,
            status=result.status,
            model_deployment=result.model_deployment,
            total_score=round(sum(question.awarded_marks for question in normalized_questions), 2),
            max_score=round(sum(question.max_marks for question in normalized_questions), 2),
            duration_ms=result.duration_ms,
            questions=normalized_questions,
        )

    def _normalize_question_result(
        self,
        *,
        exam_question: ExamQuestion,
        rubric: RubricQuestion,
        answer: StudentAnswer | None,
        draft: QuestionGradeResult,
    ) -> QuestionGradeResult:
        criterion_scores = [
            self._normalize_criterion_score(score, answer.evidence if answer else None)
            for score in draft.criterion_scores
        ]
        criterion_total = round(sum(item.awarded for item in criterion_scores), 2)
        awarded_marks = round(min(max(0.0, max(draft.awarded_marks, criterion_total)), rubric.max_marks), 2)
        suspicious_low_score = self._should_soften_low_score(
            question=exam_question,
            rubric=rubric,
            answer=answer,
            criterion_scores=criterion_scores,
            awarded_marks=awarded_marks,
            max_marks=rubric.max_marks,
        )
        correct_elements = self._finalize_correct_elements(
            draft=draft,
            rubric=rubric,
            criterion_scores=criterion_scores,
            answer=answer,
        )
        missing_elements = self._finalize_missing_elements(
            draft=draft,
            rubric=rubric,
            criterion_scores=criterion_scores,
            answer=answer,
        )
        improvement_suggestions = self._finalize_improvement_suggestions(
            draft=draft,
            rubric=rubric,
            criterion_scores=criterion_scores,
            answer=answer,
            awarded_marks=awarded_marks,
            max_marks=rubric.max_marks,
        )
        visible_evidence = self._finalize_visible_evidence(
            draft=draft,
            answer=answer,
            criterion_scores=criterion_scores,
        )
        evidence_summaries = self._finalize_evidence_summaries(
            draft=draft,
            answer=answer,
            criterion_scores=criterion_scores,
            visible_evidence=visible_evidence,
        )
        correct_elements = self._harmonize_correct_elements(
            correct_elements=correct_elements,
            missing_elements=missing_elements,
            awarded_marks=awarded_marks,
            max_marks=rubric.max_marks,
        )
        missing_elements = self._harmonize_missing_elements(
            missing_elements=missing_elements,
            correct_elements=correct_elements,
            visible_evidence=visible_evidence,
            answer=answer,
            awarded_marks=awarded_marks,
            max_marks=rubric.max_marks,
        )
        improvement_suggestions = self._harmonize_improvement_suggestions(
            suggestions=improvement_suggestions,
            missing_elements=missing_elements,
            awarded_marks=awarded_marks,
            max_marks=rubric.max_marks,
        )
        evidence_summaries = self._harmonize_evidence_summaries(
            evidence_summaries=evidence_summaries,
            visible_evidence=visible_evidence,
        )
        rationale = self._finalize_score_rationale(
            draft=draft,
            question=exam_question,
            rubric=rubric,
            answer=answer,
            awarded_marks=awarded_marks,
            missing_elements=missing_elements,
            correct_elements=correct_elements,
            visible_evidence=visible_evidence,
            evidence_summaries=evidence_summaries,
            criterion_scores=criterion_scores,
        )
        needs_human_review = (
            draft.needs_human_review
            or any(item.needs_human_review for item in criterion_scores)
            or suspicious_low_score
            or self._needs_low_score_review(
                question=exam_question,
                rubric=rubric,
                answer=answer,
                criterion_scores=criterion_scores,
                awarded_marks=awarded_marks,
                max_marks=rubric.max_marks,
                correct_elements=correct_elements,
                missing_elements=missing_elements,
                visible_evidence=visible_evidence,
            )
        )
        return QuestionGradeResult(
            question_id=exam_question.question_id,
            awarded_marks=awarded_marks,
            max_marks=rubric.max_marks,
            rubric_source=rubric.rubric_source,
            max_marks_source=rubric.max_marks_source,
            feedback=rationale,
            score_rationale=rationale,
            correct_elements=correct_elements,
            missing_or_incorrect_elements=missing_elements,
            improvement_suggestions=improvement_suggestions,
            evidence_summaries=evidence_summaries,
            visible_evidence=visible_evidence,
            confidence=draft.confidence,
            needs_human_review=needs_human_review,
            criterion_scores=criterion_scores,
        )

    def _missing_result(
        self,
        question_id: str,
        rubric: RubricQuestion,
        answer: StudentAnswer | None,
    ) -> QuestionGradeResult:
        needs_review = bool(answer and (answer.status == "unclear" or self._has_substantive_visible_work(answer)))
        evidence = answer.evidence if answer else None
        visible_evidence = self._fallback_visible_evidence(answer)
        evidence_summaries = self._fallback_evidence_summaries(answer, visible_evidence=visible_evidence)
        feedback = (
            "No answer was located for this question, so no marks could be awarded."
            if not needs_review
            else "Visible work may be present, but it could not be verified confidently enough for automatic credit. This question should be checked by a human reviewer."
        )
        return QuestionGradeResult(
            question_id=question_id,
            awarded_marks=0.0,
            max_marks=rubric.max_marks,
            rubric_source=rubric.rubric_source,
            max_marks_source=rubric.max_marks_source,
            feedback=feedback,
            score_rationale=feedback,
            correct_elements=[],
            missing_or_incorrect_elements=[
                "No usable answer evidence was available for this question."
                if not needs_review
                else "Visible work was too unclear or incomplete to confirm the required steps or final answer automatically."
            ],
            improvement_suggestions=[
                "Provide a clearly readable final answer and the key supporting steps for each rubric criterion."
            ],
            evidence_summaries=evidence_summaries,
            visible_evidence=visible_evidence,
            confidence=0.0,
            needs_human_review=needs_review,
            criterion_scores=[
                CriterionScore(
                    criterion_id=criterion.criterion_id,
                    awarded=0.0,
                    max=criterion.marks,
                    match_type="missing",
                    verification_status="partial",
                    feedback="No usable evidence was available for this criterion.",
                    confidence=0.0,
                    needs_human_review=needs_review,
                    evidence=evidence,
                )
                for criterion in rubric.criteria
            ],
        )

    def _normalize_criterion_score(
        self,
        score: CriterionScore,
        fallback_evidence: Evidence | None,
    ) -> CriterionScore:
        awarded = round(min(max(0.0, score.awarded), score.max), 2)
        evidence = score.evidence or fallback_evidence
        return CriterionScore(
            criterion_id=score.criterion_id,
            awarded=awarded,
            max=round(score.max, 2),
            match_type=score.match_type,
            verification_status=score.verification_status,
            feedback=score.feedback,
            confidence=score.confidence,
            needs_human_review=score.needs_human_review or (awarded > 0 and evidence is None),
            evidence=evidence,
        )

    @staticmethod
    def _strip_internal_process_language(text: str) -> str:
        cleaned = text
        cleaned = re.sub(
            r"(?i)\blimited the (?:earlier|previous|old)\s+(?:grading|score)\b",
            "limited the awarded credit",
            cleaned,
        )
        cleaned = re.sub(
            r"(?i)\bafter (?:recheck|repair)\b",
            "",
            cleaned,
        )
        for pattern, replacement in GradingValidator._INTERNAL_LANGUAGE_PATTERNS:
            cleaned = pattern.sub(replacement, cleaned)
        cleaned = re.sub(r"(?i)^\s*(because|since)\s+", "", cleaned)
        cleaned = re.sub(r"^[\s:;,-]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _clean_items(items: list[str], *, limit: int) -> list[str]:
        cleaned: list[str] = []
        for item in items:
            text = GradingValidator._strip_internal_process_language(" ".join(item.split()).strip())
            if text and text not in cleaned:
                cleaned.append(text[:220])
            if len(cleaned) >= limit:
                break
        return cleaned

    @staticmethod
    def _clean_text(text: str, *, limit: int) -> str:
        return GradingValidator._strip_internal_process_language(" ".join(text.split()).strip())[:limit]

    @staticmethod
    def _strip_terminal_punctuation(text: str) -> str:
        return text.strip().rstrip(" .;:,")

    @staticmethod
    def _ensure_terminal_period(text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""
        if cleaned[-1] in ".!?":
            return cleaned
        return f"{cleaned}."

    @staticmethod
    def _lowercase_first(text: str) -> str:
        if not text:
            return text
        return text[0].lower() + text[1:]

    @staticmethod
    def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
        normalized = text.lower()
        return any(needle in normalized for needle in needles)

    @staticmethod
    def _normalize_phrase(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    @staticmethod
    def _contains_absence_language(text: str) -> bool:
        return GradingValidator._contains_any(
            text,
            (
                "no answer",
                "blank",
                "nothing written",
                "not present",
                "not visible",
                "missing entirely",
                "no calculation",
                "no final answer",
                "no conclusion",
            ),
        )

    @staticmethod
    def _has_math_signal(text: str) -> bool:
        return any(signal in text for signal in ("=", "/", "∫", ">", "<", "+", "-", "*"))

    def _evidence_shows_category(
        self,
        *,
        category: str,
        visible_evidence: list[VisibleEvidenceItem],
        correct_elements: list[str],
        answer: StudentAnswer | None,
    ) -> bool:
        haystacks = [item.evidence for item in visible_evidence] + list(correct_elements)
        if answer is not None:
            haystacks.extend(
                part
                for part in (
                    answer.final_answer or "",
                    answer.derivation_summary or "",
                    answer.transcription or "",
                    " ".join(claim.content for claim in answer.student_claims),
                )
                if part
            )
        if category == "final_answer":
            return any(
                self._contains_any(text, ("final answer", "therefore", "hence", "concludes", "result", "better"))
                or self._has_math_signal(text)
                for text in haystacks
            )
        if category == "calculation":
            return any(
                self._contains_any(text, ("integral", "formula", "derivation", "calculate", "setup", "substitute"))
                or self._has_math_signal(text)
                for text in haystacks
            )
        if category == "conclusion":
            return any(
                self._contains_any(text, ("therefore", "hence", "concludes", "better", "preferred", "choose"))
                for text in haystacks
            )
        return False

    @staticmethod
    def _has_serious_issue_language(text: str) -> bool:
        return any(
            phrase in text.lower()
            for phrase in (
                "missing",
                "incorrect",
                "wrong",
                "not correct",
                "does not meet",
                "conceptual",
                "major",
                "unsupported",
                "absent",
            )
        )

    @staticmethod
    def _has_minor_issue_language(text: str) -> bool:
        return any(
            phrase in text.lower()
            for phrase in (
                "minor",
                "slightly",
                "notation",
                "format",
                "clarity",
                "presentation",
                "unit",
                "brief",
            )
        )

    @staticmethod
    def _is_generic_feedback(text: str) -> bool:
        return any(
            phrase in text.lower()
            for phrase in (
                "does not fully meet every rubric requirement",
                "partially correct",
                "unclear transcription elements remain",
                "some rubric requirements could not be confirmed",
            )
        )

    @staticmethod
    def _is_full_score(*, awarded_marks: float, max_marks: float) -> bool:
        return max_marks > 0 and awarded_marks >= max_marks

    @staticmethod
    def _is_near_full_score(*, awarded_marks: float, max_marks: float) -> bool:
        return max_marks > 0 and awarded_marks < max_marks and awarded_marks >= round(max_marks * 0.85, 2)

    @staticmethod
    def _is_low_score(*, awarded_marks: float, max_marks: float) -> bool:
        return max_marks > 0 and awarded_marks < round(max_marks * 0.75, 2)

    @staticmethod
    def _format_mark_amount(amount: float) -> str:
        rounded = round(amount, 2)
        if rounded.is_integer():
            value = str(int(rounded))
        else:
            value = f"{rounded:.2f}".rstrip("0").rstrip(".")
        return f"{value} mark" if rounded == 1 else f"{value} marks"

    def _append_unique_item(self, items: list[str], candidate: str, *, limit: int) -> None:
        cleaned = self._ensure_terminal_period(self._clean_text(candidate, limit=220))
        if not cleaned:
            return
        normalized = self._normalize_phrase(cleaned)
        if any(self._normalize_phrase(existing) == normalized for existing in items):
            return
        if len(items) < limit:
            items.append(cleaned)

    def _criterion_feedback_item(
        self,
        *,
        criterion: CriterionScore,
        rubric_item_description: str,
        earned_credit: bool,
    ) -> str:
        feedback = self._strip_terminal_punctuation(self._clean_text(criterion.feedback, limit=180))
        if feedback and not self._is_generic_feedback(feedback):
            return self._ensure_terminal_period(feedback[0].upper() + feedback[1:])
        description = self._strip_terminal_punctuation(self._clean_text(rubric_item_description, limit=180))
        if not description:
            return ""
        if earned_credit:
            return self._ensure_terminal_period(f"Meets the rubric criterion for {description.lower()}")
        return self._ensure_terminal_period(f"The rubric criterion for {description.lower()} was not fully satisfied")

    def _criteria_list_text(self, items: list[str], *, limit: int) -> str:
        fragments = [
            self._strip_terminal_punctuation(self._clean_text(item, limit=180))
            for item in items
            if self._strip_terminal_punctuation(self._clean_text(item, limit=180))
        ]
        if not fragments:
            return ""
        fragments = fragments[:limit]
        if len(fragments) == 1:
            return fragments[0]
        if len(fragments) == 2:
            return f"{fragments[0]} and {fragments[1]}"
        return f"{'; '.join(fragments[:-1])}; and {fragments[-1]}"

    def _summarize_credit_points(
        self,
        *,
        correct_elements: list[str],
        rubric: RubricQuestion,
        criterion_scores: list[CriterionScore],
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        positive_criteria_count = sum(1 for criterion in criterion_scores if criterion.awarded > 0)
        target_count = min(max_items, max(1, positive_criteria_count))
        for item in correct_elements:
            self._append_unique_item(items, item, limit=max_items)
            if len(items) >= target_count:
                return items
        for criterion, rubric_item in zip(criterion_scores, rubric.criteria):
            if criterion.awarded <= 0:
                continue
            self._append_unique_item(
                items,
                self._criterion_feedback_item(
                    criterion=criterion,
                    rubric_item_description=rubric_item.description,
                    earned_credit=True,
                ),
                limit=max_items,
            )
            if len(items) >= target_count:
                break
        return items

    def _summarize_missing_points(
        self,
        *,
        missing_elements: list[str],
        rubric: RubricQuestion,
        criterion_scores: list[CriterionScore],
        max_items: int,
    ) -> list[str]:
        items: list[str] = []
        negative_criteria_count = sum(1 for criterion in criterion_scores if criterion.awarded < criterion.max)
        target_count = min(max_items, max(1, negative_criteria_count))
        for item in missing_elements:
            self._append_unique_item(items, item, limit=max_items)
            if len(items) >= target_count:
                return items
        for criterion, rubric_item in zip(criterion_scores, rubric.criteria):
            if criterion.awarded >= criterion.max:
                continue
            self._append_unique_item(
                items,
                self._criterion_feedback_item(
                    criterion=criterion,
                    rubric_item_description=rubric_item.description,
                    earned_credit=False,
                ),
                limit=max_items,
            )
            if len(items) >= target_count:
                break
        return items

    def _evidence_sentence(
        self,
        *,
        visible_evidence: list[VisibleEvidenceItem],
        evidence_summaries: list[EvidenceSummary],
        has_ambiguous_numeric_signal: bool,
    ) -> str:
        sources: list[tuple[int | None, str]] = (
            [(item.page, item.summary) for item in evidence_summaries]
            if evidence_summaries
            else [(item.page, item.evidence) for item in visible_evidence]
        )
        if not sources:
            return ""

        phrases: list[tuple[int | None, str]] = []
        for page, text in sources[:2]:
            cleaned = self._strip_terminal_punctuation(self._clean_text(text, limit=180))
            if not cleaned:
                continue
            if has_ambiguous_numeric_signal and self._extract_numeric_tokens(cleaned):
                if self._contains_any(cleaned, ("conclusion", "compare", "greater", "less", "therefore", "hence", "better")):
                    cleaned = "the visible comparison and conclusion align with the expected result"
                elif self._contains_any(cleaned, ("formula", "integral", "setup", "derivation", "calculate")) or self._has_math_signal(cleaned):
                    cleaned = "the visible setup and calculation steps align with the expected method"
                else:
                    cleaned = "the visible value is consistent with the expected result up to rounding or equivalence"
            phrases.append((page, self._lowercase_first(cleaned)))

        if not phrases:
            return ""
        if len(phrases) == 1:
            page, fragment = phrases[0]
            if page:
                return f"Visible work on page {page} shows {fragment}."
            return f"Visible work shows {fragment}."
        first_page, first_fragment = phrases[0]
        second_page, second_fragment = phrases[1]
        if first_page and first_page == second_page:
            return f"Visible work on page {first_page} shows {first_fragment} and {second_fragment}."
        if first_page and second_page:
            return (
                f"Visible work on page {first_page} shows {first_fragment}, and page {second_page} shows {second_fragment}."
            )
        return f"Visible work shows {first_fragment} and {second_fragment}."

    def _has_strong_correctness_claim(self, items: list[str]) -> bool:
        return any(
            self._contains_any(
                item,
                (
                    "correct final answer",
                    "correct final result",
                    "correct conclusion",
                    "correct comparison",
                    "correctly computes",
                    "correct computed values",
                    "complete justification",
                    "substantially correct",
                ),
            )
            for item in items
        )

    def _has_substantive_visible_work(self, answer: StudentAnswer | None) -> bool:
        if answer is None:
            return False
        if answer.student_claims or answer.final_answer or answer.derivation_summary or answer.source_pages:
            return True
        transcription = " ".join(answer.transcription.split()).strip().lower()
        return bool(
            transcription
            and transcription
            not in {
                "no student answer was confidently located for this question.",
                "possible student work was detected, but the relevant page could not be isolated confidently.",
                "no answer was returned for this question.",
            }
            and "no answer was" not in transcription
            and "no student answer" not in transcription
        )

    def _looks_math_like(
        self,
        question: ExamQuestion,
        rubric: RubricQuestion | None,
        answer: StudentAnswer | None,
    ) -> bool:
        if answer is not None:
            claim_types = {claim.type.lower() for claim in answer.student_claims}
            if claim_types.intersection(
                {"formula", "numerical_value", "comparison", "derivation_step", "equation", "inequality", "setup", "integral"}
            ):
                return True
        haystacks = [
            question.question_text,
            question.official_solution,
            " ".join(item.expected_answer for item in rubric.criteria) if rubric is not None else "",
            answer.final_answer if answer else "",
            answer.derivation_summary if answer else "",
            answer.transcription if answer else "",
        ]
        symbolic_signals = ("=", "/", "∫", ">", "<", "+", "-", "*", "^", "≤", "≥", "≈")
        textual_signals = (
            "equation",
            "formula",
            "inequality",
            "fraction",
            "decimal",
            "value",
            "quantity",
            "compare",
            "derivation",
            "calculate",
            "simplify",
            "evaluate",
            "substitute",
        )
        return any(
            any(signal in (text or "") for signal in symbolic_signals)
            or self._contains_any(text or "", textual_signals)
            or bool(re.search(r"\d", text or ""))
            for text in haystacks
        )

    def _has_ambiguous_numeric_signal(self, answer: StudentAnswer | None) -> bool:
        if answer is None:
            return False
        texts = [*answer.uncertain_parts]
        if answer.transcription:
            texts.append(answer.transcription)
        if answer.final_answer:
            texts.append(answer.final_answer)
        if answer.derivation_summary:
            texts.append(answer.derivation_summary)
        texts.extend(claim.content for claim in answer.student_claims)
        if any(re.search(r"\d+\s*/\s*\d+", text) for text in texts):
            if any(
                self._contains_any(
                    text,
                    ("unclear", "ambiguous", "appears", "likely", "digit", "hard to read", "partially unclear"),
                )
                for text in texts
            ):
                return True
        return any(
            self._contains_any(
                text,
                ("unclear digit", "ambiguous digit", "unclear fraction", "partially unclear value", "likely intended"),
            )
            for text in texts
        )

    @staticmethod
    def _extract_numeric_tokens(text: str) -> list[str]:
        return list(dict.fromkeys(token for token in re.findall(r"\d+(?:\.\d+)?(?:\s*/\s*\d+)?", text or "") if token))

    @staticmethod
    def _digits_only(token: str) -> str:
        return "".join(character for character in token if character.isdigit())

    @staticmethod
    def _differs_by_one_missing_digit(expected: str, observed: str) -> bool:
        if len(expected) - len(observed) != 1:
            return False
        for index in range(len(expected)):
            if expected[:index] + expected[index + 1 :] == observed:
                return True
        return False

    def _has_possible_digit_drop(
        self,
        *,
        question: ExamQuestion,
        rubric: RubricQuestion | None,
        answer: StudentAnswer | None,
    ) -> bool:
        if answer is None:
            return False
        official_tokens: list[str] = []
        sources = [question.official_solution]
        if rubric is not None:
            sources.extend(item.expected_answer for item in rubric.criteria)
        for text in sources:
            official_tokens.extend(self._extract_numeric_tokens(text))
        if not official_tokens:
            return False
        student_tokens: list[str] = []
        for text in [
            answer.final_answer or "",
            answer.derivation_summary or "",
            answer.transcription or "",
            *[claim.content for claim in answer.student_claims],
        ]:
            student_tokens.extend(self._extract_numeric_tokens(text))
        for official_token in official_tokens:
            official_digits = self._digits_only(official_token)
            if len(official_digits) < 3:
                continue
            for student_token in student_tokens:
                student_digits = self._digits_only(student_token)
                if len(student_digits) < 2:
                    continue
                if self._differs_by_one_missing_digit(official_digits, student_digits):
                    return True
        return False

    def _has_numeric_uncertainty_signal(
        self,
        *,
        question: ExamQuestion,
        rubric: RubricQuestion | None,
        answer: StudentAnswer | None,
    ) -> bool:
        return self._has_ambiguous_numeric_signal(answer) or self._has_possible_digit_drop(
            question=question,
            rubric=rubric,
            answer=answer,
        )

    def _has_setup_signal(self, answer: StudentAnswer | None) -> bool:
        if answer is None:
            return False
        claim_types = {claim.type.lower() for claim in answer.student_claims}
        if claim_types.intersection({"derivation_step", "formula", "numerical_value", "comparison", "setup", "integral"}):
            return True
        text = " ".join(
            part
            for part in (
                answer.derivation_summary or "",
                answer.transcription or "",
                " ".join(claim.content for claim in answer.student_claims),
            )
            if part
        )
        return self._contains_any(
            text,
            ("integral", "compare", "substitute", "using", "therefore", "hence", "setup", "calculate", "method"),
        ) or any(symbol in text for symbol in ("=", "∫", "/", ">", "<"))

    def _has_conclusion_signal(self, answer: StudentAnswer | None) -> bool:
        if answer is None:
            return False
        claim_types = {claim.type.lower() for claim in answer.student_claims}
        if claim_types.intersection({"conclusion", "comparison", "final_answer"}):
            return True
        text = " ".join(
            part
            for part in (
                answer.final_answer or "",
                answer.derivation_summary or "",
                answer.transcription or "",
                " ".join(claim.content for claim in answer.student_claims),
            )
            if part
        )
        return self._contains_any(text, ("therefore", "hence", "so ", "better", "greater", "larger", "choose", "preferred"))

    def _has_visible_final_or_equivalent_signal(self, answer: StudentAnswer | None) -> bool:
        if answer is None:
            return False
        if answer.final_answer:
            return True
        text = " ".join(claim.content for claim in answer.student_claims)
        return bool(re.search(r"\d+\s*/\s*\d+|\d+\.\d+", text))

    @staticmethod
    def _low_score_floor(max_marks: float) -> float:
        if max_marks >= 5:
            return min(round(max_marks, 2), 2.0)
        return round(min(max_marks, max_marks * 0.4), 2)

    def _should_soften_low_score(
        self,
        *,
        question: ExamQuestion,
        rubric: RubricQuestion | None,
        answer: StudentAnswer | None,
        criterion_scores: list[CriterionScore],
        awarded_marks: float,
        max_marks: float | None = None,
    ) -> bool:
        if answer is None or not self._looks_math_like(question, rubric, answer):
            return False
        available_max_marks = rubric.max_marks if rubric is not None else (max_marks or 0.0)
        floor = self._low_score_floor(available_max_marks)
        if awarded_marks >= floor:
            return False
        if not self._has_substantive_visible_work(answer):
            return False
        if not self._has_numeric_uncertainty_signal(question=question, rubric=rubric, answer=answer):
            return False
        has_positive_credit = any(score.awarded > 0 for score in criterion_scores)
        has_setup = self._has_setup_signal(answer)
        has_conclusion = self._has_conclusion_signal(answer)
        has_final_signal = self._has_visible_final_or_equivalent_signal(answer)
        return has_positive_credit or ((has_setup or has_final_signal) and has_conclusion)

    def _needs_low_score_review(
        self,
        *,
        question: ExamQuestion,
        rubric: RubricQuestion,
        answer: StudentAnswer | None,
        criterion_scores: list[CriterionScore],
        awarded_marks: float,
        max_marks: float,
        correct_elements: list[str],
        missing_elements: list[str],
        visible_evidence: list[VisibleEvidenceItem],
    ) -> bool:
        if answer is None or not self._has_substantive_visible_work(answer):
            return False
        softened = self._should_soften_low_score(
            question=question,
            rubric=rubric,
            answer=answer,
            criterion_scores=criterion_scores,
            awarded_marks=awarded_marks,
            max_marks=max_marks,
        )
        contradictory_low_score = (
            self._is_low_score(awarded_marks=awarded_marks, max_marks=max_marks)
            and (
                self._has_strong_correctness_claim(correct_elements)
                or self._evidence_shows_category(
                    category="final_answer",
                    visible_evidence=visible_evidence,
                    correct_elements=correct_elements,
                    answer=answer,
                )
                or self._evidence_shows_category(
                    category="conclusion",
                    visible_evidence=visible_evidence,
                    correct_elements=correct_elements,
                    answer=answer,
                )
            )
            and not any(self._has_serious_issue_language(item) for item in missing_elements)
        )
        return softened or contradictory_low_score or (
            answer.status == "unclear"
            and awarded_marks <= max(0.5, round(max_marks * 0.2, 2))
        )

    def _finalize_score_rationale(
        self,
        *,
        draft: QuestionGradeResult,
        question: ExamQuestion,
        rubric: RubricQuestion,
        answer: StudentAnswer | None,
        awarded_marks: float,
        missing_elements: list[str],
        correct_elements: list[str],
        visible_evidence: list[VisibleEvidenceItem],
        evidence_summaries: list[EvidenceSummary],
        criterion_scores: list[CriterionScore],
    ) -> str:
        rationale = self._clean_text(draft.score_rationale or draft.feedback or "", limit=650)
        if rationale and self._is_generic_feedback(rationale):
            rationale = ""
        has_ambiguous_numeric_signal = bool(
            answer and self._has_numeric_uncertainty_signal(question=question, rubric=rubric, answer=answer)
        )
        ambiguous_only_issue = bool(
            missing_elements
            and all(
                self._contains_any(
                    item,
                    ("unclear", "ambiguous", "appears", "likely", "partially unclear", "hard to read", "notation", "unit"),
                )
                for item in missing_elements
            )
        )
        marks_lost = round(max(0.0, rubric.max_marks - awarded_marks), 2)
        credit_points = self._summarize_credit_points(
            correct_elements=correct_elements,
            rubric=rubric,
            criterion_scores=criterion_scores,
            max_items=4,
        )
        issue_points = self._summarize_missing_points(
            missing_elements=missing_elements,
            rubric=rubric,
            criterion_scores=criterion_scores,
            max_items=3,
        )
        credit_summary = self._criteria_list_text(credit_points, limit=3)
        issue_summary = self._criteria_list_text(issue_points, limit=2)
        evidence_sentence = self._evidence_sentence(
            visible_evidence=visible_evidence,
            evidence_summaries=evidence_summaries,
            has_ambiguous_numeric_signal=has_ambiguous_numeric_signal,
        )
        if has_ambiguous_numeric_signal and rationale and self._extract_numeric_tokens(rationale):
            rationale = ""
        if rationale and answer and self._has_substantive_visible_work(answer) and self._contains_absence_language(rationale):
            rationale = ""

        if self._is_full_score(awarded_marks=awarded_marks, max_marks=rubric.max_marks):
            minor_note = ""
            if missing_elements and all(self._has_minor_issue_language(item) for item in missing_elements):
                minor_note = " Minor clarity or presentation issues do not affect the score."
            if credit_summary:
                rationale = f"The response earns full credit because it satisfies the key rubric criteria: {credit_summary}."
            elif evidence_sentence:
                rationale = "The response earns full credit because the visible work satisfies the required rubric criteria."
            else:
                rationale = "The response earns full credit because the visible work satisfies the required result and supporting criteria."
            if evidence_sentence:
                rationale = f"{rationale} {evidence_sentence}"
            if minor_note:
                rationale = f"{rationale}{minor_note}"
            return rationale[:650]

        if self._is_near_full_score(awarded_marks=awarded_marks, max_marks=rubric.max_marks):
            if credit_summary:
                rationale = (
                    f"The response is substantially correct because it satisfies most key rubric criteria: {credit_summary}."
                )
            else:
                rationale = f"The response earns {awarded_marks}/{rubric.max_marks} because it is substantially correct overall."
            if evidence_sentence:
                rationale = f"{rationale} {evidence_sentence}"
            if issue_summary:
                if ambiguous_only_issue:
                    rationale += " A small deduction is applied because one handwritten or presentation detail remains partially unclear, but the main rubric-linked work is still present."
                else:
                    rationale += (
                        f" A small deduction of about {self._format_mark_amount(marks_lost)} is applied because "
                        f"{self._lowercase_first(issue_summary)}."
                    )
            return rationale[:650]

        answer_status = answer.status if answer else "missing"
        if answer_status == "missing":
            return "No answer was located, so none of the rubric criteria could be credited."
        if answer and self._has_substantive_visible_work(answer):
            if self._is_low_score(awarded_marks=awarded_marks, max_marks=rubric.max_marks) and issue_summary:
                credited_work = credit_summary or "some visible work satisfies a limited part of the rubric"
                rationale = (
                    f"The response earns {awarded_marks}/{rubric.max_marks} because it shows some rubric-linked work: {credited_work}. "
                    f"Higher credit is not justified because {self._lowercase_first(issue_summary)}."
                )
                if evidence_sentence:
                    rationale = f"{rationale} {evidence_sentence}"
                return rationale[:650]
            if issue_summary and marks_lost > 0:
                credit_lead = credit_summary or "the visible work satisfies part of the rubric"
                rationale = (
                    f"The response earns {awarded_marks}/{rubric.max_marks} because {self._lowercase_first(credit_lead)}. "
                    f"Marks are deducted because {self._lowercase_first(issue_summary)}."
                )
                if ambiguous_only_issue:
                    rationale = f"{rationale} This is a limited deduction of about {self._format_mark_amount(marks_lost)}."
                else:
                    rationale = f"{rationale} That deduction is about {self._format_mark_amount(marks_lost)}."
                if evidence_sentence:
                    rationale = f"{rationale} {evidence_sentence}"
                return rationale[:650]
            if credit_summary:
                rationale = f"The response earns {awarded_marks}/{rubric.max_marks} because it satisfies some rubric criteria: {credit_summary}."
                if evidence_sentence:
                    rationale = f"{rationale} {evidence_sentence}"
                return rationale[:650]
            return (
                f"The response earns {awarded_marks}/{rubric.max_marks} because only part of the rubric could be confirmed from the visible work. "
                "The remaining marks depend on rubric criteria that are still missing, incorrect, or not clearly supported by the submitted answer."
            )[:650]
        return (
            f"The response earns {awarded_marks}/{rubric.max_marks} because it satisfies only part of the rubric; missing or unclear required elements prevented full credit."
        )[:650]

    def _finalize_correct_elements(
        self,
        *,
        draft: QuestionGradeResult,
        rubric: RubricQuestion,
        criterion_scores: list[CriterionScore],
        answer: StudentAnswer | None,
    ) -> list[str]:
        provided = self._clean_items(list(draft.correct_elements), limit=4)
        generated = list(provided)
        for criterion, rubric_item in zip(criterion_scores, rubric.criteria):
            if criterion.awarded <= 0:
                continue
            self._append_unique_item(
                generated,
                self._criterion_feedback_item(
                    criterion=criterion,
                    rubric_item_description=rubric_item.description,
                    earned_credit=True,
                ),
                limit=4,
            )
        if not generated and answer and answer.final_answer:
            generated.append(self._ensure_terminal_period(f"The response includes a usable final answer: {answer.final_answer[:140]}"))
        if not generated and answer and answer.status == "answered":
            generated.append("The response contains some work that supports limited partial credit.")
        return self._clean_items(generated, limit=4)

    def _finalize_missing_elements(
        self,
        *,
        draft: QuestionGradeResult,
        rubric: RubricQuestion,
        criterion_scores: list[CriterionScore],
        answer: StudentAnswer | None,
    ) -> list[str]:
        if all(criterion.awarded >= criterion.max for criterion in criterion_scores) and criterion_scores:
            provided = self._clean_items(list(draft.missing_or_incorrect_elements), limit=4)
            if not provided or provided == ["The response does not fully meet every rubric requirement for full credit."]:
                return []
            if any("does not fully meet every rubric requirement" in item.lower() for item in provided):
                return ["No substantive issues."]
            return provided
        provided = self._clean_items(list(draft.missing_or_incorrect_elements), limit=4)
        if provided and not (
            answer
            and self._has_substantive_visible_work(answer)
            and any(self._contains_absence_language(item) for item in provided)
        ):
            return provided
        generated: list[str] = []
        for criterion, rubric_item in zip(criterion_scores, rubric.criteria):
            if criterion.awarded >= criterion.max:
                continue
            self._append_unique_item(
                generated,
                self._criterion_feedback_item(
                    criterion=criterion,
                    rubric_item_description=rubric_item.description,
                    earned_credit=False,
                ),
                limit=4,
            )
        if not generated and answer and answer.uncertain_parts:
            generated.append(self._ensure_terminal_period(f"Some handwritten content remains partially unclear: {', '.join(answer.uncertain_parts[:3])}"))
        if not generated:
            generated.append("One or more remaining rubric criteria were not demonstrated clearly enough in the visible work to earn the remaining marks.")
        return self._clean_items(generated, limit=4)

    def _finalize_improvement_suggestions(
        self,
        *,
        draft: QuestionGradeResult,
        rubric: RubricQuestion,
        criterion_scores: list[CriterionScore],
        answer: StudentAnswer | None,
        awarded_marks: float,
        max_marks: float,
    ) -> list[str]:
        provided = self._clean_items(list(draft.improvement_suggestions), limit=3)
        if provided:
            return provided
        if awarded_marks >= max_marks and max_marks > 0:
            return []
        generated = []
        for criterion, rubric_item in zip(criterion_scores, rubric.criteria):
            if criterion.awarded < criterion.max:
                generated.append(f"To gain full credit, include {rubric_item.description.lower()}.")
        if not generated and answer and answer.status != "answered":
            generated.append("Write the full solution steps clearly enough to verify each rubric point.")
        return self._clean_items(generated or ["State the final result clearly and justify it against the required method."], limit=3)

    def _harmonize_correct_elements(
        self,
        *,
        correct_elements: list[str],
        missing_elements: list[str],
        awarded_marks: float,
        max_marks: float,
    ) -> list[str]:
        if not correct_elements:
            return []
        cleaned: list[str] = []
        missing_text = " ".join(missing_elements).lower()
        low_score = max_marks > 0 and awarded_marks < round(max_marks * 0.4, 2)
        for item in correct_elements:
            lowered = item.lower()
            if "final answer" in lowered and self._contains_any(missing_text, ("final answer", "final value", "final condition")):
                continue
            if "conclusion" in lowered and self._contains_any(missing_text, ("conclusion", "comparison")):
                continue
            if low_score and self._contains_any(
                lowered,
                ("complete", "fully correct", "full credit", "all required", "entire solution", "complete justification"),
            ):
                continue
            cleaned.append(item)
        if not cleaned and awarded_marks > 0:
            cleaned.append("Some visible work earned partial credit.")
        return self._clean_items(cleaned, limit=4)

    def _harmonize_missing_elements(
        self,
        *,
        missing_elements: list[str],
        correct_elements: list[str],
        visible_evidence: list[VisibleEvidenceItem],
        answer: StudentAnswer | None,
        awarded_marks: float,
        max_marks: float,
    ) -> list[str]:
        if self._is_full_score(awarded_marks=awarded_marks, max_marks=max_marks):
            filtered = [item for item in missing_elements if self._has_minor_issue_language(item)]
            return self._clean_items(filtered, limit=4) if filtered else []
        if self._is_near_full_score(awarded_marks=awarded_marks, max_marks=max_marks):
            filtered = [item for item in missing_elements if not self._has_serious_issue_language(item)]
            missing_elements = filtered if filtered else ["A minor verification or clarity detail was not fully established."]
        cleaned: list[str] = []
        evidence_text = " ".join(self._normalize_phrase(item.evidence) for item in visible_evidence)
        correct_text = " ".join(self._normalize_phrase(item) for item in correct_elements)
        for item in missing_elements:
            lowered = item.lower()
            if self._is_generic_feedback(item) and len(missing_elements) > 1:
                continue
            if (
                ("no calculation" in lowered or "calculation" in lowered and "missing" in lowered)
                and self._evidence_shows_category(
                    category="calculation",
                    visible_evidence=visible_evidence,
                    correct_elements=correct_elements,
                    answer=answer,
                )
            ):
                continue
            if (
                ("no final answer" in lowered or "final answer" in lowered and "missing" in lowered)
                and self._evidence_shows_category(
                    category="final_answer",
                    visible_evidence=visible_evidence,
                    correct_elements=correct_elements,
                    answer=answer,
                )
            ):
                continue
            if (
                ("no conclusion" in lowered or "conclusion" in lowered and "missing" in lowered)
                and self._evidence_shows_category(
                    category="conclusion",
                    visible_evidence=visible_evidence,
                    correct_elements=correct_elements,
                    answer=answer,
                )
            ):
                continue
            normalized = self._normalize_phrase(item)
            if (
                ("missing" in lowered or "absent" in lowered)
                and normalized
                and (normalized in evidence_text or normalized in correct_text)
            ):
                continue
            cleaned.append(item)
        return self._clean_items(cleaned, limit=4)

    def _harmonize_improvement_suggestions(
        self,
        *,
        suggestions: list[str],
        missing_elements: list[str],
        awarded_marks: float,
        max_marks: float,
    ) -> list[str]:
        if self._is_full_score(awarded_marks=awarded_marks, max_marks=max_marks):
            return []
        if self._is_near_full_score(awarded_marks=awarded_marks, max_marks=max_marks):
            suggestions = [
                suggestion
                for suggestion in suggestions
                if not self._contains_any(suggestion, ("redo", "major", "fundamental", "conceptual"))
            ]
        if not missing_elements:
            return []
        return self._clean_items(suggestions, limit=3)

    def _harmonize_evidence_summaries(
        self,
        *,
        evidence_summaries: list[EvidenceSummary],
        visible_evidence: list[VisibleEvidenceItem],
    ) -> list[EvidenceSummary]:
        cleaned: list[EvidenceSummary] = []
        visible_keys = {
            (item.page, self._clean_text(item.evidence, limit=220).lower())
            for item in visible_evidence
        }
        seen: set[tuple[int | None, str]] = set()
        for item in evidence_summaries:
            summary = self._clean_text(item.summary, limit=220)
            key = (item.page, summary.lower())
            if key in seen or key in visible_keys:
                continue
            cleaned.append(EvidenceSummary(page=item.page, summary=summary))
            seen.add(key)
            if len(cleaned) >= 2:
                break
        return cleaned

    def _finalize_evidence_summaries(
        self,
        *,
        draft: QuestionGradeResult,
        answer: StudentAnswer | None,
        criterion_scores: list[CriterionScore],
        visible_evidence: list[VisibleEvidenceItem],
    ) -> list[EvidenceSummary]:
        if draft.evidence_summaries:
            cleaned: list[EvidenceSummary] = []
            seen: set[tuple[int | None, str]] = set()
            for item in draft.evidence_summaries:
                summary = self._clean_text(item.summary, limit=220)
                key = (item.page, summary.lower())
                if summary and key not in seen:
                    cleaned.append(EvidenceSummary(page=item.page, summary=summary))
                    seen.add(key)
                if len(cleaned) >= 2:
                    break
            if cleaned:
                return cleaned
        if visible_evidence:
            return [
                EvidenceSummary(page=item.page, summary=self._clean_text(item.evidence, limit=220))
                for item in visible_evidence[:2]
            ]
        generated = self._fallback_evidence_summaries(answer)
        if generated:
            return generated
        for criterion in criterion_scores:
            if criterion.evidence is not None:
                return [
                    EvidenceSummary(
                        page=criterion.evidence.page,
                        summary="A recorded evidence region supports the awarded partial credit."
                        if criterion.awarded > 0
                        else "A recorded evidence region was reviewed but did not satisfy the full criterion.",
                    )
                ]
        return []

    def _finalize_visible_evidence(
        self,
        *,
        draft: QuestionGradeResult,
        answer: StudentAnswer | None,
        criterion_scores: list[CriterionScore],
    ) -> list[VisibleEvidenceItem]:
        if draft.visible_evidence:
            cleaned: list[VisibleEvidenceItem] = []
            seen: set[tuple[int | None, str]] = set()
            for item in draft.visible_evidence:
                evidence = self._clean_text(item.evidence, limit=220)
                key = (item.page, evidence)
                if evidence and key not in seen:
                    cleaned.append(VisibleEvidenceItem(page=item.page, evidence=evidence))
                    seen.add(key)
                if len(cleaned) >= 3:
                    break
            if cleaned:
                return cleaned
        generated = self._fallback_visible_evidence(answer)
        if generated:
            return generated
        for criterion in criterion_scores:
            if criterion.evidence is not None:
                return [
                    VisibleEvidenceItem(
                        page=criterion.evidence.page,
                        evidence="A recorded evidence region on this page was used while checking the rubric criteria.",
                    )
                ]
        return []

    def _fallback_visible_evidence(self, answer: StudentAnswer | None) -> list[VisibleEvidenceItem]:
        if answer is None:
            return []
        items: list[VisibleEvidenceItem] = []
        seen: set[tuple[int | None, str]] = set()

        for claim in answer.student_claims:
            evidence = self._clean_text(claim.content, limit=220)
            key = (claim.evidence_page, evidence)
            if evidence and key not in seen:
                items.append(VisibleEvidenceItem(page=claim.evidence_page, evidence=evidence))
                seen.add(key)
            if len(items) >= 3:
                return items

        primary_page = answer.source_pages[0] if answer.source_pages else answer.evidence.page if answer and answer.evidence else None
        if answer.final_answer:
            prefix = "The student appears to write" if self._has_ambiguous_numeric_signal(answer) else "Student writes"
            evidence = self._clean_text(
                f"{prefix} {answer.final_answer}.",
                limit=220,
            )
            key = (primary_page, evidence)
            if key not in seen:
                items.append(VisibleEvidenceItem(page=primary_page, evidence=evidence))
                seen.add(key)
        if answer.derivation_summary and len(items) < 3:
            evidence = self._clean_text(answer.derivation_summary, limit=220)
            key = (primary_page, evidence)
            if key not in seen:
                items.append(VisibleEvidenceItem(page=primary_page, evidence=evidence))
                seen.add(key)
        if not items and answer.evidence is not None:
            items.append(
                VisibleEvidenceItem(
                    page=answer.evidence.page,
                    evidence=(
                        "Visible work on this page was reviewed, but the value is partially unclear."
                        if self._has_ambiguous_numeric_signal(answer)
                        else "Visible work on this page was reviewed, but the transcription remained limited."
                    ),
                )
            )
        return items[:3]

    @staticmethod
    def _fallback_evidence_summaries(
        answer: StudentAnswer | None,
        *,
        visible_evidence: list[VisibleEvidenceItem] | None = None,
    ) -> list[EvidenceSummary]:
        if visible_evidence:
            return [
                EvidenceSummary(page=item.page, summary=" ".join(item.evidence.split()).strip()[:220])
                for item in visible_evidence[:2]
            ]
        if answer is None or answer.evidence is None:
            return []
        snippets: list[str] = []
        if answer.final_answer:
            snippets.append(f"Final answer noted as {answer.final_answer[:120]}.")
        if answer.derivation_summary:
            snippets.append(answer.derivation_summary[:180])
        if answer.transcription:
            snippets.append(answer.transcription[:180])
        summary = " ".join(snippets).strip() or "Visible work on this page was reviewed for grading."
        return [EvidenceSummary(page=answer.evidence.page, summary=summary[:220])]
