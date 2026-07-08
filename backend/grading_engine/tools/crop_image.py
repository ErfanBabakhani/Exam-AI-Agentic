from __future__ import annotations

from pathlib import Path

from PIL import Image


def crop_image(source_path: Path, destination_path: Path, bbox: list[int]) -> Path:
    with Image.open(source_path) as image:
        cropped = image.crop(tuple(bbox))
        if destination_path.suffix.lower() in {".jpg", ".jpeg"}:
            cropped.convert("RGB").save(destination_path, format="JPEG", quality=86, optimize=True)
        else:
            cropped.save(destination_path, optimize=True)
    return destination_path
