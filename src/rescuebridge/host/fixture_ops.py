"""In-memory fixture implementation of SystemOps.

Used by default automated tests and the fixture evaluation harness. It never touches the real OS.
Every observation and operation produced through it is labelled `fixture_simulation`.

Fault knobs let tests reproduce real failure shapes: OS call failure, success-without-change,
unobservable state, interleaved state changes (endpoint switch, HWND reuse, monitor change), and delays.
"""

from __future__ import annotations

import copy
import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rescuebridge.host.geometry import Rect
from rescuebridge.host.system_ops import Endpoint, Monitor, OpsError, RawWindow, WindowIdentity

WORKPAD_TEXT = (
    "Interview prep notes (synthetic demo document)\n"
    "- Tell me about yourself: 60-second version\n"
    "- Project story: RescueBridge second-channel recovery\n"
)


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class FixtureState:
    swap_effective: bool = False
    swap_saved: bool = False
    mouse_present: bool = True
    button_count: int = 5
    endpoints: list[Endpoint] = field(default_factory=list)
    monitors: list[Monitor] = field(default_factory=list)
    windows: list[RawWindow] = field(default_factory=list)
    workpad_text: str = WORKPAD_TEXT
    workpad_hwnd: int | None = None
    click_tests: dict[str, dict[str, Any]] = field(default_factory=dict)


def default_state() -> FixtureState:
    st = FixtureState()
    st.endpoints = [
        Endpoint(id="{0.0.0.00000000}.{fixture-speakers-0001}", name="Speakers (Fixture Audio)",
                 is_default=True, muted=False, volume_scalar=0.4),
        Endpoint(id="{0.0.0.00000000}.{fixture-headset-0002}", name="Headset (Fixture Bluetooth)",
                 is_default=False, muted=False, volume_scalar=0.5),
    ]
    st.monitors = [Monitor(device=r"\\.\DISPLAY1", rect=(0, 0, 1920, 1200), work=(0, 0, 1920, 1140),
                           primary=True, dpi=120)]
    now = int(time.time() * 1000)
    st.windows = [
        RawWindow(hwnd=0x1A2B, pid=4100, process_create_time=now - 600_000, exe="python.exe",
                  window_class="TkTopLevel", title="RescueBridge WorkPad", rect=(200, 150, 1000, 750),
                  frame=(207, 150, 993, 743), visible=True, minimized=False, maximized=False, cloaked=False,
                  tool_window=False, owned=False, integrity="same"),
        RawWindow(hwnd=0x2C3D, pid=5200, process_create_time=now - 900_000, exe="notepad.exe",
                  window_class="Notepad", title="private-notes.txt - Notepad", rect=(400, 300, 1300, 900),
                  frame=(407, 300, 1293, 893), visible=True, minimized=False, maximized=False, cloaked=False,
                  tool_window=False, owned=False, integrity="same"),
        RawWindow(hwnd=0x3E4F, pid=6300, process_create_time=now - 1_200_000, exe="explorer.exe",
                  window_class="CabinetWClass", title="Downloads", rect=(100, 100, 1100, 800),
                  frame=(107, 100, 1093, 793), visible=True, minimized=False, maximized=False, cloaked=False,
                  tool_window=False, owned=False, integrity="same"),
    ]
    st.workpad_hwnd = 0x1A2B
    return st


def _offscreen(st: FixtureState, hwnd: int, rect: tuple[int, int, int, int]) -> None:
    w = next(x for x in st.windows if x.hwnd == hwnd)
    w.rect = rect
    w.frame = (rect[0] + 7, rect[1], rect[2] - 7, rect[3] - 7)


def _mute(st: FixtureState, vol: float = 0.24) -> None:
    st.endpoints[0].muted = True
    st.endpoints[0].volume_scalar = vol


def _swap(st: FixtureState) -> None:
    st.swap_effective = True  # temporary change: the saved setting still says "not swapped"


def _elevated_notepad(st: FixtureState) -> None:
    w = next(x for x in st.windows if x.hwnd == 0x2C3D)
    w.integrity = "higher"
    _offscreen(st, 0x2C3D, (-1400, 200, -500, 800))


SCENARIOS: dict[str, Callable[[FixtureState], None]] = {
    "healthy": lambda st: None,
    "muted": _mute,
    "silent": lambda st: _mute(st, 0.0),
    "volume-zero": lambda st: setattr(st.endpoints[0], "volume_scalar", 0.0),
    "swapped": _swap,
    "left-handed": lambda st: (setattr(st, "swap_effective", True), setattr(st, "swap_saved", True)) and None,
    "offscreen": lambda st: _offscreen(st, 0x1A2B, (2500, 300, 3300, 900)),
    "two-offscreen": lambda st: (_offscreen(st, 0x1A2B, (2500, 300, 3300, 900)),
                                 _offscreen(st, 0x2C3D, (-1400, 200, -500, 800))) and None,
    "elevated-offscreen": _elevated_notepad,
    "interview": lambda st: (_swap(st), _mute(st), _offscreen(st, 0x1A2B, (2500, 300, 3300, 900))) and None,
}


def make_fixture(scenario: str = "healthy") -> FixtureOps:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown fixture scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
    ops = FixtureOps()
    SCENARIOS[scenario](ops.state)
    return ops


