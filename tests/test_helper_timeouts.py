"""A helper request that times out must not lose track of the OS call it started.

Part 1 uses the real `WindowsOps` worker thread and its real timeout path, with **fake Core Audio objects** in
place of pycaw's device enumerator: no real setting is read or changed. Part 2 checks the backend's handling on
the fixture OS. Stalls are held by events (no timing sleeps as proof); the only timing is a short timeout itself,
which always expires because the stall is released only after the request has returned.
"""

from __future__ import annotations

import dataclasses
import sys
import threading
from typing import Any

import anyio
import pytest

from rescuebridge.host.engine import HelperEngine
from rescuebridge.host.system_ops import Endpoint, OpsTimeout

pytestmark = pytest.mark.anyio  # part 2 is async; part 1 tests are plain functions

FAKE_ID = "{fake-speaker}"
UNMUTE = {"endpoint_id": FAKE_ID, "mute": False, "expect_muted": True, "expect_volume_scalar": 0.5}


class FakeCoreAudio:
    """Enumerator, device and IAudioEndpointVolume in one object. Records every call; can stall in one of them."""

    def __init__(self) -> None:
        self.endpoint = Endpoint(id=FAKE_ID, name="Fake Speaker", is_default=True, muted=True, volume_scalar=0.5)
        self.calls: list[tuple[str, Any]] = []
        self.stall_in: str | None = None
        self.stalled = threading.Event()
        self.release = threading.Event()

    def _maybe_stall(self, name: str) -> None:
        if self.stall_in == name:
            self.stalled.set()
            assert self.release.wait(10), "stall was never released"

    def GetDevice(self, endpoint_id: str) -> FakeCoreAudio:  # noqa: N802 - COM method names
        self._maybe_stall("GetDevice")  # a preparatory COM call: nothing has changed yet
        self.calls.append(("GetDevice", endpoint_id))
        return self

    def Activate(self, *_: Any) -> FakeCoreAudio:  # noqa: N802
        return self

    def QueryInterface(self, *_: Any) -> FakeCoreAudio:  # noqa: N802
        return self

    def SetMasterVolumeLevelScalar(self, value: float, _ctx: Any) -> None:  # noqa: N802
        self.calls.append(("SetMasterVolumeLevelScalar", value))
        self.endpoint.volume_scalar = value

    def SetMute(self, mute: int, _ctx: Any) -> None:  # noqa: N802
        self._maybe_stall("SetMute")  # inside the mutating call
        self.calls.append(("SetMute", mute))
        self.endpoint.muted = bool(mute)

    def writes(self) -> list[tuple[str, Any]]:
        return [c for c in self.calls if c[0].startswith("Set")]


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    if sys.platform != "win32":
        pytest.skip("exercises the WindowsOps worker thread")
    from pycaw.utils import AudioUtilities

    from rescuebridge.host.windows_ops import WindowsOps

    audio = FakeCoreAudio()
    monkeypatch.setattr(AudioUtilities, "GetDeviceEnumerator", staticmethod(lambda: audio))
    monkeypatch.setattr(WindowsOps, "_read_endpoints", staticmethod(lambda: [dataclasses.replace(audio.endpoint)]))
    ops = WindowsOps(tmp_path, tmp_path, call_timeout_s=0.3)
    return audio, ops, HelperEngine(ops)


def execute(engine: HelperEngine, op_id: str, revision: int = 1) -> dict[str, Any]:
    return engine.handle({"op": "execute", "revision": revision, "operation_id": op_id,
                          "action": "SET_AUDIO_ENDPOINT", "params": UNMUTE})


def drain(ops: Any) -> None:
    """Wait until the single worker has finished everything queued before (deterministic, no sleep)."""
    ops.call_timeout_s = 10
    ops._run(lambda: None)


def helper(engine: HelperEngine, op: str, **kw: Any) -> dict[str, Any]:
    r = engine.handle({"op": op, **kw})
    assert r["ok"], r
    return r["result"]


