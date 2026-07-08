from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import fitz
from PIL import Image, ImageEnhance, ImageOps, ImageStat

from grading_engine.runtime import GradingSettings
from grading_engine.trace_logger import append_run_trace


PageType = Literal["TEXT_PAGE", "MIXED_PAGE", "SCANNED_PAGE", "DARK_SCANNED_PAGE"]


@dataclass(slots=True)
class PageSignals:
    page_type: PageType
    text_length: int
    mean_brightness: float
    dark_pixel_ratio: float
    contrast_stddev: float
    image_heavy: bool
    needs_visual_context: bool
    low_contrast: bool
    thin_handwriting: bool


@dataclass(slots=True)
class OptimizedPageImage:
    image: Image.Image
    image_format: Literal["JPEG", "PNG"]
    image_bytes: bytes
    contrast_normalized: bool
    dark_inversion_applied: bool


@dataclass(slots=True)
class DocumentPage:
    page_number: int
    text: str
    image_path: Path
    thumbnail_path: Path
    width: int
    height: int
    original_width: int
    original_height: int
    original_image_bytes: int
    page_type: PageType
    text_length: int
    mean_brightness: float
    dark_pixel_ratio: float
    contrast_stddev: float
    image_bytes: int
    thumbnail_bytes: int
    image_format: Literal["JPEG", "PNG"]
    contrast_normalized: bool
    dark_inversion_applied: bool
    needs_visual_context: bool


@dataclass(slots=True)
class ProcessedDocument:
    pdf_path: Path
    pages: list[DocumentPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def all_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text)

    def as_page_payload(self, *, max_chars_per_page: int = 5000) -> list[dict[str, object]]:
        return [
            {
                "page_number": page.page_number,
                "page_type": page.page_type,
                "text": page.text[:max_chars_per_page],
                "needs_visual_context": page.needs_visual_context,
            }
            for page in self.pages
        ]


