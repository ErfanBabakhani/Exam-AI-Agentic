from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from apps.grading.serializers import HealthSerializer

@extend_schema(
    tags=["system"],
    summary="Health check",
    auth=[],
    responses={200: HealthSerializer},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health(_: object) -> JsonResponse:
    azure_configured = all(
        [
            settings.AZURE_OPENAI_API_KEY,
            settings.AZURE_OPENAI_ENDPOINT,
            settings.AZURE_OPENAI_DEPLOYMENT,
            settings.AZURE_OPENAI_API_VERSION,
        ]
    )
    deployment_locked = settings.AZURE_OPENAI_DEPLOYMENT in (
        None,
        settings.AZURE_OPENAI_ALLOWED_DEPLOYMENT,
    )
    return JsonResponse(
        {
            "status": "ok",
            "service": settings.APP_NAME,
            "azure_configured": azure_configured,
            "deployment_locked": deployment_locked,
        }
    )


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="api-redoc"),
    re_path(r"^api/health/?$", health),
    re_path(r"^api/auth(?:/|$)", include("apps.accounts.urls")),
    re_path(r"^api/gradings(?:/|$)", include("apps.grading.urls")),
]

handler404 = "common.api.json_not_found"
handler500 = "common.api.json_server_error"
