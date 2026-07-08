from __future__ import annotations

from django.test import SimpleTestCase

from grading_engine.agents.equivalence import build_equivalence_seeds
from grading_engine.agents.validator import GradingValidator
from grading_engine.schemas import (
    CriterionScore,
    Evidence,
    ExamQuestion,
    GradingDraft,
    GradingResult,
    QuestionGradeResult,
    RubricCriterionItem,
    RubricQuestion,
    StudentAnswer,
    StudentClaim,
)


class GradingQualityValidatorTests(SimpleTestCase):
    def make_exam_question(self) -> ExamQuestion:
        return ExamQuestion(
            question_id="1",
            question_text="Solve for the feasible range.",
            official_solution="Official solution text.",
            source_pages=[1],
        )

    def make_rubric_question(self) -> RubricQuestion:
        return RubricQuestion(
            question_id="1",
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            max_marks=5.0,
            criteria=[
                RubricCriterionItem(
                    criterion_id="1.1",
                    description="Correct final condition",
                    expected_answer="b > 1/2 and b + 1 < Ia < 5b - 1",
                    marks=5.0,
                    source="official_explicit",
                )
            ],
        )

    def make_draft(self) -> QuestionGradeResult:
        return QuestionGradeResult(
            question_id="1",
            awarded_marks=4.5,
            max_marks=5.0,
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            feedback="The final condition is present and mostly justified.",
            score_rationale="The final condition is visible and matches the required result, with only minor notation issues.",
            correct_elements=[],
            missing_or_incorrect_elements=[],
            improvement_suggestions=[],
            evidence_summaries=[],
            visible_evidence=[],
            confidence=0.8,
            needs_human_review=False,
            criterion_scores=[
                CriterionScore(
                    criterion_id="1.1",
                    awarded=4.5,
                    max=5.0,
                    match_type="equivalent_variant",
                    verification_status="verified",
                    feedback="the correct final condition in an equivalent form",
                    confidence=0.8,
                    needs_human_review=False,
                    evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                )
            ],
        )

    def test_validator_falls_back_to_student_claims_for_visible_evidence(self) -> None:
        validator = GradingValidator()
        answer = StudentAnswer(
            question_id="1",
            status="answered",
            transcription="Student writes the final inequality and brief supporting algebra.",
            final_answer="Ia - 1 > b > (Ia + 1)/5",
            derivation_summary="A short rearrangement leads to the same feasible region.",
            uncertain_parts=[],
            student_claims=[
                StudentClaim(
                    type="inequality",
                    content="Student writes Ia - 1 > b > (Ia + 1)/5 as the final feasible range.",
                    evidence_page=2,
                )
            ],
            source_pages=[2],
            evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.85,
            needs_human_review=False,
        )

        result = validator.run(
            grading_id="demo",
            model_deployment="gpt-5.4-mini",
            duration_ms=1000,
            exam_questions=[self.make_exam_question()],
            rubric_questions=[self.make_rubric_question()],
            student_answers=[answer],
            grading_draft=GradingDraft(questions=[self.make_draft()]),
        )

        question = result.questions[0]
        self.assertEqual(question.visible_evidence[0].page, 2)
        self.assertIn("Ia - 1 > b > (Ia + 1)/5", question.visible_evidence[0].evidence)
        self.assertEqual(question.evidence_summaries, [])

    def test_missing_draft_with_unclear_visible_work_does_not_claim_blank_answer(self) -> None:
        validator = GradingValidator()
        answer = StudentAnswer(
            question_id="1",
            status="unclear",
            transcription="A handwritten final formula is visible but not fully legible.",
            final_answer=None,
            derivation_summary=None,
            uncertain_parts=["final formula"],
            student_claims=[],
            source_pages=[2],
            evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.35,
            needs_human_review=True,
        )

        result = validator.run(
            grading_id="demo",
            model_deployment="gpt-5.4-mini",
            duration_ms=1000,
            exam_questions=[self.make_exam_question()],
            rubric_questions=[self.make_rubric_question()],
            student_answers=[answer],
            grading_draft=GradingDraft(questions=[]),
        )

        question = result.questions[0]
        self.assertTrue(question.needs_human_review)
        self.assertNotIn("No answer was located", question.score_rationale)
        self.assertIn("Visible work", question.score_rationale)
        self.assertEqual(question.visible_evidence[0].page, 2)

    def test_ambiguous_handwritten_number_keeps_score_and_flags_review(self) -> None:
        validator = GradingValidator()
        question = ExamQuestion(
            question_id="2",
            question_text="Compare the two area moments of inertia and decide which option is better.",
            official_solution="I_A = 245/2, I_B = 731/4, so I_B > I_A and option B is better.",
            source_pages=[1],
        )
        rubric = RubricQuestion(
            question_id="2",
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            max_marks=5.0,
            criteria=[
                RubricCriterionItem(
                    criterion_id="2.1",
                    description="Correct setup, comparison, and conclusion",
                    expected_answer="I_A = 245/2, I_B = 731/4, therefore option B is better",
                    marks=5.0,
                    source="official_explicit",
                )
            ],
        )
        answer = StudentAnswer(
            question_id="2",
            status="unclear",
            transcription=(
                "Student appears to write the inertia calculations and concludes I_B > I_A, so B is better. "
                "The numerator in one fraction is partially unclear."
            ),
            final_answer="I_B > I_A, therefore B is better",
            derivation_summary="Sets up both integrals and compares the two final values before choosing B.",
            uncertain_parts=["The handwritten value appears to be 731/4, but one digit in the numerator is ambiguous."],
            student_claims=[
                StudentClaim(
                    type="derivation_step",
                    content="Student sets up the integrals for both area moments of inertia.",
                    evidence_page=2,
                ),
                StudentClaim(
                    type="comparison",
                    content="Student appears to compare the two values and writes I_B > I_A.",
                    evidence_page=2,
                ),
                StudentClaim(
                    type="conclusion",
                    content="Student concludes B is better; the value is partially unclear but consistent with that comparison.",
                    evidence_page=2,
                ),
            ],
            source_pages=[2],
            evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.45,
            needs_human_review=False,
        )
        draft = QuestionGradeResult(
            question_id="2",
            awarded_marks=1.0,
            max_marks=5.0,
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            feedback="One numerical value was read as incorrect, so only limited credit was awarded.",
            score_rationale="A handwritten numerator is ambiguous, but the setup and final conclusion appear consistent.",
            correct_elements=["The setup and comparison are mostly present."],
            missing_or_incorrect_elements=["One handwritten fraction is partially unclear."],
            improvement_suggestions=["Write the final numerical values more clearly."],
            evidence_summaries=[],
            visible_evidence=[],
            confidence=0.45,
            needs_human_review=False,
            criterion_scores=[
                CriterionScore(
                    criterion_id="2.1",
                    awarded=1.0,
                    max=5.0,
                    match_type="partial_credit",
                    verification_status="partial",
                    feedback="the method and conclusion, but not every digit in the final numeric value",
                    confidence=0.45,
                    needs_human_review=False,
                    evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                )
            ],
        )

        result = validator.run(
            grading_id="demo",
            model_deployment="gpt-5.4-mini",
            duration_ms=1000,
            exam_questions=[question],
            rubric_questions=[rubric],
            student_answers=[answer],
            grading_draft=GradingDraft(questions=[draft]),
        )

        graded = result.questions[0]
        self.assertEqual(graded.awarded_marks, 1.0)
        self.assertTrue(graded.needs_human_review)
        self.assertIn("partially unclear", graded.score_rationale)
        self.assertNotIn("withheld for verification", graded.score_rationale.lower())

    def test_possible_leading_digit_drop_keeps_score_and_flags_review(self) -> None:
        validator = GradingValidator()
        question = ExamQuestion(
            question_id="2",
            question_text="Compare the two computed section properties and choose the better option.",
            official_solution="Property A = 338.67, Property B = 586.67, so option B is better.",
            source_pages=[1],
        )
        rubric = RubricQuestion(
            question_id="2",
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            max_marks=5.0,
            criteria=[
                RubricCriterionItem(
                    criterion_id="2.1",
                    description="Correct computation, comparison, and conclusion",
                    expected_answer="Property A = 338.67, Property B = 586.67, therefore option B is better",
                    marks=5.0,
                    source="official_explicit",
                )
            ],
        )
        answer = StudentAnswer(
            question_id="2",
            status="answered",
            transcription="Student computes both values, writes 38.67 for A, and concludes B is better.",
            final_answer="Property B is better",
            derivation_summary="The setup and comparison are shown before the final conclusion.",
            uncertain_parts=[],
            student_claims=[
                StudentClaim(
                    type="numerical_value",
                    content="Student appears to write 38.67 for Property A.",
                    evidence_page=2,
                ),
                StudentClaim(
                    type="comparison",
                    content="Student compares the two values and writes that B is greater.",
                    evidence_page=2,
                ),
                StudentClaim(
                    type="conclusion",
                    content="Student concludes option B is better.",
                    evidence_page=2,
                ),
            ],
            source_pages=[2],
            evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.55,
            needs_human_review=False,
        )
        draft = QuestionGradeResult(
            question_id="2",
            awarded_marks=1.0,
            max_marks=5.0,
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            feedback="One numerical value was transcribed as incorrect, so little credit was awarded.",
            score_rationale="The comparison and final conclusion are visible, but one leading digit may be unclear.",
            correct_elements=["The comparison and final conclusion are present."],
            missing_or_incorrect_elements=["One numerical value may have been misread."],
            improvement_suggestions=["Write the computed values more clearly."],
            evidence_summaries=[],
            visible_evidence=[],
            confidence=0.5,
            needs_human_review=False,
            criterion_scores=[
                CriterionScore(
                    criterion_id="2.1",
                    awarded=1.0,
                    max=5.0,
                    match_type="partial_credit",
                    verification_status="partial",
                    feedback="the visible comparison and conclusion, but not the confidently verified leading digit",
                    confidence=0.5,
                    needs_human_review=False,
                    evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                )
            ],
        )

        result = validator.run(
            grading_id="demo",
            model_deployment="gpt-5.4-mini",
            duration_ms=1000,
            exam_questions=[question],
            rubric_questions=[rubric],
            student_answers=[answer],
            grading_draft=GradingDraft(questions=[draft]),
        )

        graded = result.questions[0]
        self.assertEqual(graded.awarded_marks, 1.0)
        self.assertTrue(graded.needs_human_review)
        self.assertIn("higher credit is not justified", graded.score_rationale.lower())
        self.assertNotIn("worst-case digit reading", graded.score_rationale.lower())

    def test_full_score_does_not_keep_generic_missing_text(self) -> None:
        validator = GradingValidator()
        draft = QuestionGradeResult(
            question_id="1",
            awarded_marks=5.0,
            max_marks=5.0,
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            feedback="Complete solution.",
            score_rationale="The response matches the required result and supporting work.",
            correct_elements=["Correct final answer and complete justification."],
            missing_or_incorrect_elements=["The response does not fully meet every rubric requirement for full credit."],
            improvement_suggestions=[],
            evidence_summaries=[],
            visible_evidence=[],
            confidence=0.95,
            needs_human_review=False,
            criterion_scores=[
                CriterionScore(
                    criterion_id="1.1",
                    awarded=5.0,
                    max=5.0,
                    match_type="exact_match",
                    verification_status="verified",
                    feedback="the complete required solution",
                    confidence=0.95,
                    needs_human_review=False,
                    evidence=Evidence(page=1, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                )
            ],
        )
        answer = StudentAnswer(
            question_id="1",
            status="answered",
            transcription="A complete answer is visible.",
            final_answer="Correct final answer",
            derivation_summary="All required steps are present.",
            uncertain_parts=[],
            student_claims=[],
            source_pages=[1],
            evidence=Evidence(page=1, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.95,
            needs_human_review=False,
        )

        result = validator.run(
            grading_id="demo",
            model_deployment="gpt-5.4-mini",
            duration_ms=1000,
            exam_questions=[self.make_exam_question()],
            rubric_questions=[self.make_rubric_question()],
            student_answers=[answer],
            grading_draft=GradingDraft(questions=[draft]),
        )

        self.assertEqual(result.questions[0].missing_or_incorrect_elements, [])
        self.assertIn("The response earns full credit because", result.questions[0].score_rationale)

    def test_full_score_rationale_mentions_multiple_satisfied_criteria(self) -> None:
        validator = GradingValidator()
        question = ExamQuestion(
            question_id="3",
            question_text="Give the complete solution with method and conclusion.",
            official_solution="Official solution establishes the setup, supporting argument, and final conclusion.",
            source_pages=[1],
        )
        rubric = RubricQuestion(
            question_id="3",
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            max_marks=6.0,
            criteria=[
                RubricCriterionItem(
                    criterion_id="3.1",
                    description="Required setup",
                    expected_answer="Required setup is shown",
                    marks=2.0,
                    source="official_explicit",
                ),
                RubricCriterionItem(
                    criterion_id="3.2",
                    description="Supporting intermediate justification",
                    expected_answer="Intermediate justification is shown",
                    marks=2.0,
                    source="official_explicit",
                ),
                RubricCriterionItem(
                    criterion_id="3.3",
                    description="Final result and conclusion",
                    expected_answer="Final result and conclusion are shown",
                    marks=2.0,
                    source="official_explicit",
                ),
            ],
        )
        draft = QuestionGradeResult(
            question_id="3",
            awarded_marks=6.0,
            max_marks=6.0,
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            feedback="Complete solution.",
            score_rationale="The response is correct.",
            correct_elements=[],
            missing_or_incorrect_elements=[],
            improvement_suggestions=[],
            evidence_summaries=[
                {"page": 2, "summary": "Visible work shows the required setup and the final conclusion."},
            ],
            visible_evidence=[
                {"page": 2, "evidence": "Student writes the setup, a supporting intermediate argument, and the final conclusion."},
            ],
            confidence=0.95,
            needs_human_review=False,
            criterion_scores=[
                CriterionScore(
                    criterion_id="3.1",
                    awarded=2.0,
                    max=2.0,
                    match_type="exact_match",
                    verification_status="verified",
                    feedback="the required setup",
                    confidence=0.95,
                    needs_human_review=False,
                    evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                ),
                CriterionScore(
                    criterion_id="3.2",
                    awarded=2.0,
                    max=2.0,
                    match_type="exact_match",
                    verification_status="verified",
                    feedback="the supporting intermediate justification",
                    confidence=0.95,
                    needs_human_review=False,
                    evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                ),
                CriterionScore(
                    criterion_id="3.3",
                    awarded=2.0,
                    max=2.0,
                    match_type="exact_match",
                    verification_status="verified",
                    feedback="the final result and conclusion",
                    confidence=0.95,
                    needs_human_review=False,
                    evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                ),
            ],
        )
        answer = StudentAnswer(
            question_id="3",
            status="answered",
            transcription="Student writes the setup, supporting work, and final conclusion.",
            final_answer="Final conclusion is visible.",
            derivation_summary="Supporting intermediate work is visible.",
            uncertain_parts=[],
            student_claims=[],
            source_pages=[2],
            evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.95,
            needs_human_review=False,
        )

        result = validator.run(
            grading_id="demo",
            model_deployment="gpt-5.4-mini",
            duration_ms=1000,
            exam_questions=[question],
            rubric_questions=[rubric],
            student_answers=[answer],
            grading_draft=GradingDraft(questions=[draft]),
        )

        question_result = result.questions[0]
        self.assertIn("The response earns full credit because", question_result.score_rationale)
        self.assertIn("required setup", question_result.score_rationale.lower())
        self.assertIn("supporting intermediate justification", question_result.score_rationale.lower())
        self.assertIn("final result and conclusion", question_result.score_rationale.lower())
        self.assertGreaterEqual(len(question_result.correct_elements), 3)
        self.assertNotIn("Full credit was awarded", question_result.score_rationale)

    def test_contradictory_missing_final_answer_is_removed_when_visible(self) -> None:
        validator = GradingValidator()
        draft = QuestionGradeResult(
            question_id="1",
            awarded_marks=4.0,
            max_marks=5.0,
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            feedback="The main result is visible, but the explanation is brief.",
            score_rationale="The main result is visible, but the supporting explanation is brief.",
            correct_elements=["Correct final answer is present."],
            missing_or_incorrect_elements=["Final answer is missing.", "Explanation is brief."],
            improvement_suggestions=["Show the missing supporting explanation more clearly."],
            evidence_summaries=[],
            visible_evidence=[{"page": 2, "evidence": "Student writes the final feasible range on the page."}],
            confidence=0.8,
            needs_human_review=False,
            criterion_scores=[
                CriterionScore(
                    criterion_id="1.1",
                    awarded=4.0,
                    max=5.0,
                    match_type="partial_credit",
                    verification_status="verified",
                    feedback="the correct final condition, but only brief justification",
                    confidence=0.8,
                    needs_human_review=False,
                    evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                )
            ],
        )
        answer = StudentAnswer(
            question_id="1",
            status="answered",
            transcription="Student writes the final feasible range and a short note.",
            final_answer="Ia - 1 > b > (Ia + 1)/5",
            derivation_summary="Brief supporting explanation only.",
            uncertain_parts=[],
            student_claims=[],
            source_pages=[2],
            evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.8,
            needs_human_review=False,
        )

        result = validator.run(
            grading_id="demo",
            model_deployment="gpt-5.4-mini",
            duration_ms=1000,
            exam_questions=[self.make_exam_question()],
            rubric_questions=[self.make_rubric_question()],
            student_answers=[answer],
            grading_draft=GradingDraft(questions=[draft]),
        )

        question = result.questions[0]
        self.assertNotIn("Final answer is missing.", question.missing_or_incorrect_elements)
        self.assertIn("Explanation is brief.", question.missing_or_incorrect_elements)
        self.assertEqual(question.improvement_suggestions, ["Show the missing supporting explanation more clearly."])

    def test_near_full_score_uses_minor_deduction_language(self) -> None:
        validator = GradingValidator()
        draft = QuestionGradeResult(
            question_id="1",
            awarded_marks=4.5,
            max_marks=5.0,
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            feedback="The solution is mostly right.",
            score_rationale="The response is correct overall.",
            correct_elements=["Correct final answer and supporting setup."],
            missing_or_incorrect_elements=["Major conceptual error in the derivation."],
            improvement_suggestions=["Redo the derivation from the start."],
            evidence_summaries=[],
            visible_evidence=[],
            confidence=0.85,
            needs_human_review=False,
            criterion_scores=[
                CriterionScore(
                    criterion_id="1.1",
                    awarded=4.5,
                    max=5.0,
                    match_type="partial_credit",
                    verification_status="verified",
                    feedback="the correct final condition with only a small verification gap",
                    confidence=0.85,
                    needs_human_review=False,
                    evidence=Evidence(page=1, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                )
            ],
        )
        answer = StudentAnswer(
            question_id="1",
            status="answered",
            transcription="A nearly complete answer is visible.",
            final_answer="Correct final answer",
            derivation_summary="Most of the supporting work is shown.",
            uncertain_parts=[],
            student_claims=[],
            source_pages=[1],
            evidence=Evidence(page=1, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.85,
            needs_human_review=False,
        )

        result = validator.run(
            grading_id="demo",
            model_deployment="gpt-5.4-mini",
            duration_ms=1000,
            exam_questions=[self.make_exam_question()],
            rubric_questions=[self.make_rubric_question()],
            student_answers=[answer],
            grading_draft=GradingDraft(questions=[draft]),
        )

        question = result.questions[0]
        self.assertIn("substantially correct", question.score_rationale.lower())
        self.assertIn("about 0.5 mark", question.score_rationale.lower())
        self.assertFalse(any("major conceptual" in item.lower() for item in question.missing_or_incorrect_elements))

    def test_ambiguous_numeric_rationale_does_not_keep_exact_misread_value(self) -> None:
        validator = GradingValidator()
        question = ExamQuestion(
            question_id="2",
            question_text="Compare the computed values and choose the better option.",
            official_solution="Property A = 338.67, Property B = 586.67, so option B is better.",
            source_pages=[1],
        )
        rubric = RubricQuestion(
            question_id="2",
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            max_marks=5.0,
            criteria=[
                RubricCriterionItem(
                    criterion_id="2.1",
                    description="Correct method and justified comparison",
                    expected_answer="Correct computation and conclusion that option B is better",
                    marks=5.0,
                    source="official_explicit",
                )
            ],
        )
        answer = StudentAnswer(
            question_id="2",
            status="unclear",
            transcription="Student appears to compute the two values and conclude B is better, but one leading digit is faint.",
            final_answer="B is better",
            derivation_summary="The comparison is visible and the value is likely intended as the official result up to rounding.",
            uncertain_parts=["One leading digit in the displayed decimal is partially unclear."],
            student_claims=[
                StudentClaim(
                    type="comparison",
                    content="Student writes that B is greater and therefore better.",
                    evidence_page=2,
                )
            ],
            source_pages=[2],
            evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.55,
            needs_human_review=False,
        )
        draft = QuestionGradeResult(
            question_id="2",
            awarded_marks=4.0,
            max_marks=5.0,
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            feedback="One value was transcribed as 38.67, so credit was reduced.",
            score_rationale="The student writes 38.67 instead of the official value, although the method and conclusion are correct.",
            correct_elements=["Correct conclusion that B is better."],
            missing_or_incorrect_elements=["One displayed value is partially unclear."],
            improvement_suggestions=["Write the displayed values more clearly."],
            evidence_summaries=[],
            visible_evidence=[],
            confidence=0.55,
            needs_human_review=False,
            criterion_scores=[
                CriterionScore(
                    criterion_id="2.1",
                    awarded=4.0,
                    max=5.0,
                    match_type="partial_credit",
                    verification_status="partial",
                    feedback="the correct method and conclusion, with one unclear displayed value",
                    confidence=0.55,
                    needs_human_review=False,
                    evidence=Evidence(page=2, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                )
            ],
        )

        result = validator.run(
            grading_id="demo",
            model_deployment="gpt-5.4-mini",
            duration_ms=1000,
            exam_questions=[question],
            rubric_questions=[rubric],
            student_answers=[answer],
            grading_draft=GradingDraft(questions=[draft]),
        )

        question_result = result.questions[0]
        self.assertNotIn("38.67", question_result.score_rationale)
        self.assertIn("partially unclear", question_result.score_rationale)
        self.assertIn("about 1 mark", question_result.score_rationale.lower())

    def test_internal_review_language_is_removed_from_final_fields(self) -> None:
        validator = GradingValidator()
        draft = QuestionGradeResult(
            question_id="1",
            awarded_marks=4.0,
            max_marks=5.0,
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            feedback="The previous score was too harsh because the visible conclusion matches the rubric.",
            score_rationale="The previous score was too harsh because the visible conclusion matches the rubric.",
            correct_elements=["Restored credit for the correct final conclusion."],
            missing_or_incorrect_elements=["One displayed quantity is partially unclear."],
            improvement_suggestions=["Clarify the displayed quantity that limited the earlier grading."],
            evidence_summaries=[{"page": 1, "summary": "Adjusted from a lower mark after recheck because the visible conclusion matches the rubric."}],
            visible_evidence=[{"page": 1, "evidence": "Recheck shows the student writes a final conclusion consistent with the required result."}],
            confidence=0.7,
            needs_human_review=False,
            criterion_scores=[
                CriterionScore(
                    criterion_id="1.1",
                    awarded=4.0,
                    max=5.0,
                    match_type="partial_credit",
                    verification_status="verified",
                    feedback="the correct final conclusion with one small verification gap",
                    confidence=0.7,
                    needs_human_review=False,
                    evidence=Evidence(page=1, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                )
            ],
        )
        answer = StudentAnswer(
            question_id="1",
            status="answered",
            transcription="Student gives a final conclusion and one displayed value.",
            final_answer="Final conclusion is visible.",
            derivation_summary="A short supporting explanation is visible.",
            uncertain_parts=["One displayed quantity is partially unclear."],
            student_claims=[
                StudentClaim(
                    type="conclusion",
                    content="Student writes a final conclusion consistent with the required result.",
                    evidence_page=1,
                )
            ],
            source_pages=[1],
            evidence=Evidence(page=1, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.7,
            needs_human_review=False,
        )

        result = validator.run(
            grading_id="demo",
            model_deployment="gpt-5.4-mini",
            duration_ms=1000,
            exam_questions=[self.make_exam_question()],
            rubric_questions=[self.make_rubric_question()],
            student_answers=[answer],
            grading_draft=GradingDraft(questions=[draft]),
        )

        question_result = result.questions[0]
        combined_text = " ".join(
            [
                question_result.score_rationale,
                *question_result.correct_elements,
                *question_result.missing_or_incorrect_elements,
                *question_result.improvement_suggestions,
                *(item.evidence for item in question_result.visible_evidence),
                *(item.summary for item in question_result.evidence_summaries),
            ]
        ).lower()
        for forbidden in (
            "previous score",
            "too harsh",
            "restored credit",
            "earlier grading",
            "recheck",
            "repair",
            "withheld for verification",
            "worst-case digit reading",
        ):
            self.assertNotIn(forbidden, combined_text)
        self.assertIn("correct final conclusion", " ".join(question_result.correct_elements).lower())

    def test_normalize_existing_result_cleans_recheck_language_after_update(self) -> None:
        validator = GradingValidator()
        answer = StudentAnswer(
            question_id="1",
            status="answered",
            transcription="Student writes the final result and a short derivation.",
            final_answer="Final result is visible.",
            derivation_summary="A short derivation is visible.",
            uncertain_parts=["One displayed quantity is partially unclear."],
            student_claims=[
                StudentClaim(
                    type="formula",
                    content="Student writes the final result and a short derivation.",
                    evidence_page=1,
                )
            ],
            source_pages=[1],
            evidence=Evidence(page=1, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
            confidence=0.72,
            needs_human_review=False,
        )
        result = GradingResult(
            grading_id="demo",
            status="completed",
            model_deployment="gpt-5.4-mini",
            total_score=4.0,
            max_score=5.0,
            duration_ms=1000,
            questions=[
                QuestionGradeResult(
                    question_id="1",
                    awarded_marks=4.0,
                    max_marks=5.0,
                    rubric_source="official_explicit",
                    max_marks_source="official_explicit",
                    feedback="Adjusted from a lower mark after recheck.",
                    score_rationale="Adjusted from a lower mark after recheck because the visible work is consistent with the rubric.",
                    correct_elements=["Restored credit for the valid final result."],
                    missing_or_incorrect_elements=["One displayed quantity remains partially unclear."],
                    improvement_suggestions=["Clarify the displayed quantity that limited the previous score."],
                    evidence_summaries=[],
                    visible_evidence=[{"page": 1, "evidence": "Student writes the final result and a short derivation."}],
                    confidence=0.72,
                    needs_human_review=True,
                    criterion_scores=[
                        CriterionScore(
                            criterion_id="1.1",
                            awarded=4.0,
                            max=5.0,
                            match_type="partial_credit",
                            verification_status="verified",
                            feedback="the valid final result with one small verification gap",
                            confidence=0.72,
                            needs_human_review=False,
                            evidence=Evidence(page=1, bbox=[0, 0, 100, 100], crop_path=None, zoomed=False),
                        )
                    ],
                )
            ],
        )

        normalized = validator.normalize_existing_result(
            result=result,
            exam_questions=[self.make_exam_question()],
            rubric_questions=[self.make_rubric_question()],
            student_answers=[answer],
        )

        question_result = normalized.questions[0]
        combined_text = " ".join(
            [
                question_result.score_rationale,
                *question_result.correct_elements,
                *question_result.missing_or_incorrect_elements,
                *question_result.improvement_suggestions,
            ]
        ).lower()
        for forbidden in ("adjusted from", "recheck", "previous score", "restored credit"):
            self.assertNotIn(forbidden, combined_text)
        self.assertEqual(normalized.total_score, question_result.awarded_marks)


class EquivalenceSeedTests(SimpleTestCase):
    def test_equivalence_seeds_include_compact_and_normalized_math_variants(self) -> None:
        rubric = RubricQuestion(
            question_id="1",
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            max_marks=5.0,
            criteria=[
                RubricCriterionItem(
                    criterion_id="1.1",
                    description="Equivalent inequality",
                    expected_answer="b ≥ 1/2 and Ia - 1 > b > (Ia + 1)/5",
                    marks=5.0,
                    source="official_explicit",
                )
            ],
        )

        seeds = build_equivalence_seeds([rubric])
        self.assertIn("b>=1/2andIa-1>b>(Ia+1)/5", seeds["1"])
        self.assertIn("b >= 1/2 and ia - 1 > b > (ia + 1)/5", seeds["1"])
        self.assertIn("0.5", seeds["1"])

    def test_equivalence_seeds_include_decimal_variants_for_fractions(self) -> None:
        rubric = RubricQuestion(
            question_id="2",
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            max_marks=5.0,
            criteria=[
                RubricCriterionItem(
                    criterion_id="2.1",
                    description="Equivalent fraction or decimal",
                    expected_answer="I_A = 245/2 and I_B = 731/4",
                    marks=5.0,
                    source="official_explicit",
                )
            ],
        )

        seeds = build_equivalence_seeds([rubric])
        self.assertIn("122.5", seeds["2"])
        self.assertIn("182.75", seeds["2"])

    def test_equivalence_seeds_include_multiple_rounding_precisions_for_fractions(self) -> None:
        rubric = RubricQuestion(
            question_id="3",
            rubric_source="official_explicit",
            max_marks_source="official_explicit",
            max_marks=1.0,
            criteria=[
                RubricCriterionItem(
                    criterion_id="3.1",
                    description="Equivalent numeric value",
                    expected_answer="1/3",
                    marks=1.0,
                    source="official_explicit",
                )
            ],
        )

        seeds = build_equivalence_seeds([rubric])
        self.assertIn("0.3", seeds["3"])
        self.assertIn("0.33", seeds["3"])
        self.assertIn("0.333", seeds["3"])
        self.assertIn("0.3333", seeds["3"])
