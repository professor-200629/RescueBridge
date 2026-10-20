"""Live-lab arming record.

The live lab is opt-in: the person arms it from a terminal for a named session, a short duration, and an
exact set of allowed fault types. While armed, observations from the real Windows helper are labelled
"Controlled Live Lab" instead of "Real Windows". The record lives in the lab directory, which no agent or
MCP tool can read.
"""

from __future__ import annotations

import json
import time
from typing import Any

from rescuebridge.config import Settings

ALLOWED_SCOPES = ("mouse", "audio", "workpad")
MAX_MINUTES = 30


def arming_path(settings: Settings) -> Any:
    return settings.lab_dir / "arming.json"


def read_arming(settings: Settings) -> dict[str, Any] | None:
    try:
        rec = json.loads(arming_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def is_armed(settings: Settings, now: float | None = None) -> bool:
    rec = read_arming(settings)
    if not rec or rec.get("disarmed_at"):
        return False
    return float(rec.get("expires_at", 0)) > (now if now is not None else time.time())
