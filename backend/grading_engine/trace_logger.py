from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from grading_engine.runtime import GradingSettings


def append_run_trace(settings: GradingSettings, run_id: str, event: str, **fields: Any) -> None:
    path = settings.artifacts_root / run_id / "debug_trace.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str) + "\n")
