"""Controlled live lab: opt-in fault injection on REAL Windows with a recorded clean state.

Rules enforced here:
- Nothing happens unless the person armed the lab for a named session, a short duration (<= 30 min) and an
  explicit scope (mouse, audio, workpad).
- Only these reversible faults exist: temporary (non-persistent) mouse-button swap, mute (optionally volume 0)
  of the default playback endpoint, and moving RescueBridge's OWN WorkPad window off-screen.
- The snapshot of the clean state and the ground-truth manifest live in the lab directory, which no MCP tool
  or agent can read.
- Restore puts back the snapshot only where the current state is still the injected fault (or otherwise
  differs in the faulted direction); it reports anything it did not touch. Cleanup after power loss or a
  killed process is NOT guaranteed: a sign-out resets the temporary mouse swap; audio and WorkPad must be
  restored with `rescuebridge lab restore` or by hand.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from rescuebridge.config import Settings
from rescuebridge.lab.arming import ALLOWED_SCOPES, MAX_MINUTES, arming_path, read_arming

FAULT_SCOPE = {"mouse-swap": "mouse", "audio-mute": "audio", "audio-mute-silent": "audio", "workpad-offscreen": "workpad"}


class LabError(Exception):
    pass


@dataclass
class LiveOps:
    """Direct real-Windows access for the lab harness only (never reachable from MCP tools)."""

    ops: Any

    @classmethod
    def create(cls, settings: Settings) -> LiveOps:
        from rescuebridge.host.windows_ops import WindowsOps, enable_per_monitor_dpi_awareness

        enable_per_monitor_dpi_awareness()
        return cls(WindowsOps(settings.workpad_dir, settings.data_dir / "clicktest"))

    def snapshot(self) -> dict[str, Any]:
        snap: dict[str, Any] = {"taken_at": time.time()}
        snap["mouse"] = self.ops.mouse_state()
        eps = self.ops.audio_endpoints()
        d = next((e for e in eps if e.is_default), None)
        snap["audio"] = {"endpoint_id": d.id, "name": d.name, "muted": d.muted, "volume_scalar": d.volume_scalar} if d else None
        wp = self.ops.workpad_status()
        if wp:
            rects = self.ops.window_rect(wp["hwnd"])
            snap["workpad"] = {"hwnd": wp["hwnd"], "pid": wp["pid"], "rect": list(rects[0]) if rects else None,
                               "text_sha256": wp["text_sha256"]}
        else:
            snap["workpad"] = None
        return snap


def _write(settings: Settings, rec: dict[str, Any]) -> None:
    from rescuebridge.host.pipe import write_private_file

    write_private_file(arming_path(settings), json.dumps(rec, indent=2).encode("utf-8"))


def arm(settings: Settings, live: LiveOps, session: str, minutes: int, allow: list[str]) -> dict[str, Any]:
    if not session.strip() or len(session) > 60:
        raise LabError("session name must be 1-60 characters")
    if not 1 <= minutes <= MAX_MINUTES:
        raise LabError(f"duration must be 1-{MAX_MINUTES} minutes")
    bad = [a for a in allow if a not in ALLOWED_SCOPES]
    if bad or not allow:
        raise LabError(f"allowed scopes are {', '.join(ALLOWED_SCOPES)}; got {allow}")
    current = read_arming(settings)
    if current and not current.get("disarmed_at") and current.get("expires_at", 0) > time.time():
        raise LabError("the lab is already armed; restore/disarm it first")
    now = time.time()
    rec = {"session": session.strip(), "armed_at": now, "expires_at": now + minutes * 60, "allow": allow,
           "snapshot": live.snapshot(), "injected": [], "disarmed_at": None, "restores": []}
    _write(settings, rec)
    return rec


def _require_armed(settings: Settings, scope: str) -> dict[str, Any]:
    rec = read_arming(settings)
    if not rec or rec.get("disarmed_at"):
        raise LabError("the live lab is not armed")
    if rec["expires_at"] < time.time():
        raise LabError("the arming expired; restore and arm again")
    if scope not in rec["allow"]:
        raise LabError(f"'{scope}' is not in the armed scope {rec['allow']}")
    return rec


def inject(settings: Settings, live: LiveOps, fault: str) -> dict[str, Any]:
    scope = FAULT_SCOPE.get(fault)
    if scope is None:
        raise LabError(f"unknown fault {fault}")
    rec = _require_armed(settings, scope)
    entry: dict[str, Any] = {"fault": fault, "at": time.time()}
    if fault == "mouse-swap":
        live.ops.inject_mouse_swap_temporary(True)  # SwapMouseButton: not saved; sign-out resets it
        entry["state_after"] = live.ops.mouse_state()
    elif fault in ("audio-mute", "audio-mute-silent"):
        snap = rec["snapshot"].get("audio")
        if not snap:
            raise LabError("no default playback endpoint was recorded when the lab was armed")
        live.ops.set_audio(snap["endpoint_id"], True, 0.0 if fault == "audio-mute-silent" else None)
        entry["endpoint_name"] = snap["name"]
    elif fault == "workpad-offscreen":
        wp = live.ops.workpad_status()
        if not wp:
            raise LabError("WorkPad is not running: start it with `rescuebridge workpad` first")
        rects = live.ops.window_rect(wp["hwnd"])
        if not rects:
            raise LabError("WorkPad window not found")
        # Found in a live run: "moving" a minimized WorkPad creates no off-screen fault (RescueBridge rightly reports
        # minimized windows as unsupported), so the test would silently test nothing. Refuse instead.
        if any(w.hwnd == wp["hwnd"] and (w.minimized or not w.visible) for w in live.ops.windows()):
            raise LabError("WorkPad is minimized or hidden, so moving it would not create an off-screen fault. "
                           "Restore it first (click it in the taskbar), then inject again.")
        r = rects[0]
        mons = live.ops.monitors()
        right = max(m.rect[2] for m in mons)
        target = (right + 400, r[1], right + 400 + (r[2] - r[0]), r[3])
        live.ops.move_window(wp["hwnd"], target)
        entry["moved_to"] = list(target)
        if rec["snapshot"].get("workpad") is None or rec["snapshot"]["workpad"].get("hwnd") != wp["hwnd"]:
            rec["snapshot"]["workpad"] = {"hwnd": wp["hwnd"], "pid": wp["pid"], "rect": list(r),
                                          "text_sha256": wp["text_sha256"]}
    rec["injected"].append(entry)
    _write(settings, rec)
    return entry


def restore(settings: Settings, live: LiveOps, reason: str = "manual") -> dict[str, Any]:
    rec = read_arming(settings)
    if not rec:
        raise LabError("no lab arming record found")
    snap = rec["snapshot"]
    report: dict[str, Any] = {"at": time.time(), "reason": reason, "actions": [], "left_alone": []}
    injected = {e["fault"] for e in rec.get("injected", [])}
    if "mouse" in rec["allow"] and snap.get("mouse"):
        cur = live.ops.mouse_state()
        if bool(cur["swap_effective"]) != bool(snap["mouse"]["swap_effective"]):
            if "mouse-swap" in injected:
                live.ops.inject_mouse_swap_temporary(bool(snap["mouse"]["swap_effective"]))
                report["actions"].append("mouse: restored the effective button mapping")
            else:
                report["left_alone"].append("mouse: differs from snapshot but the lab did not change it")
    if "audio" in rec["allow"] and snap.get("audio"):
        a = snap["audio"]
        eps = {e.id: e for e in live.ops.audio_endpoints()}
        cur_ep = eps.get(a["endpoint_id"])
        if cur_ep is None:
            report["left_alone"].append("audio: the recorded endpoint is no longer active")
        elif cur_ep.muted != a["muted"] or abs(cur_ep.volume_scalar - a["volume_scalar"]) > 0.02:
            if injected & {"audio-mute", "audio-mute-silent"}:
                live.ops.set_audio(a["endpoint_id"], a["muted"], a["volume_scalar"])
                report["actions"].append(f"audio: restored '{a['name']}' mute/volume")
            else:
                report["left_alone"].append("audio: differs from snapshot but the lab did not change it")
    if "workpad" in rec["allow"] and snap.get("workpad") and "workpad-offscreen" in injected:
        w = snap["workpad"]
        ident = live.ops.window_identity(w["hwnd"])
        rects = live.ops.window_rect(w["hwnd"]) if ident.exists and ident.pid == w["pid"] else None
        if rects and w.get("rect"):
            from rescuebridge.host import geometry

            frac = geometry.visible_fraction(rects[1], [m.rect for m in live.ops.monitors()])
            if frac < 0.5:
                live.ops.move_window(w["hwnd"], tuple(w["rect"]))
                report["actions"].append("workpad: moved back to its recorded position")
        elif not rects:
            report["left_alone"].append("workpad: window no longer exists")
    rec.setdefault("restores", []).append(report)
    _write(settings, rec)
    return report


def disarm(settings: Settings, live: LiveOps) -> dict[str, Any]:
    report = restore(settings, live, "disarm")
    rec = read_arming(settings) or {}
    rec["disarmed_at"] = time.time()
    _write(settings, rec)
    return report


def watchdog(settings: Settings, live: LiveOps, poll_s: float = 2.0) -> dict[str, Any]:
    """Foreground watchdog: restores the clean state when the arming expires (or on Ctrl+C)."""
    try:
        while True:
            rec = read_arming(settings)
            if not rec or rec.get("disarmed_at"):
                return {"stopped": "not armed"}
            left = rec["expires_at"] - time.time()
            if left <= 0:
                return disarm(settings, live)
            print(f"\rlive lab '{rec['session']}' armed ({', '.join(rec['allow'])}); auto-restore in {int(left)} s  ",
                  end="", flush=True)
            time.sleep(min(poll_s, max(0.2, left)))
    except KeyboardInterrupt:
        print()
        return disarm(settings, live)
