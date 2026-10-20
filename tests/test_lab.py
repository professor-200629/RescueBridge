"""Live-lab arming/injection/restore rules, exercised against the fixture (no real Windows changes)."""

from __future__ import annotations

import time

import pytest

from rescuebridge.config import load_settings
from rescuebridge.host.fixture_ops import FixtureOps
from rescuebridge.lab import live
from rescuebridge.lab.arming import is_armed, read_arming


@pytest.fixture
def lab(tmp_path):
    settings = load_settings(data_dir=tmp_path)
    ops = FixtureOps()
    return settings, live.LiveOps(ops), ops


def test_nothing_can_be_injected_unless_armed_and_in_scope(lab):
    settings, lops, ops = lab
    with pytest.raises(live.LabError, match="not armed"):
        live.inject(settings, lops, "audio-mute")
    live.arm(settings, lops, "rehearsal-1", 5, ["audio"])
    assert is_armed(settings)
    with pytest.raises(live.LabError, match="not in the armed scope"):
        live.inject(settings, lops, "mouse-swap")
    assert ops.state.swap_effective is False
    live.inject(settings, lops, "audio-mute")
    assert ops.state.endpoints[0].muted is True


def test_arming_bounds(lab):
    settings, lops, _ = lab
    with pytest.raises(live.LabError):
        live.arm(settings, lops, "x", 31, ["audio"])
    with pytest.raises(live.LabError):
        live.arm(settings, lops, "x", 5, ["network"])
    with pytest.raises(live.LabError):
        live.arm(settings, lops, "", 5, ["audio"])
    live.arm(settings, lops, "ok", 5, ["mouse"])
    with pytest.raises(live.LabError, match="already armed"):
        live.arm(settings, lops, "again", 5, ["mouse"])


def test_restore_returns_to_snapshot_and_reports(lab):
    settings, lops, ops = lab
    live.arm(settings, lops, "rehearsal-2", 5, ["mouse", "audio", "workpad"])
    live.inject(settings, lops, "mouse-swap")
    live.inject(settings, lops, "audio-mute-silent")
    live.inject(settings, lops, "workpad-offscreen")
    assert ops.state.swap_effective is True and ops.state.swap_saved is False
    assert ops.state.endpoints[0].muted is True and ops.state.endpoints[0].volume_scalar == 0.0
    report = live.restore(settings, lops)
    assert ops.state.swap_effective is False
    assert ops.state.endpoints[0].muted is False and ops.state.endpoints[0].volume_scalar == pytest.approx(0.4)
    wp = next(w for w in ops.state.windows if w.hwnd == 0x1A2B)
    assert wp.rect == (200, 150, 1000, 750)
    assert len(report["actions"]) == 3


def test_restore_does_not_touch_settings_the_lab_did_not_change(lab):
    settings, lops, ops = lab
    live.arm(settings, lops, "rehearsal-3", 5, ["mouse", "audio"])
    ops.state.endpoints[0].volume_scalar = 0.9  # the person changed volume themselves; no fault injected
    report = live.restore(settings, lops)
    assert ops.state.endpoints[0].volume_scalar == 0.9
    assert any("did not change it" in x for x in report["left_alone"])


def test_watchdog_restores_at_expiry(lab):
    settings, lops, ops = lab
    live.arm(settings, lops, "rehearsal-4", 1, ["audio"])
    live.inject(settings, lops, "audio-mute")
    rec = read_arming(settings)
    rec["expires_at"] = time.time() + 0.3
    live._write(settings, rec)
    report = live.watchdog(settings, lops, poll_s=0.1)
    assert ops.state.endpoints[0].muted is False
    assert report["reason"] == "disarm"
    assert not is_armed(settings)


def test_arming_file_is_private(lab):
    import win32api
    import win32con
    import win32security

    settings, lops, _ = lab
    live.arm(settings, lops, "acl", 5, ["audio"])
    sd = win32security.GetFileSecurity(str(settings.lab_dir / "arming.json"), win32security.DACL_SECURITY_INFORMATION)
    dacl = sd.GetSecurityDescriptorDacl()
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    me = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    assert [dacl.GetAce(i)[2] for i in range(dacl.GetAceCount())] == [me]
