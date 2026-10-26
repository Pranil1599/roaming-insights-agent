"""Append-only JSONL audit trail of reviewer decisions and executed queries."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

AUDIT_PATH = Path(os.getenv("AUDIT_LOG", Path(__file__).resolve().parent.parent / "logs" / "audit.jsonl"))


def log_event(event: str, **fields) -> None:
    if os.getenv("AUDIT_DISABLED") == "1":
        return
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
