"""USB cable mode (`adb reverse`) with a scripted adb: no phone, adb, or Windows state is touched."""

from __future__ import annotations

import pytest

from rescuebridge.usb import UsbLink, has_mapping, parse_devices
from tests.harness import running_backend

READY = "List of devices attached\nR5TEST000XYZ           device product:a36x model:SM_A366E device:a36xq transport_id:1\n"


class FakeAdb:
    """Just enough of adb's command line: devices -l, reverse (--list/--remove), shell curl."""

    def __init__(self, devices: str = READY, curl_status: str = "200") -> None:
        self.devices = devices
        self.curl_status = curl_status
        self.mappings: set[str] = set()
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float) -> tuple[int, str, str]:
        self.calls.append(argv)
        args = argv[1:]
        if args[:1] == ["-s"]:
            args = args[2:]
        if args[:1] == ["devices"]:
            return 0, self.devices, "* daemon not running; starting now at tcp:5037\n"
        if args == ["reverse", "--list"]:
            return 0, "".join(f"UsbFfs {m} {m}\n" for m in sorted(self.mappings)), ""
        if args[:2] == ["reverse", "--remove"]:
            if args[2] in self.mappings:
                self.mappings.discard(args[2])
                return 0, "", ""
            return 1, "", f"adb: error: listener '{args[2]}' not found\n"
        if args[:1] == ["reverse"]:
            self.mappings.add(args[1])
            return 0, "", ""
        if args[:1] == ["shell"]:
            return 0, self.curl_status, ""
        return 1, "", "unexpected command"

    def adds(self) -> int:
        return sum(1 for c in self.calls if c[-3:] == ["reverse", "tcp:8740", "tcp:8740"])


def test_parse_devices_and_mapping_lines():
    out = ("* daemon started successfully\nList of devices attached\n"
           "AAA111 device product:p model:Pixel_8 device:d transport_id:2\nBBB222 unauthorized transport_id:3\n"
           "CCC333 offline\n\n")
    devs = parse_devices(out)
    assert [(d.serial, d.state, d.model) for d in devs] == [
        ("AAA111", "device", "Pixel-8"), ("BBB222", "unauthorized", None), ("CCC333", "offline", None)]
    assert has_mapping("host-19 tcp:8740 tcp:8740\n", 8740)
    assert has_mapping("UsbFfs tcp:8740 tcp:8740", 8740)
    assert not has_mapping("UsbFfs tcp:87400 tcp:87400\nUsbFfs tcp:8740 tcp:9999", 8740)


def test_ensure_adds_the_mapping_once_and_never_exposes_the_serial():
    fake = FakeAdb()
    link = UsbLink(8740, adb="adb", runner=fake)
    assert link.inspect().state == "ready" and fake.mappings == set()  # read-only check adds nothing
    st = link.ensure()
    assert (st.state, st.model) == ("linked", "SM-A366E")
    assert fake.mappings == {"tcp:8740"}
    assert ["adb", "-s", "R5TEST000XYZ", "reverse", "tcp:8740", "tcp:8740"] in fake.calls
    assert link.ensure().state == "linked" and fake.adds() == 1  # idempotent
    assert "R5TEST000XYZ" not in str(st.view())
    assert link.inspect().state == "linked"


@pytest.mark.parametrize(("devices", "adb", "state", "hint"), [
    (READY, "", "no_adb", "never downloads"),
    ("List of devices attached\n\n", "adb", "no_device", "USB debugging"),
    ("List of devices attached\nX1 unauthorized transport_id:1\n", "adb", "unauthorized", "Allow"),
    (READY + "Y2 device model:Other transport_id:4\n", "adb", "several_devices", "--serial"),
    ("List of devices attached\nX1 offline\n", "adb", "error", "replug"),
])
def test_problem_states_are_reported_with_a_next_step(devices, adb, state, hint):
    fake = FakeAdb(devices)
    st = UsbLink(8740, adb=adb, runner=fake).ensure()
    assert st.state == state and hint in st.detail
    assert fake.mappings == set()


def test_phone_side_probe_and_remove():
    fake = FakeAdb()
    link = UsbLink(8740, adb="adb", runner=fake)
    link.ensure()
    ok, detail = link.probe()
    assert ok and "HTTP 200" in detail
    assert any(c[-2] == "shell" and "curl" in c[-1] and "127.0.0.1:8740/api/health" in c[-1] for c in fake.calls)
    fake.curl_status = "000"
    assert link.probe()[0] is False
    assert link.remove().state == "removed" and fake.mappings == set()
    assert link.remove().state == "removed"  # already gone ("listener not found") is not an error


@pytest.mark.anyio
async def test_host_console_shows_usb_status_and_rechecks_after_unplug(tmp_path):
    fake = FakeAdb()
    link = UsbLink(8740, adb="adb", runner=fake)
    async with running_backend(tmp_path, usb=link) as be:
        host = be.browser()
        assert (await host.post("/api/host/bootstrap", json={"code": be.auth.create_host_bootstrap()})).status_code == 200
        state = (await host.get("/api/host/state")).json()
        assert state["usb"]["state"] == "linked" and state["usb"]["model"] == "SM-A366E"
        assert fake.mappings == {"tcp:8740"}
        calls = len(fake.calls)
        await host.get("/api/host/state")
        assert len(fake.calls) == calls  # re-checked at most every 10 s
        csrf = (await host.get("/api/session")).json()["csrf_token"]
        pairing = (await host.post("/api/host/pairing-code", headers={"X-RB-CSRF": csrf})).json()["pairing"]
        assert pairing["url"].startswith("http://127.0.0.1:")  # the address the USB-linked phone can open
        fake.devices = "List of devices attached\n\n"  # cable unplugged
        link.status.checked_at = 0
        state = (await host.get("/api/host/state")).json()
        assert state["usb"]["state"] == "no_device"
        assert "R5TEST000XYZ" not in str(state)
        await host.aclose()
