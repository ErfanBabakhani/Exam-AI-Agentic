from __future__ import annotations

from copy import deepcopy

from rest_framework import serializers

from apps.grading.models import GradingRun
from apps.grading.services import get_progress_snapshot, normalize_public_status


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()
    service = serializers.CharField()
    azure_configured = serializers.BooleanField()
    deployment_locked = serializers.BooleanField()


class ProgressSnapshotMixin:
    def _snapshot(self, obj: GradingRun) -> dict:
        cache_name = "_progress_snapshot_cache"
        cache = getattr(self, cache_name, {})
        if obj.id not in cache:
            cache[obj.id] = get_progress_snapshot(obj)
            setattr(self, cache_name, cache)
        return cache[obj.id]

    def _public_status(self, obj: GradingRun) -> str:
        return normalize_public_status(obj.status)

    def _normalized_result(self, obj: GradingRun):
        if obj.result_json is None:
            return None
        payload = deepcopy(obj.result_json)
        payload["status"] = normalize_public_status(payload.get("status"))
        return payload


class GradingRunSummarySerializer(ProgressSnapshotMixin, serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    stage = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()
    status_message = serializers.SerializerMethodField()
    started_at = serializers.SerializerMethodField()
    completed_at = serializers.SerializerMethodField()

    class Meta:
        model = GradingRun
        fields = (
            "id",
            "status",
            "stage",
            "progress_percent",
            "status_message",
            "exam_filename",
            "student_filename",
            "total_score",
            "max_score",
            "duration_ms",
            "model_deployment",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
        )

    def get_status(self, obj: GradingRun):
        return self._public_status(obj)

    def get_stage(self, obj: GradingRun):
        return self._snapshot(obj)["stage"]

    def get_progress_percent(self, obj: GradingRun):
        return self._snapshot(obj)["progress_percent"]

    def get_status_message(self, obj: GradingRun):
        return self._snapshot(obj).get("status_message")

    def get_started_at(self, obj: GradingRun):
        return self._snapshot(obj).get("started_at")

    def get_completed_at(self, obj: GradingRun):
        return self._snapshot(obj).get("completed_at")


class GradingRunDetailSerializer(ProgressSnapshotMixin, serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()
    stage = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()
    status_message = serializers.SerializerMethodField()
    started_at = serializers.SerializerMethodField()
    completed_at = serializers.SerializerMethodField()

    class Meta:
        model = GradingRun
        fields = (
            "id",
            "status",
            "stage",
            "progress_percent",
            "status_message",
            "exam_filename",
            "student_filename",
            "total_score",
            "max_score",
            "model_deployment",
            "duration_ms",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "error_message",
            "created_at",
            "updated_at",
            "started_at",
            "completed_at",
            "result",
        )

    def get_status(self, obj: GradingRun):
        return self._public_status(obj)

    def get_result(self, obj: GradingRun):
        return self._normalized_result(obj)

    def get_stage(self, obj: GradingRun):
        return self._snapshot(obj)["stage"]

    def get_progress_percent(self, obj: GradingRun):
        return self._snapshot(obj)["progress_percent"]

    def get_status_message(self, obj: GradingRun):
        return self._snapshot(obj).get("status_message")

    def get_started_at(self, obj: GradingRun):
        return self._snapshot(obj).get("started_at")

    def get_completed_at(self, obj: GradingRun):
        return self._snapshot(obj).get("completed_at")


class GradingRunStatusSerializer(ProgressSnapshotMixin, serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    stage = serializers.SerializerMethodField()
    progress_percent = serializers.SerializerMethodField()
    status_message = serializers.SerializerMethodField()
    started_at = serializers.SerializerMethodField()
    completed_at = serializers.SerializerMethodField()

    class Meta:
        model = GradingRun
        fields = (
            "id",
            "status",
            "stage",
            "progress_percent",
            "status_message",
            "error_message",
            "started_at",
            "completed_at",
        )

    def get_status(self, obj: GradingRun):
        return self._public_status(obj)

    def get_stage(self, obj: GradingRun):
        return self._snapshot(obj)["stage"]

    def get_progress_percent(self, obj: GradingRun):
        return self._snapshot(obj)["progress_percent"]

    def get_status_message(self, obj: GradingRun):
        return self._snapshot(obj).get("status_message")

    def get_started_at(self, obj: GradingRun):
        return self._snapshot(obj).get("started_at")

    def get_completed_at(self, obj: GradingRun):
        return self._snapshot(obj).get("completed_at")


class TeacherOverrideRequestSerializer(serializers.Serializer):
    question_id = serializers.CharField()
    new_score = serializers.FloatField(min_value=0)
    reason = serializers.CharField(min_length=3, max_length=2000)


class TeacherOverrideResponseSerializer(serializers.Serializer):
    grading_id = serializers.UUIDField()
    question_id = serializers.CharField()
    new_score = serializers.FloatField()
    total_score = serializers.FloatField()
    updated_at = serializers.DateTimeField()


class BulkDeleteGradingsRequestSerializer(serializers.Serializer):
    grading_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
    )


class BulkDeleteGradingsResponseSerializer(serializers.Serializer):
    deleted_count = serializers.IntegerField()
    deleted_ids = serializers.ListField(child=serializers.UUIDField())


class GradingExportRequestSerializer(serializers.Serializer):
    grading_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
    )


class GradingCreateRequestSerializer(serializers.Serializer):
    exam_pdf = serializers.FileField()
    student_pdf = serializers.FileField()


class BatchGradingCreateRequestSerializer(serializers.Serializer):
    exam_pdf = serializers.FileField()
    student_pdfs = serializers.ListField(
        child=serializers.FileField(),
        allow_empty=False,
    )


class BatchGradingCreateResponseSerializer(serializers.Serializer):
    queue_size = serializers.IntegerField()
    runs = GradingRunDetailSerializer(many=True)


class GradingCancellationResponseSerializer(serializers.Serializer):
    grading_id = serializers.UUIDField()
    status = serializers.CharField()
    canceled_at = serializers.DateTimeField()