@pytest.mark.parametrize("stop_after_timeout", [True, False])
def test_a_timed_out_call_that_had_not_started_its_change_is_cancelled_and_never_runs(rig, stop_after_timeout):
    audio, ops, engine = rig
    audio.stall_in = "GetDevice"
    r = execute(engine, "op_prep")  # returns after the 0.3 s worker timeout while the worker is still stalled
    assert audio.stalled.is_set()
    assert r["error"]["code"] == "OUTCOME_UNKNOWN" and r["error"]["admitted"] is False
    if stop_after_timeout:
        ack = helper(engine, "fence", revision=2)
        assert ack["in_flight_operation_ids"] == [] and "op_prep" not in ack["pending_operation_ids"]
    audio.release.set()
    drain(ops)
    assert audio.writes() == []  # the stalled worker resumed, but the change was never admitted
    assert audio.endpoint.muted is True


def test_a_timed_out_call_already_inside_its_os_call_stays_in_flight_until_it_returns(rig):
    audio, ops, engine = rig
    audio.stall_in = "SetMute"
    r = execute(engine, "op_inside")
    assert r["error"]["code"] == "OUTCOME_UNKNOWN"
    assert r["error"]["admitted"] is True and r["error"]["still_running"] is True
    ack = helper(engine, "fence", revision=2)  # Stop after the timeout: the call is still reported in flight
    assert ack["in_flight_operation_id"] == "op_inside" and ack["in_flight_operation_ids"] == ["op_inside"]
    assert helper(engine, "health")["in_flight_operation_ids"] == ["op_inside"]
    audio.release.set()
    drain(ops)
    assert audio.writes() == [("SetMute", 0)]  # it finished, exactly as the acknowledgement said it might
    assert helper(engine, "health")["in_flight_operation_ids"] == []
    assert helper(engine, "fence", revision=3)["in_flight_operation_id"] is None


def test_stop_during_a_stalled_preparatory_com_call_refuses_the_change(rig):
    audio, ops, engine = rig
    ops.call_timeout_s = 10  # no timeout here: Stop lands while the worker is inside GetDevice
    audio.stall_in = "GetDevice"
    out: dict[str, Any] = {}
    t = threading.Thread(target=lambda: out.update(r=execute(engine, "op_prep_stop")), daemon=True)
    t.start()
    assert audio.stalled.wait(10)
    ack = helper(engine, "fence", revision=2)
    assert ack["in_flight_operation_ids"] == [] and "op_prep_stop" in ack["pending_operation_ids"]
    audio.release.set()
    t.join(10)
    assert out["r"]["error"]["code"] == "FENCED"  # authority re-checked after the preparatory COM calls
    assert audio.writes() == [] and audio.endpoint.muted is True


# --- part 2: the backend never concludes while the helper still runs the change ------------------------------


class Gate:
    def __init__(self) -> None:
        self.arrived = threading.Event()
        self.release = threading.Event()

    def __call__(self, *_: Any) -> None:
        self.arrived.set()
        assert self.release.wait(10), "test gate was never released"


async def approved_unmute(env: Any) -> tuple[str, dict[str, Any]]:
    env.ops.state.endpoints[0].muted = True
    iid = env.svc.start_recovery(env.phone, "no sound", [{"category": "no_sound"}])["created_issue_ids"][0]
    await env.svc.inspect(env.phone, iid)
    p = env.ctx.store.one("SELECT * FROM proposals WHERE issue_id = ? AND status = 'PENDING'", (iid,))
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    return iid, p


def stall_inside_set_audio(env: Any) -> tuple[Gate, threading.Event]:
    """The (simulated) Core Audio call blocks until released; `done` is set when it has returned."""
    gate, done = Gate(), threading.Event()
    env.ops.pause_points["os:set_audio"] = gate
    original = env.ops.set_audio

    def tracked(*a: Any, **k: Any) -> None:
        try:
            original(*a, **k)
        finally:
            done.set()

    env.ops.set_audio = tracked
    env.svc.execute_timeout_s = 0.3  # the backend stops waiting while the call is still running
    return gate, done


