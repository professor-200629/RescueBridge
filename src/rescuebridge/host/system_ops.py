"""Low-level system operations interface implemented by the real Windows adapter and the fixture.

These are called ONLY by `HelperEngine`, which enforces the fixed protocol, fencing, write
serialization, and target revalidation. Implementations must not be exposed to any caller directly.

Every mutating method takes `admit`: an admission context supplied by the engine. Implementations MUST enter it
in the execution context that performs the change, after any worker-queue wait and any preparatory calls,
immediately before the mutating OS call, and leave it only when that call has returned (or raised): `with
admitted(admit): <OS call>`. Entering raises when the operation may no longer run, and then nothing may be
changed. Leaving is what tells the engine the call is over, even if the request that started it gave up waiting.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from rescuebridge.host.geometry import Rect


class OpsError(Exception):
    """An OS call failed. `code` is a protocol error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OpsTimeout(OpsError):
    """A Windows call did not finish in time. The call itself may still be running on the worker thread."""

    def __init__(self, message: str) -> None:
        super().__init__("UNOBSERVABLE", message)


Admit = Callable[[], AbstractContextManager[None]]


def admitted(admit: Admit | None) -> AbstractContextManager[None]:
    return admit() if admit else nullcontext()

# A test tone is approved for one endpoint, unmuted, at one volume. Windows reports the endpoint volume as a float
# scalar that reads back exactly what was set (float rounding only), and every user-visible change is at least a
# 1% step (0.01). Half a step therefore tolerates rounding but rejects any change a person could make.
TONE_VOLUME_TOLERANCE = 0.005


@dataclass(frozen=True)
class ToneExpectation:
    endpoint_id: str
    volume_scalar: float  # the approved volume; the tone also requires the endpoint to be unmuted


def tone_expectation_problem(default: dict[str, Any] | None, endpoint_id: str,
                             volume_scalar: float) -> tuple[Literal["ENDPOINT_CHANGED", "PRECONDITION_FAILED"], str] | None:
    """(error code, message) if the default output no longer matches the approved tone, else None."""
    if default is None or default.get("endpoint_id") != endpoint_id:
        return "ENDPOINT_CHANGED", "the default playback device changed since the tone was approved"
    if default.get("muted"):
        return "PRECONDITION_FAILED", "the playback device is muted now; the approved tone assumed it was unmuted"
    if abs(float(default.get("volume_scalar", -1.0)) - volume_scalar) > TONE_VOLUME_TOLERANCE:
        return ("PRECONDITION_FAILED", f"the volume changed from the approved {round(volume_scalar * 100)}% "
                f"to {round(float(default.get('volume_scalar', 0)) * 100)}%")
    return None


@dataclass
class RawWindow:
    hwnd: int
    pid: int
    process_create_time: int  # ms since epoch, binds HWND to a process instance
    exe: str
    window_class: str
    title: str  # stays inside the helper; never sent to the backend or model
    rect: Rect  # GetWindowRect, physical pixels
    frame: Rect  # DWM extended frame bounds (visible area)
    visible: bool
    minimized: bool
    maximized: bool
    cloaked: bool
    tool_window: bool
    owned: bool
    integrity: str  # "same" | "higher" | "lower" | "unknown"


@dataclass
class Monitor:
    device: str
    rect: Rect
    work: Rect
    primary: bool
    dpi: int

    def as_dict(self) -> dict[str, Any]:
        return {"device": self.device, "rect": list(self.rect), "work": list(self.work),
                "primary": self.primary, "dpi": self.dpi}


@dataclass
class Endpoint:
    id: str
    name: str
    is_default: bool
    muted: bool
    volume_scalar: float


@dataclass
class WindowIdentity:
    exists: bool
    pid: int = 0
    process_create_time: int = 0
    exe: str = ""
    window_class: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class SystemOps(Protocol):
    mode: str  # "real_windows" | "fixture_simulation"

    def mouse_state(self) -> dict[str, Any]: ...

    def set_mouse_swap(self, swap: bool, *, admit: Admit | None = None) -> None: ...

    def audio_endpoints(self) -> list[Endpoint]: ...

    def set_audio(self, endpoint_id: str, mute: bool | None, volume_scalar: float | None, *,
                  admit: Admit | None = None) -> None: ...

    def play_tone(self, duration_ms: int, frequency_hz: int, *, admit: Admit | None = None,
                  expect: ToneExpectation | None = None) -> dict[str, Any]: ...

    def monitors(self) -> list[Monitor]: ...

    def windows(self) -> list[RawWindow]: ...

    def window_identity(self, hwnd: int) -> WindowIdentity: ...

    def window_rect(self, hwnd: int) -> tuple[Rect, Rect] | None: ...

    def move_window(self, hwnd: int, rect: Rect, *, admit: Admit | None = None) -> None: ...

    def workpad_status(self) -> dict[str, Any] | None: ...

    def show_click_test(self, test_id: str, *, admit: Admit | None = None) -> None: ...

    def click_test_result(self, test_id: str) -> dict[str, Any] | None: ...
