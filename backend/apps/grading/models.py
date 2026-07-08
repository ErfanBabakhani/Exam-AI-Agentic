from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class GradingRun(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="grading_runs")
    status = models.CharField(max_length=32, default="running")
    exam_filename = models.CharField(max_length=255)
    exam_storage_path = models.TextField()
    student_filename = models.CharField(max_length=255)
    student_storage_path = models.TextField()
    model_deployment = models.CharField(max_length=128, null=True, blank=True)
    total_score = models.FloatField(null=True, blank=True)
    max_score = models.FloatField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    cost_usd = models.FloatField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    result_json = models.JSONField(null=True, blank=True)


class Question(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grading_run = models.ForeignKey(GradingRun, on_delete=models.CASCADE, related_name="questions")
    question_id = models.CharField(max_length=64)
    question_text = models.TextField()
    official_solution = models.TextField()
    source_pages = models.JSONField(null=True, blank=True)
    max_marks = models.FloatField()
    rubric_source = models.CharField(max_length=64)
    max_marks_source = models.CharField(max_length=64)


class RubricCriterion(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="rubric_criteria")
    criterion_id = models.CharField(max_length=64)
    description = models.TextField()
    expected_answer = models.TextField()
    marks = models.FloatField()
    source = models.CharField(max_length=64)


class StudentAnswer(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grading_run = models.ForeignKey(GradingRun, on_delete=models.CASCADE, related_name="student_answers")
    question_id = models.CharField(max_length=64)
    page_number = models.IntegerField(null=True, blank=True)
    bbox = models.JSONField(null=True, blank=True)
    transcription = models.TextField()
    final_answer = models.TextField(null=True, blank=True)
    derivation_summary = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=32)
    uncertainty_flags = models.JSONField(null=True, blank=True)
    needs_human_review = models.BooleanField(default=False)


class QuestionGrade(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grading_run = models.ForeignKey(GradingRun, on_delete=models.CASCADE, related_name="question_grades")
    question_id = models.CharField(max_length=64)
    awarded_marks = models.FloatField()
    max_marks = models.FloatField()
    feedback = models.TextField()
    confidence = models.FloatField(null=True, blank=True)
    needs_human_review = models.BooleanField(default=False)
    override_applied = models.BooleanField(default=False)


class CriterionGrade(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_grade = models.ForeignKey(QuestionGrade, on_delete=models.CASCADE, related_name="criterion_grades")
    criterion_id = models.CharField(max_length=64)
    awarded = models.FloatField()
    max = models.FloatField()
    match_type = models.CharField(max_length=64)
    verification_status = models.CharField(max_length=64)
    feedback = models.TextField()
    confidence = models.FloatField(null=True, blank=True)
    needs_human_review = models.BooleanField(default=False)


class EvidenceRegion(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_grade = models.ForeignKey(
        QuestionGrade,
        on_delete=models.CASCADE,
        related_name="evidence_regions",
        null=True,
        blank=True,
    )
    criterion_grade = models.ForeignKey(
        CriterionGrade,
        on_delete=models.CASCADE,
        related_name="evidence_regions",
        null=True,
        blank=True,
    )
    question_id = models.CharField(max_length=64)
    page_number = models.IntegerField()
    bbox = models.JSONField(null=True, blank=True)
    crop_path = models.TextField(null=True, blank=True)
    zoomed = models.BooleanField(default=False)


class TeacherOverride(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grading_run = models.ForeignKey(GradingRun, on_delete=models.CASCADE, related_name="teacher_overrides")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teacher_overrides")
    question_id = models.CharField(max_length=64)
    old_score = models.FloatField()
    new_score = models.FloatField()
    reason = models.TextField()


class ModelCall(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    grading_run = models.ForeignKey(GradingRun, on_delete=models.CASCADE, related_name="model_calls")
    stage = models.CharField(max_length=64)
    deployment = models.CharField(max_length=128)
    prompt_tokens = models.IntegerField(null=True, blank=True)
    completion_tokens = models.IntegerField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    cost_usd = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=32)
    error_message = models.TextField(null=True, blank=True)
