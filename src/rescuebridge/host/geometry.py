"""Rectangle math for off-screen window analysis (physical pixels, per-monitor DPI aware)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

Rect = tuple[int, int, int, int]  # left, top, right, bottom


def area(r: Rect) -> int:
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def intersect(a: Rect, b: Rect) -> Rect:
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def visible_fraction(window: Rect, monitors: list[Rect]) -> float:
    """Fraction of the window rectangle that lies on any monitor (monitors do not overlap)."""
    total = area(window)
    if total == 0:
        return 0.0
    covered = sum(area(intersect(window, m)) for m in monitors)
    return round(min(1.0, covered / total), 4)


def caption_reachable(window: Rect, work_areas: list[Rect], dpi: int = 96) -> bool:
    """True when a usable part of the title-bar strip is inside a monitor work area.

    This is a geometric heuristic only: it does not prove a person can see or use the window.
    """
    strip_h = max(8, round(30 * dpi / 96))
    strip = (window[0], window[1], window[2], window[1] + strip_h)
    min_w = round(80 * dpi / 96)
    for wa in work_areas:
        inter = intersect(strip, wa)
        if inter[2] - inter[0] >= min_w and inter[3] - inter[1] >= strip_h // 2:
            return True
    return False


def monitors_fingerprint(monitors: list[dict[str, Any]]) -> str:
    canon = sorted(
        (tuple(m["rect"]), tuple(m["work"]), bool(m["primary"]), int(m.get("dpi", 96))) for m in monitors
    )
    return hashlib.sha256(json.dumps(canon).encode()).hexdigest()[:32]


def placement_on(work: Rect, window: Rect, max_fraction: float = 0.9) -> Rect:
    """Center the window on a work area, keeping its size when it fits (else shrink to max_fraction)."""
    ww, wh = window[2] - window[0], window[3] - window[1]
    aw, ah = work[2] - work[0], work[3] - work[1]
    w = min(ww, int(aw * max_fraction)) if ww > aw * max_fraction else ww
    h = min(wh, int(ah * max_fraction)) if wh > ah * max_fraction else wh
    w, h = max(w, 320), max(h, 240)
    left = work[0] + (aw - w) // 2
    top = work[1] + (ah - h) // 2
    return (left, top, left + w, top + h)
