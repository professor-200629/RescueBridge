"""The helper as a SEPARATE PROCESS over the real named pipe (fixture-backed: no Windows settings change)."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest

from rescuebridge.host.client import HelperUnavailableError, HostClient, PipeTransport

pytestmark = [pytest.mark.anyio, pytest.mark.slow]


def _spawn(tmp: Path, pipe: str) -> subprocess.Popen:
    env = {**os.environ, "RB_DATA_DIR": str(tmp), "RB_HELPER_PIPE": pipe}
    return subprocess.Popen([sys.executable, "-m", "rescuebridge.cli", "helper", "--fixture"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)


def _wait_ready(tmp: Path, proc: subprocess.Popen) -> None:
    for _ in range(100):
        if (tmp / "helper.pid").exists():
            return
        if proc.poll() is not None:
            raise AssertionError(proc.stdout.read().decode(errors="replace") if proc.stdout else "helper exited")
        time.sleep(0.1)
    raise AssertionError("helper did not start")


@pytest.fixture
def helper(tmp_path):
    pipe = rf"\\.\pipe\RescueBridgeTest-{secrets.token_hex(4)}"
    proc = _spawn(tmp_path, pipe)
    _wait_ready(tmp_path, proc)
    yield tmp_path, pipe, proc
    proc.kill()
    proc.wait(5)


async def test_pipe_roundtrip_fence_and_reject(helper):
    tmp, pipe, _ = helper
    client = HostClient(PipeTransport(pipe, tmp / "helper.key"))
    h = await client.health()
    assert h["ok"] and h["result"]["mode"] == "fixture_simulation"
    obs = await client.observe("audio")
    default = obs["result"]["default"]
    assert default["name"] == "Speakers (Fixture Audio)"
    # a write under revision 1 works; after fence(2) a write still carrying revision 1 is rejected
    params = {"swap": True, "expect_swap": False}
    r = await client.execute(action="SET_MOUSE_PRIMARY", params=params, revision=1, operation_id="op_test1")
    assert r["ok"], r
    ack = await client.fence(2)
    assert ack["ok"] and ack["result"]["fence"] == 2
    r = await client.execute(action="SET_MOUSE_PRIMARY", params={"swap": False, "expect_swap": True}, revision=1,
                             operation_id="op_test2")
    assert r["ok"] is False and r["error"]["code"] == "FENCED"
    # fixed schema: arbitrary operations are refused
    r = await client.transport.call({"op": "execute", "revision": 5, "operation_id": "op_x", "action": "RUN_SHELL",
                                     "params": {"cmd": "calc"}}, 3)
    assert r["ok"] is False and r["error"]["code"] == "BAD_REQUEST"
    r = await client.transport.call({"op": "observe", "kind": "registry"}, 3)
    assert r["error"]["code"] == "BAD_REQUEST"


async def test_wrong_key_is_rejected(helper):
    tmp, pipe, _ = helper
    fake = tmp / "fake.key"
    fake.write_bytes(os.urandom(32))
    with pytest.raises(HelperUnavailableError, match="authentication failed"):
        await HostClient(PipeTransport(pipe, fake)).health()


async def test_second_helper_cannot_take_over_the_pipe(helper):
    tmp, pipe, _ = helper
    other = tmp / "other"
    other.mkdir()
    proc2 = _spawn(other, pipe)
    out = proc2.communicate(timeout=20)[0].decode(errors="replace")
    assert proc2.returncode != 0
    assert "could not start" in out


def test_pipe_dacl_grants_only_current_user(helper):
    import win32api
    import win32con
    import win32file
    import win32security

    tmp, pipe, _ = helper
    h = win32file.CreateFile(pipe, win32con.GENERIC_READ | win32con.GENERIC_WRITE, 0, None, win32con.OPEN_EXISTING, 0, None)
    try:
        sd = win32security.GetSecurityInfo(h, win32security.SE_KERNEL_OBJECT, win32security.DACL_SECURITY_INFORMATION)
        dacl = sd.GetSecurityDescriptorDacl()
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        me = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        sids = [dacl.GetAce(i)[2] for i in range(dacl.GetAceCount())]
        assert sids == [me]
        key_sd = win32security.GetFileSecurity(str(tmp / "helper.key"), win32security.DACL_SECURITY_INFORMATION)
        kd = key_sd.GetSecurityDescriptorDacl()
        assert [kd.GetAce(i)[2] for i in range(kd.GetAceCount())] == [me]
    finally:
        win32file.CloseHandle(h)


async def test_unreachable_helper_is_reported_as_unavailable(helper):
    tmp, pipe, proc = helper
    proc.kill()
    proc.wait(5)
    await anyio.sleep(0.2)
    with pytest.raises(HelperUnavailableError):
        await HostClient(PipeTransport(pipe, tmp / "helper.key")).observe("mouse")
