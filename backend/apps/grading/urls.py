from __future__ import annotations

from django.urls import re_path

from apps.grading.views import (
    BatchGradingCreateView,
    GradingCancelView,
    GradingDetailView,
    GradingExportPdfView,
    GradingListCreateView,
    GradingOverrideView,
    GradingStatusView,
)


urlpatterns = [
    re_path(r"^$", GradingListCreateView.as_view()),
    re_path(r"^batch/?$", BatchGradingCreateView.as_view()),
    re_path(r"^export/?$", GradingExportPdfView.as_view()),
    re_path(
        r"^(?P<grading_id>[0-9A-Fa-f-]{36})/?$",
        GradingDetailView.as_view(),
    ),
    re_path(
        r"^(?P<grading_id>[0-9A-Fa-f-]{36})/status/?$",
        GradingStatusView.as_view(),
    ),
    re_path(
        r"^(?P<grading_id>[0-9A-Fa-f-]{36})/cancel/?$",
        GradingCancelView.as_view(),
    ),
    re_path(
        r"^(?P<grading_id>[0-9A-Fa-f-]{36})/override/?$",
        GradingOverrideView.as_view(),
    ),
]