class FixtureOps:
    mode = "fixture_simulation"

    def __init__(self, state: FixtureState | None = None) -> None:
        self.state = state or default_state()
        self._lock = threading.RLock()
        self.fail: dict[str, OpsError] = {}
        self.noop: set[str] = set()
        self.unobservable: set[str] = set()
        self.delays: dict[str, float] = {}
        self.after_delays: dict[str, float] = {}  # sleep AFTER the change: the reply arrives late
        self.before_hooks: dict[str, Callable[[FixtureState], None]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tones: list[dict[str, Any]] = []

    # --- helpers -------------------------------------------------------------------------------
    def _mutation(self, name: str, args: dict[str, Any]) -> bool:
        """Common prelude for mutating calls. Returns False when the call must be a silent no-op."""
        if name in self.delays:
            time.sleep(self.delays[name])
        hook = self.before_hooks.pop(name, None)
        if hook:
            with self._lock:
                hook(self.state)
        with self._lock:
            self.calls.append((name, args))
        if name in self.fail:
            raise self.fail[name]
        return name not in self.noop

    def _after(self, name: str) -> None:
        if name in self.after_delays:
            time.sleep(self.after_delays[name])

    def _observe(self, kind: str) -> None:
        if kind in self.unobservable:
            raise OpsError("UNOBSERVABLE", f"fixture: {kind} state is unobservable")

    def snapshot(self) -> FixtureState:
        with self._lock:
            return copy.deepcopy(self.state)

    # --- mouse -------------------------------------------------------------------------------
    def mouse_state(self) -> dict[str, Any]:
        self._observe("mouse")
        with self._lock:
            return {"swap_effective": self.state.swap_effective, "swap_saved": self.state.swap_saved,
                    "mouse_present": self.state.mouse_present, "button_count": self.state.button_count}

    def set_mouse_swap(self, swap: bool) -> None:
        if self._mutation("set_mouse_swap", {"swap": swap}):
            with self._lock:
                self.state.swap_effective = swap
                self.state.swap_saved = swap
            self._after("set_mouse_swap")

    # --- audio -------------------------------------------------------------------------------
    def audio_endpoints(self) -> list[Endpoint]:
        self._observe("audio")
        with self._lock:
            return copy.deepcopy(self.state.endpoints)

    def set_audio(self, endpoint_id: str, mute: bool | None, volume_scalar: float | None) -> None:
        if not self._mutation("set_audio", {"endpoint_id": endpoint_id, "mute": mute, "volume": volume_scalar}):
            return
        with self._lock:
            for ep in self.state.endpoints:
                if ep.id == endpoint_id:
                    if mute is not None:
                        ep.muted = mute
                    if volume_scalar is not None:
                        ep.volume_scalar = volume_scalar
                    break
            else:
                raise OpsError("ENDPOINT_CHANGED", "fixture: endpoint not found")
        self._after("set_audio")

    def play_tone(self, duration_ms: int, frequency_hz: int) -> dict[str, Any]:
        if not self._mutation("play_tone", {"duration_ms": duration_ms, "frequency_hz": frequency_hz}):
            return {"played": False, "duration_ms": 0}
        record = {"duration_ms": duration_ms, "frequency_hz": frequency_hz, "at": int(time.time() * 1000)}
        self.tones.append(record)
        return {"played": True, "duration_ms": duration_ms, "simulated": True}

    # --- windows -----------------------------------------------------------------------------
    def monitors(self) -> list[Monitor]:
        self._observe("windows")
        with self._lock:
            return copy.deepcopy(self.state.monitors)

    def windows(self) -> list[RawWindow]:
        self._observe("windows")
        with self._lock:
            return copy.deepcopy(self.state.windows)

    def _find(self, hwnd: int) -> RawWindow | None:
        return next((w for w in self.state.windows if w.hwnd == hwnd), None)

    def window_identity(self, hwnd: int) -> WindowIdentity:
        with self._lock:
            w = self._find(hwnd)
            if w is None:
                return WindowIdentity(exists=False)
            return WindowIdentity(exists=True, pid=w.pid, process_create_time=w.process_create_time,
                                  exe=w.exe, window_class=w.window_class)

    def window_rect(self, hwnd: int) -> tuple[Rect, Rect] | None:
        self._observe("windows")
        with self._lock:
            w = self._find(hwnd)
            return (w.rect, w.frame) if w else None

    def move_window(self, hwnd: int, rect: Rect) -> None:
        if not self._mutation("move_window", {"hwnd": hwnd, "rect": list(rect)}):
            return
        with self._lock:
            w = self._find(hwnd)
            if w is None:
                raise OpsError("TARGET_INVALID", "fixture: window vanished")
            dx_l, dx_r = w.frame[0] - w.rect[0], w.rect[2] - w.frame[2]
            dy_b = w.rect[3] - w.frame[3]
            w.rect = rect
            w.frame = (rect[0] + dx_l, rect[1], rect[2] - dx_r, rect[3] - dy_b)
        self._after("move_window")

    # --- owned demo apps -------------------------------------------------------------------------
    def workpad_status(self) -> dict[str, Any] | None:
        with self._lock:
            if self.state.workpad_hwnd is None:
                return None
            w = self._find(self.state.workpad_hwnd)
            if w is None:
                return None
            return {"pid": w.pid, "hwnd": w.hwnd, "text_sha256": text_digest(self.state.workpad_text),
                    "text_chars": len(self.state.workpad_text), "unsaved": True}

    def show_click_test(self, test_id: str) -> None:
        if self._mutation("show_click_test", {"test_id": test_id}):
            with self._lock:
                self.state.click_tests.setdefault(test_id, {"status": "waiting"})

    def click_test_result(self, test_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self.state.click_tests.get(test_id)
            return dict(r) if r else None
