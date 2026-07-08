from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from grading_engine.exam_cache import ExamAnalysisCache
from grading_engine.runtime import GradingSettings
from grading_engine.schemas import (
    ExamQuestion,
    ExamUnderstandingResult,
    RubricCriterionItem,
    RubricQuestion,
    RubricResult,
)


class ExamCacheTests(SimpleTestCase):
    def make_settings(self, storage_root: Path) -> GradingSettings:
        return GradingSettings(
            storage_root=storage_root,
            uploads_root=storage_root / "uploads",
            artifacts_root=storage_root / "artifacts",
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

    def test_exam_analysis_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = self.make_settings(root)
            cache = ExamAnalysisCache(settings)
            exam_pdf = root / "exam.pdf"
            exam_pdf.write_bytes(b"%PDF-1.4 fake content")

            exam = ExamUnderstandingResult(
                questions=[
                    ExamQuestion(
                        question_id="1",
                        question_text="Q1",
                        official_solution="A1",
                        source_pages=[1],
                        has_diagram_or_formula=False,
                        explicit_max_marks_found=False,
                        explicit_max_marks=None,
                    )
                ]
            )
            rubric = RubricResult(
                questions=[
                    RubricQuestion(
                        question_id="1",
                        rubric_source="system_default",
                        max_marks_source="system_default",
                        max_marks=5.0,
                        criteria=[
                            RubricCriterionItem(
                                criterion_id="1.1",
                                description="demo",
                                expected_answer="A1",
                                marks=5.0,
                                source="system_default",
                            )
                        ],
                    )
                ]
            )

            cache.save(
                exam_pdf_path=exam_pdf,
                default_question_max_marks=5.0,
                exam=exam,
                rubric=rubric,
            )

            loaded = cache.load(exam_pdf_path=exam_pdf, default_question_max_marks=5.0)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.exam.model_dump(mode="json"), exam.model_dump(mode="json"))
            self.assertEqual(loaded.rubric.model_dump(mode="json"), rubric.model_dump(mode="json"))