async def test_backend_does_not_conclude_while_the_change_still_runs_and_settles_it_on_check_again(env):
    iid, p = await approved_unmute(env)
    gate, done = stall_inside_set_audio(env)
    res = await env.svc.apply(env.phone, p["id"])
    op = env.ctx.store.one("SELECT * FROM operations WHERE proposal_id = ?", (p["id"],))
    assert gate.arrived.is_set() and "still running" in res["note"]
    assert op["phase"] != "FINISHED" and env.ctx.store.get("issues", iid)["state"] == "APPLYING"
    again = await env.svc.inspect(env.phone, iid)  # Check again while it is still running: still open
    assert "still running" in again["note"] and env.ctx.store.get("issues", iid)["state"] == "APPLYING"
    gate.release.set()
    assert await anyio.to_thread.run_sync(done.wait, 10)
    await env.svc.inspect(env.phone, iid)  # now settled from a fresh observation, never re-executed
    op = env.ctx.store.get("operations", op["id"])
    assert op["phase"] == "FINISHED" and "requested state is present" in op["reconcile_note"]
    assert env.ctx.store.get("issues", iid)["state"] == "VERIFYING"
    assert [c for c in env.ops.calls if c[0] == "set_audio"] == [env.ops.calls[-1]]  # exactly one call
    assert env.ops.state.endpoints[0].muted is False


async def test_stop_after_a_backend_timeout_still_names_the_running_change(env):
    _, p = await approved_unmute(env)
    gate, done = stall_inside_set_audio(env)
    await env.svc.apply(env.phone, p["id"])
    op = env.ctx.store.one("SELECT * FROM operations WHERE proposal_id = ?", (p["id"],))
    stop = await env.svc.stop(env.phone)
    assert stop["stop_state"] == "CONFIRMED" and stop["in_flight_operation_id"] == op["id"]
    assert "may complete" in stop["detail"]
    gate.release.set()
    assert await anyio.to_thread.run_sync(done.wait, 10)
    assert (await env.ctx.host_client.health())["result"]["in_flight_operation_ids"] == []


async def test_a_helper_timeout_before_the_change_started_is_reported_as_not_attempted(env):
    iid, p = await approved_unmute(env)

    def windows_did_not_answer() -> None:
        raise OpsTimeout("simulated: the worker did not answer")

    env.ops.pause_points["queue:set_audio"] = windows_did_not_answer  # before admission
    res = await env.svc.apply(env.phone, p["id"])
    op = env.ctx.store.one("SELECT * FROM operations WHERE proposal_id = ?", (p["id"],))
    assert op["outcome"] == "NOT_ATTEMPTED" and "cancelled before it started" in res["note"]
    assert env.ctx.store.get("issues", iid)["state"] == "FAILED"
    assert [c for c in env.ops.calls if c[0] == "set_audio"] == [] and env.ops.state.endpoints[0].muted is True


async def test_a_helper_timeout_after_the_change_started_is_an_unknown_outcome_settled_by_observation(env):
    iid, p = await approved_unmute(env)
    env.ops.fail["set_audio"] = OpsTimeout("simulated: the worker did not answer")  # admitted, then timed out
    res = await env.svc.apply(env.phone, p["id"])
    op = env.ctx.store.one("SELECT * FROM operations WHERE proposal_id = ?", (p["id"],))
    assert op["outcome"] == "OUTCOME_UNKNOWN" and op["phase"] == "FINISHED"  # not a plain "failed"
    assert "Outcome unknown" in res["note"] and "NOT present" in res["note"]
    assert env.ctx.store.get("issues", iid)["state"] == "FAILED"
