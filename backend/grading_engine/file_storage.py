from __future__ import annotations

from pathlib import Path

from grading_engine.runtime import GradingSettings


class FileStorageService:
    def __init__(self, settings: GradingSettings) -> None:
        self._settings = settings

    def save_upload(self, run_id: str, label: str, upload) -> Path:
        run_dir = self._settings.uploads_root / run_id
        return self.save_upload_to_directory(run_dir, label, upload)

    def save_upload_to_directory(self, directory: Path, label: str, upload) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        filename = getattr(upload, "name", None) or f"{label}.pdf"
        filename = filename.replace("/", "_").replace("\\", "_")
        destination = directory / f"{label}_{filename}"
        total_size = 0
        with destination.open("wb") as handle:
            for chunk in upload.chunks():
                total_size += len(chunk)
                if total_size > self._settings.max_upload_size_mb * 1024 * 1024:
                    raise RuntimeError(f"{label} upload exceeds the configured size limit")
                handle.write(chunk)
        return destination
