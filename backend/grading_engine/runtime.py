from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


@dataclass(frozen=True)
class GradingSettings:
    storage_root: Path
    uploads_root: Path
    artifacts_root: Path
    azure_openai_api_key: str | None
    azure_openai_endpoint: str | None
    azure_openai_deployment: str | None
    azure_openai_api_version: str
    azure_openai_allowed_deployment: str
    azure_openai_input_usd_per_1m_tokens: float | None
    azure_openai_output_usd_per_1m_tokens: float | None
    default_question_max_marks: float
    hard_timeout_seconds: int
    llm_timeout_seconds: float
    pdf_render_dpi: int
    pdf_max_page_dimension: int
    pdf_max_zoomed_dimension: int
    max_upload_size_mb: int
    inspection_batch_size: int
    max_images_per_request: int
    mock_grading_enabled: bool

    @property
    def azure_configured(self) -> bool:
        return all(
            [
                self.azure_openai_api_key,
                self.azure_openai_endpoint,
                self.azure_openai_deployment,
                self.azure_openai_api_version,
            ]
        )

    def validate_azure_configuration(self) -> None:
        if not self.azure_configured:
            raise RuntimeError(
                "Azure OpenAI is not fully configured. Set AZURE_OPENAI_API_KEY, "
                "AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, and AZURE_OPENAI_API_VERSION."
            )
        if self.azure_openai_deployment != self.azure_openai_allowed_deployment:
            raise RuntimeError(
                f"Invalid Azure deployment configured. Use only {self.azure_openai_allowed_deployment!r}."
            )


def get_grading_settings() -> GradingSettings:
    return GradingSettings(
        storage_root=settings.STORAGE_ROOT,
        uploads_root=settings.UPLOADS_ROOT,
        artifacts_root=settings.ARTIFACTS_ROOT,
        azure_openai_api_key=settings.AZURE_OPENAI_API_KEY,
        azure_openai_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        azure_openai_deployment=settings.AZURE_OPENAI_DEPLOYMENT,
        azure_openai_api_version=settings.AZURE_OPENAI_API_VERSION,
        azure_openai_allowed_deployment=settings.AZURE_OPENAI_ALLOWED_DEPLOYMENT,
        azure_openai_input_usd_per_1m_tokens=settings.AZURE_OPENAI_INPUT_USD_PER_1M_TOKENS,
        azure_openai_output_usd_per_1m_tokens=settings.AZURE_OPENAI_OUTPUT_USD_PER_1M_TOKENS,
        default_question_max_marks=settings.DEFAULT_QUESTION_MAX_MARKS,
        hard_timeout_seconds=settings.HARD_TIMEOUT_SECONDS,
        llm_timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        pdf_render_dpi=settings.PDF_RENDER_DPI,
        pdf_max_page_dimension=settings.PDF_MAX_PAGE_DIMENSION,
        pdf_max_zoomed_dimension=settings.PDF_MAX_ZOOMED_DIMENSION,
        max_upload_size_mb=settings.MAX_UPLOAD_SIZE_MB,
        inspection_batch_size=settings.INSPECTION_BATCH_SIZE,
        max_images_per_request=settings.MAX_IMAGES_PER_REQUEST,
        mock_grading_enabled=settings.ALLOW_MOCK_GRADING,
    )