class PDFPreprocessor:
    def __init__(self, settings: GradingSettings) -> None:
        self._settings = settings

    def process(self, *, run_id: str, document_kind: str, pdf_path: Path) -> ProcessedDocument:
        output_dir = self._settings.artifacts_root / run_id / document_kind
        output_dir.mkdir(parents=True, exist_ok=True)

        append_run_trace(
            self._settings,
            run_id,
            "document.processing_started",
            document_kind=document_kind,
            pdf_path=str(pdf_path),
        )

        pages: list[DocumentPage] = []
        with fitz.open(pdf_path) as document:
            for index, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                matrix = self._matrix_for_page(page, text_length=len(text))
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                original_width = pixmap.width
                original_height = pixmap.height
                original_image_bytes = len(pixmap.samples)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                signals = self._analyze_page(image=image, text=text)
                optimized = self._optimize_image(image=image, signals=signals)
                image_format = optimized.image_format
                image_suffix = ".jpg" if image_format == "JPEG" else ".png"
                image_path = output_dir / f"page_{index}{image_suffix}"
                image_path.write_bytes(optimized.image_bytes)
                thumbnail_path = output_dir / f"page_{index}_thumb.jpg"
                self._create_thumbnail(optimized.image, thumbnail_path)
                page_record = DocumentPage(
                    page_number=index,
                    text=text,
                    image_path=image_path,
                    thumbnail_path=thumbnail_path,
                    width=optimized.image.width,
                    height=optimized.image.height,
                    original_width=original_width,
                    original_height=original_height,
                    original_image_bytes=original_image_bytes,
                    page_type=signals.page_type,
                    text_length=signals.text_length,
                    mean_brightness=signals.mean_brightness,
                    dark_pixel_ratio=signals.dark_pixel_ratio,
                    contrast_stddev=signals.contrast_stddev,
                    image_bytes=image_path.stat().st_size,
                    thumbnail_bytes=thumbnail_path.stat().st_size,
                    image_format=image_format,
                    contrast_normalized=optimized.contrast_normalized,
                    dark_inversion_applied=optimized.dark_inversion_applied,
                    needs_visual_context=signals.needs_visual_context,
                )
                pages.append(page_record)
                append_run_trace(
                    self._settings,
                    run_id,
                    "document.page_processed",
                    document_kind=document_kind,
                    page_number=index,
                    page_type=page_record.page_type,
                    page_classification=page_record.page_type.lower().replace("_page", "").replace("_", "-"),
                    text_length=page_record.text_length,
                    mean_brightness=round(page_record.mean_brightness, 2),
                    dark_pixel_ratio=round(page_record.dark_pixel_ratio, 4),
                    contrast_stddev=round(page_record.contrast_stddev, 2),
                    original_dimensions=[page_record.original_width, page_record.original_height],
                    final_dimensions=[page_record.width, page_record.height],
                    original_image_bytes=page_record.original_image_bytes,
                    image_bytes=page_record.image_bytes,
                    thumbnail_bytes=page_record.thumbnail_bytes,
                    image_format=page_record.image_format,
                    contrast_normalized=page_record.contrast_normalized,
                    dark_inversion_applied=page_record.dark_inversion_applied,
                    image_path=str(page_record.image_path),
                    thumbnail_path=str(page_record.thumbnail_path),
                )

        append_run_trace(
            self._settings,
            run_id,
            "document.processing_completed",
            document_kind=document_kind,
            page_count=len(pages),
        )
        return ProcessedDocument(pdf_path=pdf_path, pages=pages)

    def _matrix_for_page(self, page: fitz.Page, *, text_length: int) -> fitz.Matrix:
        base_scale = self._settings.pdf_render_dpi / 72
        rect = page.rect
        max_points = max(rect.width, rect.height, 1)
        capped_scale = self._target_max_dimension(text_length=text_length) / max_points
        scale = min(base_scale, capped_scale)
        return fitz.Matrix(scale, scale)

    def _target_max_dimension(self, *, text_length: int) -> int:
        if text_length < 400:
            return min(2200, max(self._settings.pdf_max_page_dimension, 2000))
        return self._settings.pdf_max_page_dimension

    def _analyze_page(self, *, image: Image.Image, text: str) -> PageSignals:
        text_length = len(text)
        probe = image.convert("L")
        probe.thumbnail((256, 256))
        stat = ImageStat.Stat(probe)
        mean_brightness = float(stat.mean[0])
        contrast_stddev = float(stat.stddev[0])
        pixels = list(probe.getdata())
        total_pixels = max(len(pixels), 1)
        dark_pixel_ratio = sum(1 for pixel in pixels if pixel < 60) / total_pixels
        image_heavy = text_length < 140 or (text_length < 320 and max(image.size) >= 1400)
        low_contrast = contrast_stddev < 40 or (mean_brightness > 150 and dark_pixel_ratio < 0.08 and text_length < 220)
        thin_handwriting = text_length < 260 and dark_pixel_ratio < 0.13
        if mean_brightness < 95 and dark_pixel_ratio > 0.45 and text_length < 200:
            page_type: PageType = "DARK_SCANNED_PAGE"
        elif text_length < 90:
            page_type = "SCANNED_PAGE"
        elif text_length > 900 and not image_heavy and dark_pixel_ratio < 0.25:
            page_type = "TEXT_PAGE"
        else:
            page_type = "MIXED_PAGE"
        return PageSignals(
            page_type=page_type,
            text_length=text_length,
            mean_brightness=mean_brightness,
            dark_pixel_ratio=dark_pixel_ratio,
            contrast_stddev=contrast_stddev,
            image_heavy=image_heavy,
            needs_visual_context=page_type != "TEXT_PAGE",
            low_contrast=low_contrast,
            thin_handwriting=thin_handwriting,
        )

    def _optimize_image(self, *, image: Image.Image, signals: PageSignals) -> OptimizedPageImage:
        optimized = image.convert("RGB")
        contrast_normalized = False
        dark_inversion_applied = False
        if signals.page_type in {"SCANNED_PAGE", "DARK_SCANNED_PAGE"}:
            optimized = self._trim_margins(optimized, dark_background=signals.page_type == "DARK_SCANNED_PAGE")
        if signals.page_type == "DARK_SCANNED_PAGE":
            optimized = ImageOps.grayscale(optimized)
            optimized = ImageOps.invert(optimized)
            optimized = ImageOps.autocontrast(optimized, cutoff=1)
            optimized = optimized.convert("RGB")
            contrast_normalized = True
            dark_inversion_applied = True
        elif signals.page_type == "SCANNED_PAGE":
            optimized = ImageOps.grayscale(optimized)
            optimized = ImageOps.autocontrast(optimized, cutoff=0.5)
            optimized = optimized.convert("RGB")
            contrast_normalized = True
        elif signals.low_contrast:
            optimized = ImageOps.autocontrast(optimized, cutoff=0.5)
            contrast_normalized = True
        if signals.low_contrast or signals.thin_handwriting:
            optimized = ImageEnhance.Contrast(optimized).enhance(1.12 if signals.low_contrast else 1.06)
            contrast_normalized = True
        max_dimension = self._target_max_dimension(text_length=signals.text_length)
        if max(optimized.size) > max_dimension:
            optimized.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        image_format = self._image_format_for_page(image=optimized, signals=signals)
        image_bytes = self._encode_image(optimized, image_format=image_format, jpeg_quality=94 if image_format == "JPEG" else None)
        return OptimizedPageImage(
            image=optimized,
            image_format=image_format,
            image_bytes=image_bytes,
            contrast_normalized=contrast_normalized,
            dark_inversion_applied=dark_inversion_applied,
        )

    @staticmethod
    def _trim_margins(image: Image.Image, *, dark_background: bool) -> Image.Image:
        grayscale = image.convert("L")
        if dark_background:
            mask = grayscale.point(lambda value: 255 if value > 35 else 0)
        else:
            mask = grayscale.point(lambda value: 255 if value < 245 else 0)
        bbox = mask.getbbox()
        if bbox is None:
            return image
        left, top, right, bottom = bbox
        padding = 24
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(image.width, right + padding)
        bottom = min(image.height, bottom + padding)
        if right - left < image.width * 0.45 or bottom - top < image.height * 0.45:
            return image
        return image.crop((left, top, right, bottom))

    def _png_is_within_budget(self, image: Image.Image, *, byte_limit: int) -> bool:
        png_bytes = self._encode_image(image, image_format="PNG", jpeg_quality=None)
        return len(png_bytes) <= byte_limit

    def _image_format_for_page(self, *, image: Image.Image, signals: PageSignals) -> Literal["JPEG", "PNG"]:
        if signals.page_type == "TEXT_PAGE":
            if self._png_is_within_budget(image, byte_limit=3_500_000):
                return "PNG"
            return "JPEG"
        if signals.page_type == "MIXED_PAGE":
            if signals.low_contrast or signals.thin_handwriting:
                if self._png_is_within_budget(image, byte_limit=4_000_000):
                    return "PNG"
                return "JPEG"
            if self._png_is_within_budget(image, byte_limit=3_200_000):
                return "PNG"
            return "JPEG"
        if signals.low_contrast or signals.thin_handwriting:
            if self._png_is_within_budget(image, byte_limit=4_000_000):
                return "PNG"
            return "JPEG"
        if signals.page_type == "DARK_SCANNED_PAGE" and self._png_is_within_budget(image, byte_limit=3_400_000):
            return "PNG"
        return "JPEG"

    @staticmethod
    def _encode_image(image: Image.Image, *, image_format: Literal["JPEG", "PNG"], jpeg_quality: int | None) -> bytes:
        buffer = io.BytesIO()
        if image_format == "JPEG":
            image.convert("RGB").save(buffer, format="JPEG", quality=jpeg_quality or 92, optimize=True)
        else:
            image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    @staticmethod
    def _create_thumbnail(image: Image.Image, thumbnail_path: Path) -> None:
        thumbnail = image.copy()
        thumbnail.thumbnail((1100, 1500), Image.Resampling.LANCZOS)
        thumbnail.convert("RGB").save(thumbnail_path, format="JPEG", quality=88, optimize=True)

    @staticmethod
    def to_json(payload: dict[str, object]) -> str:
        return json.dumps(payload, ensure_ascii=False)
