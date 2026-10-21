"""USB cable mode: a phone plugged into this laptop opens the loopback app through `adb reverse`.

`adb reverse tcp:8740 tcp:8740` turns the phone's own 127.0.0.1:8740 into a tunnel over the USB cable to
this laptop's 127.0.0.1:8740. Nothing listens on Wi-Fi, no firewall rule or certificate is involved, and
phone browsers treat http://127.0.0.1 as a secure context, so the pairing QR code (which encodes
http://127.0.0.1:8740/#pair=...) opens on the phone and the microphone can be offered. The tunnel ends
when the cable is unplugged, adb restarts, or `rescuebridge usb-link --remove` runs.

Needs USB debugging enabled on the phone and Android platform-tools (adb) installed by the person.
RescueBridge never downloads or installs adb and never changes phone settings: it only lists devices and
adds or removes this one reverse port mapping. Device serial numbers are never logged or shown in full.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rescuebridge.ids import now_ms

Runner = Callable[[list[str], float], tuple[int, str, str]]  # (argv, timeout) -> (exit code, stdout, stderr)


def _run(argv: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", f"{type(exc).__name__}: {exc}"
    return p.returncode, p.stdout or "", p.stderr or ""


def find_adb() -> str | None:
    """adb from RB_ADB, PATH, or the default Android SDK location. Never downloaded by RescueBridge."""
    if v := os.environ.get("RB_ADB"):
        return v if Path(v).is_file() else None
    if found := shutil.which("adb"):
        return found
    sdk = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
    return str(sdk) if sdk.is_file() else None


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: str  # "device" (ready), "unauthorized", "offline", ...
    model: str | None = None


def parse_devices(out: str) -> list[AdbDevice]:
    """Parse `adb devices -l` output."""
    devices = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line or line.startswith(("*", "List of devices")):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), None)
        devices.append(AdbDevice(parts[0], parts[1], model.replace("_", "-") if model else None))
    return devices


def has_mapping(reverse_list: str, port: int) -> bool:
    spec = f"tcp:{port}"
    return any(line.split()[-2:] == [spec, spec] for line in reverse_list.splitlines() if line.strip())


@dataclass
class UsbStatus:
    # linked | ready | removed | no_adb | no_device | unauthorized | several_devices | error | unknown
    state: str
    detail: str
    model: str | None = None
    checked_at: int = 0

    def view(self) -> dict[str, Any]:
        return {"state": self.state, "detail": self.detail, "model": self.model, "checked_at": self.checked_at}


class UsbLink:
    """Maintains the single `adb reverse tcp:PORT tcp:PORT` mapping for one connected phone."""

    def __init__(self, port: int, *, adb: str | None = None, serial: str | None = None,
                 runner: Runner | None = None) -> None:
        self.port = port
        self.adb = adb if adb is not None else find_adb()
        self.serial = serial
        self.run = runner or _run
        self.status = UsbStatus("unknown", "not checked yet")

    def _adb(self, *args: str, serial: str | None = None, timeout: float = 10.0) -> tuple[int, str, str]:
        assert self.adb
        return self.run([self.adb, *(["-s", serial] if serial else []), *args], timeout)

    def _set(self, state: str, detail: str, model: str | None = None) -> UsbStatus:
        self.status = UsbStatus(state, detail, model, now_ms())
        return self.status

    def _pick(self) -> AdbDevice | UsbStatus:
        if not self.adb:
            return self._set("no_adb", "adb (Android platform-tools) was not found. Install it yourself or set "
                                       "RB_ADB to adb.exe; RescueBridge never downloads it.")
        code, out, err = self._adb("devices", "-l", timeout=20.0)
        if code != 0:
            return self._set("error", f"adb devices failed: {(err or out).strip()[:200]}")
        devices = parse_devices(out)
        if self.serial:
            devices = [d for d in devices if d.serial == self.serial]
        ready = [d for d in devices if d.state == "device"]
        if len(ready) == 1:
            return ready[0]
        if len(ready) > 1:
            return self._set("several_devices", "More than one phone is connected by USB. Unplug the others "
                                                "or pass --serial.")
        if any(d.state == "unauthorized" for d in devices):
            return self._set("unauthorized", "Unlock the phone and tap Allow on the 'Allow USB debugging?' prompt.")
        if devices:
            return self._set("error", f"The phone is '{devices[0].state}'. Unplug and replug the cable.")
        return self._set("no_device", "No phone found. Plug it in with a data cable and turn on USB debugging "
                                      "(Settings > Developer options).")

    def inspect(self) -> UsbStatus:
        """Read-only: report the phone and whether the mapping exists, without adding it."""
        picked = self._pick()
        if isinstance(picked, UsbStatus):
            return picked
        code, out, err = self._adb("reverse", "--list", serial=picked.serial)
        if code != 0:
            return self._set("error", f"adb reverse --list failed: {(err or out).strip()[:200]}", picked.model)
        if has_mapping(out, self.port):
            return self._set("linked", f"phone 127.0.0.1:{self.port} -> laptop 127.0.0.1:{self.port} over USB",
                             picked.model)
        return self._set("ready", "phone connected and authorized; mapping not added (start.ps1 -Usb adds it)",
                         picked.model)

    def ensure(self) -> UsbStatus:
        """Add the reverse mapping if it is missing. Idempotent; safe to call repeatedly."""
        picked = self._pick()
        if isinstance(picked, UsbStatus):
            return picked
        spec = f"tcp:{self.port}"
        code, out, _ = self._adb("reverse", "--list", serial=picked.serial)
        if code == 0 and has_mapping(out, self.port):
            return self._set("linked", f"phone 127.0.0.1:{self.port} -> laptop 127.0.0.1:{self.port} over USB",
                             picked.model)
        code, out, err = self._adb("reverse", spec, spec, serial=picked.serial)
        if code != 0:
            return self._set("error", f"adb reverse failed: {(err or out).strip()[:200]}", picked.model)
        return self._set("linked", f"phone 127.0.0.1:{self.port} -> laptop 127.0.0.1:{self.port} over USB",
                         picked.model)

    def probe(self) -> tuple[bool, str]:
        """From the phone's side, fetch /api/health through the tunnel with the phone's own curl."""
        picked = self._pick()
        if isinstance(picked, UsbStatus):
            return False, picked.detail
        url = f"http://127.0.0.1:{self.port}/api/health"
        code, out, err = self._adb("shell", f"curl -s -m 5 -o /dev/null -w '%{{http_code}}' {url}",
                                   serial=picked.serial, timeout=15.0)
        status = out.strip()
        if code == 0 and status == "200":
            return True, f"phone fetched {url} -> HTTP 200"
        return False, f"phone could not fetch {url} (curl exit {code}, HTTP {status or '-'}) {err.strip()[:120]}"

    def remove(self) -> UsbStatus:
        picked = self._pick()
        if isinstance(picked, UsbStatus):
            return picked
        code, out, err = self._adb("reverse", "--remove", f"tcp:{self.port}", serial=picked.serial)
        text = (err or out).strip()
        if code != 0 and "not found" not in text:
            return self._set("error", f"adb reverse --remove failed: {text[:200]}", picked.model)
        return self._set("removed", f"USB mapping for port {self.port} removed", picked.model)
