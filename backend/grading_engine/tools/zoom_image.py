from __future__ import annotations

from pathlib import Path

from PIL import Image


def _fit_within(width: int, height: int, max_dimension: int) -> tuple[int, int]:
    if max(width, height) <= max_dimension:
        return width, height
    ratio = max_dimension / max(width, height)
    return max(1, int(width * ratio)), max(1, int(height * ratio))


def zoom_image(source_path: Path, destination_path: Path, *, scale: float, max_dimension: int | None = None) -> Path:
    with Image.open(source_path) as image:
        target_width = max(1, int(image.width * scale))
        target_height = max(1, int(image.height * scale))
        if max_dimension is not None:
            target_width, target_height = _fit_within(target_width, target_height, max_dimension)
        resized = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
        if destination_path.suffix.lower() in {".jpg", ".jpeg"}:
            resized.convert("RGB").save(destination_path, format="JPEG", quality=86, optimize=True)
        else:
            resized.save(destination_path, optimize=True)
    return destination_path
