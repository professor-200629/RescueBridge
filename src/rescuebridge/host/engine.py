"""HelperEngine: the only component that invokes SystemOps.

Enforces, independently of the backend:
- the fixed request schema (`protocol.parse_request`),
- an execution fence: writes carrying an authority revision older than the fence are rejected,
- serialized writes (one at a time),
- precondition checks immediately before each change (observed state, endpoint identity, window target
  identity, monitor configuration),
- short-lived helper-issued window target references bound to HWND + process identity.

Stop/fence admission. Every mutation receives an admission context that the OS layer enters in the execution
context that performs the change (for WindowsOps: on its worker thread, after any queue wait and preparatory COM
calls), immediately before the mutating call, and leaves when that call returns. Entering and fence advancement
take the same lock, so they are strictly ordered: a fence acknowledged before admission makes entry refuse; an
operation admitted before the fence is reported in the acknowledgement as in flight (its OS call may finish).
An operation stays in flight until its OS call has actually returned, even if the request that started it timed
out. Operations that are only queued or still checking preconditions are never reported as in flight; they are
listed as `pending_operation_ids` and will be refused at admission. When a request gives up before its operation
was admitted, the operation is cancelled atomically and can never be admitted later.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from rescuebridge.host import geometry
from rescuebridge.host.protocol import (
    ExecuteRequest,
    FenceRequest,
    HealthRequest,
    MoveWindowParams,
    ObserveRequest,
    PlayToneParams,
    SetAudioParams,
    SetMouseParams,
    ShowClickTestParams,
    err,
    ok,
    parse_request,
)
from rescuebridge.host.system_ops import (
    Admit,
    OpsError,
    OpsTimeout,
    RawWindow,
    SystemOps,
    ToneExpectation,
    tone_expectation_problem,
)

log = logging.getLogger("rescuebridge.helper")

SHELL_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow"})
TARGET_REF_TTL_S = 15 * 60
VOLUME_TOLERANCE = 0.02
# Operation phases inside the helper (only ADMITTED means "the OS call may be underway").
QUEUED, OBSERVING, ADMITTED, COMPLETED, NOT_ADMITTED, FENCED_OUT = (
    "QUEUED", "OBSERVING", "ADMITTED", "COMPLETED", "NOT_ADMITTED", "REJECTED_BY_FENCE")
_PHASE_HISTORY = 64


class Fenced(OpsError):
    """Raised by the admission gate: the operation's authority is older than the fence."""

    def __init__(self, fence: int, revision: int) -> None:
        super().__init__("FENCED", "authority revision is older than the helper fence (Stop or revocation)")
        self.fence = fence
        self.revision = revision


class Cancelled(OpsError):
    """Raised by the admission gate: the request for this operation already ended (e.g. timed out) before it was
    admitted, so it must never start. Raised on the worker thread; nobody waits for it any more."""

    def __init__(self) -> None:
        super().__init__("OUTCOME_UNKNOWN", "request ended before admission; cancelled")


@dataclass
class TargetRef:
    ref: str
    hwnd: int
    pid: int
    process_create_time: int
    exe: str
    window_class: str
    expires_at: float


