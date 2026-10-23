"""Real Windows implementation of SystemOps (current user, no elevation).

APIs used (all documented, current-user scope):
- Mouse: GetSystemMetrics(SM_SWAPBUTTON) to read the effective mapping; HKCU\\Control Panel\\Mouse
  SwapMouseButtons (read-only) for the saved value; SystemParametersInfoW(SPI_SETMOUSEBUTTONSWAP,
  SPIF_UPDATEINIFILE | SPIF_SENDCHANGE) to change it the same way the Settings app does.
- Audio: Core Audio IMMDeviceEnumerator + IAudioEndpointVolume through pycaw (GetMute/SetMute,
  Get/SetMasterVolumeLevelScalar). Test tone: generated PCM played with winsound.PlaySound (default device).
- Windows: EnumWindows, GetWindowRect, DwmGetWindowAttribute (extended frame bounds, cloaked),
  EnumDisplayMonitors/GetMonitorInfoW/GetDpiForMonitor, SetWindowPos. Process identity from
  QueryFullProcessImageNameW + GetProcessTimes; integrity level from the process token.

All calls run on ONE dedicated worker thread that initialises COM once. The process is made
per-monitor-DPI-aware (v2) at start so all coordinates are physical pixels.
"""

from __future__ import annotations

import ctypes
import io
import json
import math
import os
import struct
import subprocess
import sys
import wave
import winreg
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from pathlib import Path
from typing import Any, TypeVar

from rescuebridge.host.geometry import Rect
from rescuebridge.host.system_ops import (
    Admit,
    Endpoint,
    Monitor,
    OpsError,
    OpsTimeout,
    RawWindow,
    ToneExpectation,
    WindowIdentity,
    admitted,
    tone_expectation_problem,
)

T = TypeVar("T")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")
shcore = ctypes.WinDLL("shcore")

SM_MOUSEPRESENT, SM_SWAPBUTTON, SM_CMOUSEBUTTONS = 19, 23, 43
SPI_SETMOUSEBUTTONSWAP = 0x0021
SPIF_UPDATEINIFILE, SPIF_SENDCHANGE = 0x01, 0x02
DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
GWL_EXSTYLE, WS_EX_TOOLWINDOW, GW_OWNER = -20, 0x00000080, 4
PROCESS_QUERY_LIMITED_INFORMATION, TOKEN_QUERY, TOKEN_INTEGRITY_LEVEL = 0x1000, 0x0008, 25
SWP_NOACTIVATE, SWP_NOOWNERZORDER, SWP_NOZORDER = 0x0010, 0x0200, 0x0004
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
CREATE_NO_WINDOW = 0x08000000

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wintypes.UINT]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
for _fn in ("IsWindow", "IsWindowVisible", "IsIconic", "IsZoomed", "GetWindowTextLengthW"):
    getattr(user32, _fn).argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4


