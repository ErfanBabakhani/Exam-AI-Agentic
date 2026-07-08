from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
from django.test import SimpleTestCase
from pydantic import BaseModel

from grading_engine.azure_client import AzureGraderClient
from grading_engine.runtime import GradingSettings


class DummyResponse(BaseModel):
    answer: str


class AzureClientPayloadTests(SimpleTestCase):
    def make_settings(self) -> GradingSettings:
        return GradingSettings(
            storage_root=Path("/tmp/storage"),
            uploads_root=Path("/tmp/storage/uploads"),
            artifacts_root=Path("/tmp/storage/artifacts"),
            azure_openai_api_key="test-key",
            azure_openai_endpoint="https://example.openai.azure.com/",
            azure_openai_deployment="gpt-5.4-mini",
            azure_openai_api_version="2024-12-01-preview",
            azure_openai_allowed_deployment="gpt-5.4-mini",
            azure_openai_input_usd_per_1m_tokens=None,
            azure_openai_output_usd_per_1m_tokens=None,
            default_question_max_marks=5.0,
            hard_timeout_seconds=120,
            llm_timeout_seconds=45.0,
            pdf_render_dpi=200,
            pdf_max_page_dimension=1800,
            pdf_max_zoomed_dimension=1800,
            max_upload_size_mb=20,
            inspection_batch_size=5,
            max_images_per_request=10,
            mock_grading_enabled=False,
        )

    def test_parse_payload_omits_parallel_tool_calls_without_tools(self) -> None:
        client = AzureGraderClient(self.make_settings())
        payload = client._build_parse_payload(
            messages=[{"role": "user", "content": "Hello"}],
            response_model=DummyResponse,
            timeout_seconds=None,
        )
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["top_p"], 1)
        self.assertNotIn("parallel_tool_calls", payload)
        self.assertNotIn("tools", payload)
        self.assertNotIn("tool_choice", payload)

    def test_parse_payload_includes_tool_fields_only_when_tools_exist(self) -> None:
        client = AzureGraderClient(self.make_settings())
        payload = client._build_parse_payload(
            messages=[{"role": "user", "content": "Hello"}],
            response_model=DummyResponse,
            timeout_seconds=12.0,
            tools=[{"type": "function", "function": {"name": "demo", "parameters": {}}}],
        )
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertTrue(payload["parallel_tool_calls"])
        self.assertIn("tools", payload)

    def test_http_timeout_is_more_resilient_than_llm_timeout(self) -> None:
        client = AzureGraderClient(self.make_settings())

        self.assertIsInstance(client._http_timeout, httpx.Timeout)
        self.assertEqual(client._http_timeout.read, 60.0)
        self.assertEqual(client._http_timeout.connect, 20.0)
        self.assertEqual(client._http_timeout.write, 20.0)
        self.assertEqual(client._http_timeout.pool, 20.0)
