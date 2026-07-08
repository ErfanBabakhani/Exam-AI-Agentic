from __future__ import annotations

from dataclasses import dataclass

from grading_engine.runtime import GradingSettings


@dataclass(slots=True)
class ModelCallTrace:
    stage: str
    deployment: str
    prompt_tokens: int | None
    completion_tokens: int | None
    duration_ms: int | None
    cost_usd: float | None
    status: str
    error_message: str | None
    run_id: str


def compute_cost_usd(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    settings: GradingSettings,
) -> float | None:
    if (
        prompt_tokens is None
        or completion_tokens is None
        or settings.azure_openai_input_usd_per_1m_tokens is None
        or settings.azure_openai_output_usd_per_1m_tokens is None
    ):
        return None
    return round(
        (prompt_tokens / 1_000_000) * settings.azure_openai_input_usd_per_1m_tokens
        + (completion_tokens / 1_000_000) * settings.azure_openai_output_usd_per_1m_tokens,
        6,
    )
