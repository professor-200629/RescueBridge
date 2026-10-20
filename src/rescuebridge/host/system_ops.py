"""Low-level system operations interface implemented by the real Windows adapter and the fixture.

These are called ONLY by `HelperEngine`, which enforces the fixed protocol, fencing, write
serialization, and target revalidation. Implementations must not be exposed to any caller directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from rescuebridge.host.geometry import Rect


class OpsError(Exception):
    """An OS call failed. `code` is a protocol error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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

    def set_mouse_swap(self, swap: bool) -> None: ...

    def audio_endpoints(self) -> list[Endpoint]: ...

    def set_audio(self, endpoint_id: str, mute: bool | None, volume_scalar: float | None) -> None: ...

    def play_tone(self, duration_ms: int, frequency_hz: int) -> dict[str, Any]: ...

    def monitors(self) -> list[Monitor]: ...

    def windows(self) -> list[RawWindow]: ...

    def window_identity(self, hwnd: int) -> WindowIdentity: ...

    def window_rect(self, hwnd: int) -> tuple[Rect, Rect] | None: ...

    def move_window(self, hwnd: int, rect: Rect) -> None: ...

    def workpad_status(self) -> dict[str, Any] | None: ...

    def show_click_test(self, test_id: str) -> None: ...

    def click_test_result(self, test_id: str) -> dict[str, Any] | None: ...