class HelperEngine:
    def __init__(self, ops: SystemOps, *, clock: Any = time.time) -> None:
        self.ops = ops
        self.mode = ops.mode
        self._clock = clock
        self._fence = 0
        self._fence_lock = threading.Lock()  # guards _fence, _in_os and _phases; never held across an OS call
        self._write_lock = threading.Lock()
        self._in_os: set[str] = set()  # admitted and their OS call has not returned yet (may outlive the request)
        self._phases: dict[str, str] = {}
        self._refs: dict[str, TargetRef] = {}
        self._refs_lock = threading.Lock()
        self.started_at = int(self._clock() * 1000)

    # ------------------------------------------------------------------------------------------
    def handle(self, raw: Any) -> dict[str, Any]:
        try:
            req = parse_request(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            return err(self.mode, "BAD_REQUEST", f"rejected by fixed schema: {type(exc).__name__}")
        try:
            if isinstance(req, HealthRequest):
                return ok(self.mode, self._health())
            if isinstance(req, ObserveRequest):
                return self._observe(req)
            if isinstance(req, FenceRequest):
                return ok(self.mode, self._set_fence(req.revision))
            if isinstance(req, ExecuteRequest):
                return self._execute(req)
        except OpsError as exc:
            return err(self.mode, exc.code, exc.message)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover - defensive: never leak tracebacks over IPC
            log.exception("helper internal error")
            return err(self.mode, "OS_ERROR", f"internal error: {type(exc).__name__}")
        return err(self.mode, "BAD_REQUEST", "unhandled op")

    # ------------------------------------------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        with self._fence_lock:
            fence, in_os = self._fence, sorted(self._in_os)
            pending = [op for op, ph in self._phases.items() if ph in (QUEUED, OBSERVING)]
        return {"mode": self.mode, "fence": fence, "pid": os.getpid(), "in_flight_operation_id": in_os[0] if in_os else None,
                "in_flight_operation_ids": in_os, "pending_operation_ids": pending, "started_at": self.started_at}

    def _set_fence(self, revision: int) -> dict[str, Any]:
        with self._fence_lock:  # same lock as admission: the two are strictly ordered
            self._fence = max(self._fence, revision)
            fence, in_os = self._fence, sorted(self._in_os)
            pending = [op for op, ph in self._phases.items() if ph in (QUEUED, OBSERVING)]
        # Only an operation admitted before this point may still change state (its OS call may finish, even after
        # its request timed out). Queued or precondition-checking operations are refused when they reach admission.
        return {"fence": fence, "in_flight_operation_id": in_os[0] if in_os else None, "in_flight_operation_ids": in_os,
                "in_flight_phase": ADMITTED if in_os else None, "pending_operation_ids": pending,
                "acknowledged_at": int(self._clock() * 1000)}

    def _set_phase(self, operation_id: str, phase: str) -> None:
        """Caller holds _fence_lock."""
        self._phases[operation_id] = phase
        while len(self._phases) > _PHASE_HISTORY:
            oldest = next((op for op in self._phases if op not in self._in_os), None)
            if oldest is None:
                break
            self._phases.pop(oldest)

    def _admission_gate(self, revision: int, operation_id: str) -> Admit:
        @contextmanager
        def admission() -> Iterator[None]:
            with self._fence_lock:
                if self._phases.get(operation_id) != OBSERVING:  # its request already ended: never start it now
                    raise Cancelled()
                if revision < self._fence:
                    self._set_phase(operation_id, FENCED_OUT)
                    raise Fenced(self._fence, revision)
                self._in_os.add(operation_id)
                self._set_phase(operation_id, ADMITTED)
            try:
                yield  # the OS call runs here, in the caller's execution context
            finally:
                with self._fence_lock:  # only now is the call over, whether or not anyone still waits for it
                    self._in_os.discard(operation_id)
                    self._set_phase(operation_id, COMPLETED)

        return admission

    def _uncertain_outcome(self, operation_id: str, exc: OpsError) -> dict[str, Any] | None:
        """A timeout, or a failed read-back after the change ran, is an uncertain outcome, never a plain failure.
        Decided under the fence lock, so an operation that was not admitted yet is cancelled atomically."""
        with self._fence_lock:
            started = self._phases.get(operation_id) in (ADMITTED, COMPLETED)
            still_running = operation_id in self._in_os
            if not started:
                self._set_phase(operation_id, NOT_ADMITTED)  # from now on admission refuses it
        if not started and isinstance(exc, OpsTimeout):
            return err(self.mode, "OUTCOME_UNKNOWN", "Windows did not respond in time before the change started; it "
                       "was cancelled and will not run", admitted=False, still_running=False)
        if started and (isinstance(exc, OpsTimeout) or exc.code == "UNOBSERVABLE"):
            msg = ("the change started but has not finished; it may still complete" if still_running else
                   "the change ran but its result could not be read back")
            return err(self.mode, "OUTCOME_UNKNOWN", msg, admitted=True, still_running=still_running)
        return None

    def _fenced_error(self, fence: int, revision: int) -> dict[str, Any]:
        return err(self.mode, "FENCED", "authority revision is older than the helper fence (Stop or revocation)",
                   fence=fence, revision=revision)

    # ------------------------------------------------------------------------------------------
    def _observe(self, req: ObserveRequest) -> dict[str, Any]:
        now = int(self._clock() * 1000)
        if req.kind == "mouse":
            return ok(self.mode, {"observed_at": now, **self.ops.mouse_state()})
        if req.kind == "audio":
            return ok(self.mode, {"observed_at": now, **self._audio_facts()})
        if req.kind == "windows":
            return ok(self.mode, {"observed_at": now, **self._windows_facts()})
        if req.kind == "workpad":
            st = self.ops.workpad_status()
            return ok(self.mode, {"observed_at": now, "running": st is not None, **(st or {})})
        if req.kind == "click_test":
            if not req.test_id:
                return err(self.mode, "BAD_REQUEST", "test_id required")
            res = self.ops.click_test_result(req.test_id)
            return ok(self.mode, {"observed_at": now, "test_id": req.test_id, "found": res is not None, **(res or {})})
        return err(self.mode, "BAD_REQUEST", "unknown observation kind")

    def _audio_facts(self) -> dict[str, Any]:
        eps = self.ops.audio_endpoints()
        default = next((e for e in eps if e.is_default), None)

        def to_dict(e: Any) -> dict[str, Any]:
            return {"endpoint_id": e.id, "name": e.name[:120], "is_default": e.is_default, "muted": e.muted,
                    "volume_scalar": round(float(e.volume_scalar), 4)}

        return {"default": to_dict(default) if default else None, "endpoints": [to_dict(e) for e in eps[:16]],
                "active_count": len(eps)}

    def _issue_ref(self, w: RawWindow) -> str:
        now = self._clock()
        with self._refs_lock:
            for r in list(self._refs.values()):
                if r.expires_at < now:
                    del self._refs[r.ref]
            for r in self._refs.values():
                if (r.hwnd, r.pid, r.process_create_time) == (w.hwnd, w.pid, w.process_create_time):
                    r.expires_at = now + TARGET_REF_TTL_S
                    return r.ref
            if len(self._refs) > 512:
                oldest = min(self._refs.values(), key=lambda r: r.expires_at)
                del self._refs[oldest.ref]
            ref = "wt_" + secrets.token_hex(8)
            self._refs[ref] = TargetRef(ref, w.hwnd, w.pid, w.process_create_time, w.exe, w.window_class,
                                        now + TARGET_REF_TTL_S)
            return ref

    def _windows_facts(self) -> dict[str, Any]:
        monitors = self.ops.monitors()
        mon_rects = [m.rect for m in monitors]
        work_areas = [m.work for m in monitors]
        primary = next((m for m in monitors if m.primary), monitors[0] if monitors else None)
        dpi = primary.dpi if primary else 96
        wp = self.ops.workpad_status()
        workpad_hwnd = wp.get("hwnd") if wp else None
        workpad_pid = wp.get("pid") if wp else None
        excluded = {"cloaked_or_other_desktop": 0, "tool_or_owned": 0, "minimized": 0}
        candidates: list[dict[str, Any]] = []
        for w in self.ops.windows():
            if not w.visible or w.window_class in SHELL_CLASSES or not w.title.strip():
                continue
            if w.tool_window or w.owned:
                excluded["tool_or_owned"] += 1
                continue
            if w.cloaked:
                excluded["cloaked_or_other_desktop"] += 1
                continue
            if geometry.area(w.rect) == 0:
                continue
            if w.minimized:
                excluded["minimized"] += 1
                continue
            frac = geometry.visible_fraction(w.frame, mon_rects)
            reachable = geometry.caption_reachable(w.frame, work_areas, dpi)
            is_workpad = workpad_hwnd == w.hwnd and workpad_pid == w.pid
            supported, reason = True, None
            if w.integrity == "higher":
                supported, reason = False, "elevated_or_protected_window"
            elif w.maximized:
                supported, reason = False, "maximized_window_not_supported_in_this_version"
            offscreen = frac < 0.5 or not reachable
            candidates.append({
                "target_ref": self._issue_ref(w),
                "app_label": "WorkPad (RescueBridge demo)" if is_workpad else (w.exe.rsplit(".", 1)[0] or "app"),
                "is_workpad": is_workpad,
                "exe": w.exe,
                "pid": w.pid,
                "process_create_time": w.process_create_time,
                "rect": list(w.rect),
                "frame": list(w.frame),
                "state": "maximized" if w.maximized else "normal",
                "visible_fraction": frac,
                "caption_reachable": reachable,
                "offscreen": offscreen,
                "supported": supported,
                "unsupported_reason": reason,
            })
        return {
            "monitors": [m.as_dict() for m in monitors],
            "monitors_fingerprint": geometry.monitors_fingerprint([m.as_dict() for m in monitors]),
            "primary_work_area": list(primary.work) if primary else None,
            "candidates": candidates[:64],
            "eligible_count": len(candidates),
            "excluded_counts": excluded,
        }

    # ------------------------------------------------------------------------------------------
    def _execute(self, req: ExecuteRequest) -> dict[str, Any]:
        params = req.typed_params()
        op_id = req.operation_id
        with self._fence_lock:
            self._set_phase(op_id, QUEUED)
        with self._write_lock:  # serialize writes; queued writes wait here
            with self._fence_lock:
                fence = self._fence
                if req.revision < fence:  # early refusal; the authoritative check is the admission gate
                    self._set_phase(op_id, FENCED_OUT)
                    return self._fenced_error(fence, req.revision)
                self._set_phase(op_id, OBSERVING)
            admit = self._admission_gate(req.revision, op_id)
            try:
                if isinstance(params, SetMouseParams):
                    return self._exec_mouse(params, admit)
                if isinstance(params, SetAudioParams):
                    return self._exec_audio(params, admit)
                if isinstance(params, PlayToneParams):
                    return self._exec_tone(params, admit)
                if isinstance(params, MoveWindowParams):
                    return self._exec_move(params, admit)
                if isinstance(params, ShowClickTestParams):
                    self.ops.show_click_test(params.test_id, admit=admit)
                    return ok(self.mode, {"executed": True, "test_id": params.test_id})
                return err(self.mode, "BAD_REQUEST", "unsupported action")
            except Fenced as f:
                return self._fenced_error(f.fence, f.revision)
            except OpsError as exc:
                uncertain = self._uncertain_outcome(op_id, exc)
                if uncertain is not None:
                    return uncertain
                raise
            finally:
                with self._fence_lock:
                    # The request is over. Not admitted by now -> never (e.g. a precondition failed: nothing changed).
                    # Admitted and still inside its OS call -> stays in flight until the call returns (the
                    # admission context marks it COMPLETED then), never cleared here.
                    if self._phases.get(op_id) in (QUEUED, OBSERVING):
                        self._set_phase(op_id, NOT_ADMITTED)

    def _exec_mouse(self, p: SetMouseParams, admit: Admit) -> dict[str, Any]:
        before = self.ops.mouse_state()
        if bool(before["swap_effective"]) != p.expect_swap:
            return err(self.mode, "PRECONDITION_FAILED", "button mapping changed since it was observed",
                       current=before)
        self.ops.set_mouse_swap(p.swap, admit=admit)
        after = self.ops.mouse_state()
        return ok(self.mode, {"executed": True, "before": before, "after": after})

    def _exec_audio(self, p: SetAudioParams, admit: Admit) -> dict[str, Any]:
        facts = self._audio_facts()
        d = facts["default"]
        if d is None or d["endpoint_id"] != p.endpoint_id:
            return err(self.mode, "ENDPOINT_CHANGED", "default playback endpoint changed since it was observed",
                       current_default=d)
        if d["muted"] != p.expect_muted or abs(d["volume_scalar"] - p.expect_volume_scalar) > VOLUME_TOLERANCE:
            return err(self.mode, "PRECONDITION_FAILED", "endpoint mute/volume changed since it was observed",
                       current_default=d)
        self.ops.set_audio(p.endpoint_id, p.mute, p.volume_scalar, admit=admit)
        after = self._audio_facts()["default"]
        return ok(self.mode, {"executed": True, "before": d, "after": after})

    def _exec_tone(self, p: PlayToneParams, admit: Admit) -> dict[str, Any]:
        d = self._audio_facts()["default"]
        problem = tone_expectation_problem(d, p.endpoint_id, p.expect_volume_scalar)
        if problem:
            return err(self.mode, problem[0], problem[1], current_default=d)
        # The OS layer re-checks the same expectation where the tone is actually played (after any queue wait).
        played = self.ops.play_tone(p.duration_ms, p.frequency_hz, admit=admit,
                                    expect=ToneExpectation(p.endpoint_id, p.expect_volume_scalar))
        return ok(self.mode, {"executed": True, "endpoint": d, **played})

    def _exec_move(self, p: MoveWindowParams, admit: Admit) -> dict[str, Any]:
        with self._refs_lock:
            ref = self._refs.get(p.target_ref)
        if ref is None or ref.expires_at < self._clock():
            return err(self.mode, "TARGET_INVALID", "unknown or expired window target reference")
        ident = self.ops.window_identity(ref.hwnd)
        if not ident.exists:
            return err(self.mode, "TARGET_CHANGED", "window no longer exists")
        if (ident.pid, ident.process_create_time, ident.exe.lower(), ident.window_class) != (
            ref.pid, ref.process_create_time, ref.exe.lower(), ref.window_class
        ):
            return err(self.mode, "TARGET_CHANGED", "window handle now belongs to a different process or window")
        monitors = [m.as_dict() for m in self.ops.monitors()]
        if geometry.monitors_fingerprint(monitors) != p.monitors_fingerprint:
            return err(self.mode, "MONITORS_CHANGED", "display configuration changed since it was observed")
        win = next((w for w in self.ops.windows() if w.hwnd == ref.hwnd), None)
        if win is None:
            return err(self.mode, "TARGET_CHANGED", "window no longer enumerable")
        if win.integrity == "higher":
            return err(self.mode, "UNSUPPORTED", "elevated or protected window")
        if win.minimized or win.maximized:
            return err(self.mode, "UNSUPPORTED", "window is minimized or maximized")
        if win.cloaked:
            return err(self.mode, "UNSUPPORTED", "window is on another virtual desktop or cloaked")
        target = tuple(p.rect)
        if not any(geometry.area(geometry.intersect(target, tuple(m["work"]))) > 0 for m in monitors):  # type: ignore[arg-type]
            return err(self.mode, "BAD_REQUEST", "target rectangle is not on an active display")
        before = {"rect": list(win.rect), "frame": list(win.frame)}
        self.ops.move_window(ref.hwnd, target, admit=admit)  # type: ignore[arg-type]
        rects = self.ops.window_rect(ref.hwnd)
        after = {"rect": list(rects[0]), "frame": list(rects[1])} if rects else None
        return ok(self.mode, {"executed": True, "before": before, "after": after})