def enable_per_monitor_dpi_awareness() -> bool:
    return bool(user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                     wintypes.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _rect(r: wintypes.RECT) -> Rect:
    return (int(r.left), int(r.top), int(r.right), int(r.bottom))


def _last_error(what: str) -> OpsError:
    code = ctypes.get_last_error()
    return OpsError("OS_ERROR", f"{what} failed (Win32 error {code})")


def _tone_wav(duration_ms: int, frequency_hz: int, amplitude: float = 0.25, rate: int = 44_100) -> bytes:
    """Bounded sine tone (-12 dBFS) with 20 ms fades, as an in-memory WAV."""
    n = int(rate * duration_ms / 1000)
    fade = int(rate * 0.02)
    frames = bytearray()
    for i in range(n):
        env = min(1.0, i / fade, (n - 1 - i) / fade) if fade else 1.0
        sample = int(32767 * amplitude * env * math.sin(2 * math.pi * frequency_hz * i / rate))
        frames += struct.pack("<h", sample)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


class WindowsOps:
    mode = "real_windows"

    def __init__(self, workpad_dir: Path, click_test_dir: Path, *, call_timeout_s: float = 20.0) -> None:
        self.workpad_dir = workpad_dir
        self.click_test_dir = click_test_dir
        self.call_timeout_s = call_timeout_s
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rb-os", initializer=self._init_thread)
        self._own_integrity = self._run(lambda: self._integrity_rid(os.getpid()))

    @staticmethod
    def _init_thread() -> None:
        import comtypes

        comtypes.CoInitialize()

    def _run(self, fn: Callable[[], T]) -> T:
        """Run on the worker. A timeout stops the WAIT, not the call: the worker may still run `fn`, so mutations
        rely on their admission context (entered and left on the worker) rather than on this return."""
        fut = self._worker.submit(fn)
        try:
            return fut.result(timeout=self.call_timeout_s)
        except TimeoutError as exc:
            if fut.done():
                raise
            raise OpsTimeout(f"Windows did not finish the call within {self.call_timeout_s:g} s") from exc

    # --- mouse ---------------------------------------------------------------------------------
    def mouse_state(self) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            saved: bool | None
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Mouse") as k:
                    saved = str(winreg.QueryValueEx(k, "SwapMouseButtons")[0]).strip() == "1"
            except OSError:
                saved = None
            return {"swap_effective": bool(user32.GetSystemMetrics(SM_SWAPBUTTON)), "swap_saved": saved,
                    "mouse_present": bool(user32.GetSystemMetrics(SM_MOUSEPRESENT)),
                    "button_count": int(user32.GetSystemMetrics(SM_CMOUSEBUTTONS))}

        return self._run(read)

    def set_mouse_swap(self, swap: bool, *, admit: Admit | None = None) -> None:
        def write() -> None:
            with admitted(admit):  # on the worker thread, after any queue wait, around the OS call only
                if not user32.SystemParametersInfoW(SPI_SETMOUSEBUTTONSWAP, 1 if swap else 0, None,
                                                    SPIF_UPDATEINIFILE | SPIF_SENDCHANGE):
                    raise _last_error("SystemParametersInfoW(SPI_SETMOUSEBUTTONSWAP)")

        self._run(write)

    def inject_mouse_swap_temporary(self, swap: bool) -> bool:
        """LIVE LAB ONLY: non-persistent SwapMouseButton (reverts at sign-out). Returns previous state."""
        return self._run(lambda: bool(user32.SwapMouseButton(1 if swap else 0)))

    # --- audio ---------------------------------------------------------------------------------
    def audio_endpoints(self) -> list[Endpoint]:
        try:
            return self._run(self._read_endpoints)
        except OpsError:
            raise
        except Exception as exc:
            raise OpsError("UNOBSERVABLE", f"Core Audio read failed: {type(exc).__name__}") from exc

    @staticmethod
    def _read_endpoints() -> list[Endpoint]:
        """Runs ON the worker thread (callers inside a worker function call it directly)."""
        from comtypes import COMError
        from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
        from pycaw.utils import AudioUtilities

        enum = AudioUtilities.GetDeviceEnumerator()
        try:
            default_id = enum.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eConsole.value).GetId()
        except COMError:
            default_id = None
        out: list[Endpoint] = []
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            devices = AudioUtilities.GetAllDevices(EDataFlow.eRender.value, DEVICE_STATE.ACTIVE.value)
        for d in devices:
            try:
                ev = d.EndpointVolume
                out.append(Endpoint(id=d.id, name=str(d.FriendlyName or "Unnamed output"),
                                    is_default=d.id == default_id, muted=bool(ev.GetMute()),
                                    volume_scalar=float(ev.GetMasterVolumeLevelScalar())))
            except COMError:
                continue
        return out

    def set_audio(self, endpoint_id: str, mute: bool | None, volume_scalar: float | None, *,
                  admit: Admit | None = None) -> None:
        def write() -> None:
            import comtypes
            from pycaw.pycaw import IAudioEndpointVolume
            from pycaw.utils import AudioUtilities

            # Preparatory COM calls change nothing and can stall; authority is checked only after them.
            dev = AudioUtilities.GetDeviceEnumerator().GetDevice(endpoint_id)
            ev = dev.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None).QueryInterface(
                IAudioEndpointVolume)
            with admitted(admit):  # on the worker thread, immediately around the mutating calls
                if volume_scalar is not None:
                    ev.SetMasterVolumeLevelScalar(float(volume_scalar), None)
                if mute is not None:
                    ev.SetMute(1 if mute else 0, None)

        try:
            self._run(write)
        except OpsError:
            raise  # a refused admission is not an OS failure
        except Exception as exc:
            raise OpsError("OS_ERROR", f"Core Audio write failed: {type(exc).__name__}") from exc

    def play_tone(self, duration_ms: int, frequency_hz: int, *, admit: Admit | None = None,
                  expect: ToneExpectation | None = None) -> dict[str, Any]:
        import winsound

        data = _tone_wav(duration_ms, frequency_hz)

        def play() -> None:
            # At the playback boundary, in the same worker call: the approved endpoint, unmuted, approved volume.
            if expect is not None:
                default = next((e for e in self._read_endpoints() if e.is_default), None)
                problem = tone_expectation_problem(
                    {"endpoint_id": default.id, "muted": default.muted, "volume_scalar": default.volume_scalar}
                    if default else None, expect.endpoint_id, expect.volume_scalar)
                if problem:
                    raise OpsError(*problem)
            with admitted(admit):
                winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)

        self._run(play)
        return {"played": True, "duration_ms": duration_ms, "frequency_hz": frequency_hz, "amplitude_dbfs": -12}

    # --- monitors and windows --------------------------------------------------------------------
    def monitors(self) -> list[Monitor]:
        def read() -> list[Monitor]:
            mons: list[Monitor] = []

            def cb(hmon: int, _hdc: int, _r: Any, _lp: int) -> bool:
                mi = MONITORINFOEXW()
                mi.cbSize = ctypes.sizeof(mi)
                user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
                dx, dy = ctypes.c_uint(), ctypes.c_uint()
                dpi = 96
                if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                    dpi = int(dx.value)
                mons.append(Monitor(device=mi.szDevice, rect=_rect(mi.rcMonitor), work=_rect(mi.rcWork),
                                    primary=bool(mi.dwFlags & 1), dpi=dpi))
                return True

            user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
            return mons

        return self._run(read)

    def _integrity_rid(self, pid: int) -> int | None:
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not hproc:
            return None
        try:
            htok = wintypes.HANDLE()
            if not advapi32.OpenProcessToken(hproc, TOKEN_QUERY, ctypes.byref(htok)):
                return -1  # token not readable from our integrity level: treat as higher/protected
            try:
                size = wintypes.DWORD()
                advapi32.GetTokenInformation(htok, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(size))
                buf = ctypes.create_string_buffer(size.value)
                if not advapi32.GetTokenInformation(htok, TOKEN_INTEGRITY_LEVEL, buf, size, ctypes.byref(size)):
                    return None
                label = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
                count = advapi32.GetSidSubAuthorityCount(label.Label.Sid).contents.value
                return int(advapi32.GetSidSubAuthority(label.Label.Sid, count - 1).contents.value)
            finally:
                kernel32.CloseHandle(htok)
        finally:
            kernel32.CloseHandle(hproc)

    @staticmethod
    def _process_identity(pid: int) -> tuple[str, int]:
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not hproc:
            return ("", 0)
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            exe = ""
            if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                exe = os.path.basename(buf.value)
            c, e, k, u = (wintypes.FILETIME() for _ in range(4))
            created = 0
            if kernel32.GetProcessTimes(hproc, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
                ft = (c.dwHighDateTime << 32) | c.dwLowDateTime
                created = int((ft - 116444736000000000) / 10_000)
            return (exe, created)
        finally:
            kernel32.CloseHandle(hproc)

    def _raw_window(self, hwnd: int) -> RawWindow | None:
        if not user32.IsWindow(hwnd):
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe, created = self._process_identity(pid.value)
        title_len = user32.GetWindowTextLengthW(hwnd)
        tbuf = ctypes.create_unicode_buffer(min(title_len, 512) + 1)
        user32.GetWindowTextW(hwnd, tbuf, len(tbuf))
        cbuf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cbuf, 256)
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        fr = wintypes.RECT()
        frame = _rect(r)
        if dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(fr),
                                        ctypes.sizeof(fr)) == 0:
            frame = _rect(fr)
        cloaked = wintypes.DWORD()
        dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        exstyle = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        rid = self._integrity_rid(pid.value)
        if rid is None:
            integrity = "unknown"
        elif rid == -1 or (self._own_integrity is not None and rid > self._own_integrity):
            integrity = "higher"
        elif self._own_integrity is not None and rid < self._own_integrity:
            integrity = "lower"
        else:
            integrity = "same"
        return RawWindow(hwnd=int(hwnd), pid=int(pid.value), process_create_time=created, exe=exe,
                         window_class=cbuf.value, title=tbuf.value, rect=_rect(r), frame=frame,
                         visible=bool(user32.IsWindowVisible(hwnd)), minimized=bool(user32.IsIconic(hwnd)),
                         maximized=bool(user32.IsZoomed(hwnd)), cloaked=bool(cloaked.value),
                         tool_window=bool(exstyle & WS_EX_TOOLWINDOW), owned=bool(user32.GetWindow(hwnd, GW_OWNER)),
                         integrity=integrity)

    def windows(self) -> list[RawWindow]:
        def read() -> list[RawWindow]:
            handles: list[int] = []

            def cb(hwnd: int, _lp: int) -> bool:
                if user32.IsWindowVisible(hwnd):
                    handles.append(hwnd)
                return True

            user32.EnumWindows(WNDENUMPROC(cb), 0)
            out = []
            for h in handles[:400]:
                w = self._raw_window(h)
                if w is not None:
                    out.append(w)
            return out

        return self._run(read)

    def window_identity(self, hwnd: int) -> WindowIdentity:
        def read() -> WindowIdentity:
            if not user32.IsWindow(hwnd):
                return WindowIdentity(exists=False)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            exe, created = self._process_identity(pid.value)
            cbuf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cbuf, 256)
            return WindowIdentity(exists=True, pid=int(pid.value), process_create_time=created, exe=exe,
                                  window_class=cbuf.value)

        return self._run(read)

    def window_rect(self, hwnd: int) -> tuple[Rect, Rect] | None:
        w = self._run(lambda: self._raw_window(hwnd))
        return (w.rect, w.frame) if w else None

    def move_window(self, hwnd: int, rect: Rect, *, admit: Admit | None = None) -> None:
        def write() -> None:
            left, top, right, bottom = rect
            with admitted(admit):  # on the worker thread, after any queue wait, around the OS call only
                if not user32.SetWindowPos(hwnd, None, left, top, right - left, bottom - top,
                                           SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_NOZORDER):
                    raise _last_error("SetWindowPos")

        self._run(write)

    # --- owned demo apps -------------------------------------------------------------------------
    def workpad_status(self) -> dict[str, Any] | None:
        path = self.workpad_dir / "status.json"
        try:
            st = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        hwnd, pid = int(st.get("hwnd", 0)), int(st.get("pid", 0))
        ident = self.window_identity(hwnd) if hwnd else WindowIdentity(exists=False)
        if not ident.exists or ident.pid != pid:
            return None  # stale status file from a closed WorkPad
        return {"pid": pid, "hwnd": hwnd, "text_sha256": str(st.get("text_sha256", ""))[:64],
                "text_chars": int(st.get("text_chars", 0)), "unsaved": bool(st.get("unsaved", True))}

    def show_click_test(self, test_id: str, *, admit: Admit | None = None) -> None:
        self.click_test_dir.mkdir(parents=True, exist_ok=True)
        exe = Path(sys.executable)
        pyw = exe.with_name("pythonw.exe")
        cmd = [str(pyw if pyw.exists() else exe), "-m", "rescuebridge.workpad.clicktest", "--test-id", test_id,
               "--out", str(self.click_test_dir)]
        with admitted(admit):  # in the calling thread, around starting the process
            subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW, close_fds=True)  # noqa: S603 - fixed argv

    def click_test_result(self, test_id: str) -> dict[str, Any] | None:
        try:
            return json.loads((self.click_test_dir / f"{test_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
