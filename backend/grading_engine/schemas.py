from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictBaseModel):
    page: int
    bbox: list[int] | None = None
    crop_path: str | None = None
    zoomed: bool = False


class CriterionScore(StrictBaseModel):
    criterion_id: str
    awarded: float
    max: float
    match_type: Literal[
        "exact_match",
        "equivalent_variant",
        "novel_valid_solution",
        "partial_credit",
        "missing",
    ]
    verification_status: Literal["verified", "partial", "inconclusive"]
    feedback: str
    confidence: float | None = None
    needs_human_review: bool = False
    evidence: Evidence | None = None


class EvidenceSummary(StrictBaseModel):
    page: int | None = None
    summary: str


class VisibleEvidenceItem(StrictBaseModel):
    page: int | None = None
    evidence: str


class QuestionGradeResult(StrictBaseModel):
    question_id: str
    awarded_marks: float
    max_marks: float
    rubric_source: Literal["official_explicit", "inferred_from_official_solution", "system_default"]
    max_marks_source: Literal["official_explicit", "inferred_from_official_solution", "system_default"]
    feedback: str
    score_rationale: str = ""
    correct_elements: list[str] = Field(default_factory=list)
    missing_or_incorrect_elements: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    evidence_summaries: list[EvidenceSummary] = Field(default_factory=list)
    visible_evidence: list[VisibleEvidenceItem] = Field(default_factory=list)
    confidence: float | None = None
    needs_human_review: bool = False
    criterion_scores: list[CriterionScore] = Field(default_factory=list)


class GradingResult(StrictBaseModel):
    grading_id: str
    status: Literal["pending", "processing", "completed", "failed", "canceled"]
    model_deployment: str
    total_score: float
    max_score: float
    duration_ms: int
    questions: list[QuestionGradeResult]


class ExamQuestion(StrictBaseModel):
    question_id: str
    question_text: str
    official_solution: str
    source_pages: list[int]
    has_diagram_or_formula: bool = False
    explicit_max_marks_found: bool = False
    explicit_max_marks: float | None = None


class ExamUnderstandingResult(StrictBaseModel):
    questions: list[ExamQuestion]


class RubricCriterionItem(StrictBaseModel):
    criterion_id: str
    description: str
    expected_answer: str
    marks: float
    source: Literal["official_explicit", "inferred_from_official_solution", "system_default"]


class RubricQuestion(StrictBaseModel):
    question_id: str
    rubric_source: Literal["official_explicit", "inferred_from_official_solution", "system_default"]
    max_marks_source: Literal["official_explicit", "inferred_from_official_solution", "system_default"]
    max_marks: float
    criteria: list[RubricCriterionItem]


class RubricResult(StrictBaseModel):
    questions: list[RubricQuestion]


class AnswerLocation(StrictBaseModel):
    question_id: str
    status: Literal["answered", "missing", "unclear"]
    page_number: int | None = None
    page_numbers: list[int] = Field(default_factory=list)
    region_hint: Literal["top", "middle", "bottom", "full_page", "unknown"] = "unknown"
    summary: str
    confidence: float | None = None
    needs_human_review: bool = False


class LocationBatchResult(StrictBaseModel):
    locations: list[AnswerLocation]


class StudentClaim(StrictBaseModel):
    type: str
    content: str
    evidence_page: int | None = None


class StudentAnswer(StrictBaseModel):
    question_id: str
    status: Literal["answered", "missing", "unclear"]
    transcription: str
    final_answer: str | None = None
    derivation_summary: str | None = None
    uncertain_parts: list[str] = Field(default_factory=list)
    student_claims: list[StudentClaim] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    evidence: Evidence | None = None
    confidence: float | None = None
    needs_human_review: bool = False


class StudentInspectionResult(StrictBaseModel):
    answers: list[StudentAnswer]


class GradingDraft(StrictBaseModel):
    questions: list[QuestionGradeResult]


class LowScoreRecheckQuestion(StrictBaseModel):
    question_id: str
    supports_existing_score: bool = False
    awarded_marks: float
    score_rationale: str
    correct_elements: list[str] = Field(default_factory=list)
    missing_or_incorrect_elements: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    visible_evidence: list[VisibleEvidenceItem] = Field(default_factory=list)
    confidence: float | None = None
    needs_human_review: bool = False


class LowScoreRecheckResult(StrictBaseModel):
    questions: list[LowScoreRecheckQuestion]
