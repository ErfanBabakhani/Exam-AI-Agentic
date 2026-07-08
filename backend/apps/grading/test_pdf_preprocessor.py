from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase
from PIL import Image

from grading_engine.runtime import GradingSettings
from grading_engine.tools.zoom_image import zoom_image


FITZ_AVAILABLE = importlib.util.find_spec("fitz") is not None
if FITZ_AVAILABLE:
    from grading_engine.pdf_preprocessor import PDFPreprocessor, PageSignals


@skipUnless(FITZ_AVAILABLE, "PyMuPDF is required for PDF preprocessing tests.")
class PdfPreprocessorSizingTests(SimpleTestCase):
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

    def test_oversized_sample_page_is_capped_during_render(self) -> None:
        root = Path(__file__).resolve().parents[3]
        sample_pdf = root / "docs" / "samples" / "studentAnswers" / "4.pdf"

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self.make_settings(Path(temp_dir))
            processed = PDFPreprocessor(settings).process(
                run_id="sample-run",
                document_kind="student",
                pdf_path=sample_pdf,
            )

            self.assertGreaterEqual(processed.page_count, 1)
            self.assertTrue(
                any(
                    page.page_type in {"SCANNED_PAGE", "DARK_SCANNED_PAGE"}
                    and max(page.width, page.height) <= settings.pdf_max_page_dimension
                    for page in processed.pages
                )
            )

    def test_zoom_image_caps_large_output_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source = temp_root / "source.png"
            destination = temp_root / "zoomed.png"

            Image.new("RGB", (2800, 1800), color="white").save(source)
            zoom_image(source, destination, scale=1.5, max_dimension=1800)

            with Image.open(destination) as image:
                self.assertLessEqual(max(image.size), 1800)

    def test_dark_image_without_text_is_classified_as_dark_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self.make_settings(Path(temp_dir))
            preprocessor = PDFPreprocessor(settings)
            image = Image.new("RGB", (1200, 1600), color=(20, 20, 20))
            signals = preprocessor._analyze_page(image=image, text="")
            self.assertEqual(signals.page_type, "DARK_SCANNED_PAGE")

    def test_text_rich_page_is_classified_as_text_page(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self.make_settings(Path(temp_dir))
            preprocessor = PDFPreprocessor(settings)
            image = Image.new("RGB", (1000, 1400), color="white")
            text = "Question text. " * 80
            signals = preprocessor._analyze_page(image=image, text=text)
            self.assertEqual(signals.page_type, "TEXT_PAGE")

    def test_low_contrast_handwritten_page_prefers_png_with_contrast_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self.make_settings(Path(temp_dir))
            preprocessor = PDFPreprocessor(settings)
            image = Image.new("RGB", (1600, 2000), color=(244, 244, 240))
            signals = PageSignals(
                page_type="MIXED_PAGE",
                text_length=120,
                mean_brightness=210.0,
                dark_pixel_ratio=0.04,
                contrast_stddev=18.0,
                image_heavy=True,
                needs_visual_context=True,
                low_contrast=True,
                thin_handwriting=True,
            )

            optimized = preprocessor._optimize_image(image=image, signals=signals)

            self.assertEqual(optimized.image_format, "PNG")
            self.assertTrue(optimized.contrast_normalized)
            self.assertFalse(optimized.dark_inversion_applied)
