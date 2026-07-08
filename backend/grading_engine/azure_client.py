from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Generic, TypeVar

import httpx
from openai import AsyncAzureOpenAI
from pydantic import BaseModel

from grading_engine.cost_logger import ModelCallTrace, compute_cost_usd
from grading_engine.runtime import GradingSettings
from grading_engine.trace_logger import append_run_trace


ResponseT = TypeVar("ResponseT", bound=BaseModel)


@dataclass(slots=True)
class StructuredCompletion(Generic[ResponseT]):
    parsed: ResponseT
    trace: ModelCallTrace


class AzureGraderClient:
    def __init__(self, settings: GradingSettings) -> None:
        settings.validate_azure_configuration()
        self._settings = settings
        self._http_timeout = self._build_http_timeout(settings.llm_timeout_seconds)
        self._client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
            max_retries=0,
            timeout=self._http_timeout,
        )
        self.deployment = settings.azure_openai_deployment or settings.azure_openai_allowed_deployment

    @property
    def settings(self) -> GradingSettings:
        return self._settings

    @staticmethod
    def _build_http_timeout(llm_timeout_seconds: float) -> httpx.Timeout:
        # Keep the grading job capped by the existing hard timeout, while letting
        # the HTTP transport tolerate slower connects and transient network stalls.
        read_timeout = max(llm_timeout_seconds, 60.0)
        return httpx.Timeout(
            connect=min(read_timeout, 20.0),
            read=read_timeout,
            write=min(read_timeout, 20.0),
            pool=min(read_timeout, 20.0),
        )

    @staticmethod
    def _summarize_messages(messages: list[dict[str, Any]]) -> dict[str, int]:
        image_count = 0
        text_chars = 0
        for message in messages:
            content = message.get("content")
            if isinstance(content, str):
                text_chars += len(content)
                continue
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "image_url":
                        image_count += 1
                    elif item.get("type") == "text":
                        text_chars += len(item.get("text", ""))
        return {"image_count": image_count, "text_chars": text_chars}

    def _build_parse_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        response_model: type[ResponseT],
        timeout_seconds: float | None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.deployment,
            "messages": messages,
            "response_format": response_model,
            "max_completion_tokens": 4000,
            "timeout": timeout_seconds or self._settings.llm_timeout_seconds,
            "temperature": 0,
            "top_p": 1,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True
        return payload

    async def complete_structured(
        self,
        *,
        stage: str,
        run_id: str,
        system_prompt: str,
        response_model: type[ResponseT],
        user_text: str | None = None,
        user_content: list[dict] | None = None,
        timeout_seconds: float | None = None,
    ) -> StructuredCompletion[ResponseT]:
        if user_text is None and user_content is None:
            raise ValueError("Either user_text or user_content must be provided")

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        if user_content is not None:
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": user_text})

        started = perf_counter()
        payload = self._build_parse_payload(
            messages=messages,
            response_model=response_model,
            timeout_seconds=timeout_seconds,
        )
        message_summary = self._summarize_messages(messages)
        append_run_trace(
            self._settings,
            run_id,
            "azure.request_started",
            stage=stage,
            timeout_seconds=payload["timeout"],
            image_count=message_summary["image_count"],
            text_chars=message_summary["text_chars"],
            message_count=len(messages),
        )
        try:
            completion = await self._client.beta.chat.completions.parse(**payload)
        except Exception as exc:
            append_run_trace(
                self._settings,
                run_id,
                "azure.request_failed",
                stage=stage,
                duration_ms=int((perf_counter() - started) * 1000),
                error=str(exc),
            )
            raise
        duration_ms = int((perf_counter() - started) * 1000)
        prompt_tokens = completion.usage.prompt_tokens if completion.usage else None
        completion_tokens = completion.usage.completion_tokens if completion.usage else None
        cost_usd = compute_cost_usd(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            settings=self._settings,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError(f"No structured payload was returned for stage {stage!r}")
        append_run_trace(
            self._settings,
            run_id,
            "azure.request_completed",
            stage=stage,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return StructuredCompletion(
            parsed=parsed,
            trace=ModelCallTrace(
                stage=stage,
                deployment=self.deployment,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration_ms=duration_ms,
                cost_usd=cost_usd,
                status="ok",
                error_message=None,
                run_id=run_id,
            ),
        )
