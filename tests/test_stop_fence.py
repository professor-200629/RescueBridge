"""Stop fence vs. mutation admission, proven deterministically with events (no timing sleeps), fixture OS only.

The engine hands every mutation an admission gate that the OS layer calls immediately before the change (for
WindowsOps on its worker thread, after any queue wait). These tests pause an operation at each boundary, advance
the fence, then resume it.
"""

from __future__ import annotations

import threading
from typing import Any

import anyio
import pytest

from rescuebridge.host.engine import HelperEngine
from rescuebridge.host.fixture_ops import FixtureOps

SPEAKERS = "{0.0.0.00000000}.{fixture-speakers-0001}"


class Gate:
    """Pauses the calling thread until released; records that it was reached."""

    def __init__(self) -> None:
        self.arrived = threading.Event()
        self.release = threading.Event()

    def __call__(self, *_: Any) -> None:
        self.arrived.set()
        assert self.release.wait(10), "test gate was never released"


def start(engine: HelperEngine, revision: int, op_id: str, action: str, params: dict[str, Any]) -> tuple[threading.Thread, dict]:
    out: dict[str, Any] = {}

    def run() -> None:
        out["r"] = engine.handle({"op": "execute", "revision": revision, "operation_id": op_id, "action": action,
                                  "params": params})

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, out


def fence(engine: HelperEngine, revision: int) -> dict[str, Any]:
    ack = engine.handle({"op": "fence", "revision": revision})
    assert ack["ok"], ack
    return ack["result"]


def mutations(ops: FixtureOps, name: str) -> list:
    return [c for c in ops.calls if c[0] == name]


AUDIO = {"endpoint_id": SPEAKERS, "mute": True, "expect_muted": False, "expect_volume_scalar": 0.4}


def test_stop_acknowledged_during_paused_precondition_observation_prevents_the_change():
    ops = FixtureOps()
    engine = HelperEngine(ops)
    gate = Gate()
    ops.pause_points["observe:mouse"] = gate  # the precondition read inside execute
    t, out = start(engine, 1, "op_obs", "SET_MOUSE_PRIMARY", {"swap": True, "expect_swap": False})
    assert gate.arrived.wait(10)
    ack = fence(engine, 2)  # returns while the operation is paused: Stop stays responsive
    assert ack["fence"] == 2 and ack["in_flight_operation_id"] is None  # observing is not "inside an OS call"
    assert "op_obs" in ack["pending_operation_ids"]
    gate.release.set()
    t.join(10)
    assert out["r"]["ok"] is False and out["r"]["error"]["code"] == "FENCED"
    assert mutations(ops, "set_mouse_swap") == [] and ops.state.swap_effective is False


def test_stop_acknowledged_while_the_mutation_waits_in_the_worker_queue_prevents_the_change():
    ops = FixtureOps()
    engine = HelperEngine(ops)
    gate = Gate()
    ops.pause_points["queue:set_audio"] = gate  # after the preconditions passed, before admission
    t, out = start(engine, 1, "op_queued", "SET_AUDIO_ENDPOINT", AUDIO)
    assert gate.arrived.wait(10)
    ack = fence(engine, 2)
    assert ack["in_flight_operation_id"] is None and "op_queued" in ack["pending_operation_ids"]
    gate.release.set()
    t.join(10)
    assert out["r"]["error"]["code"] == "FENCED"
    assert mutations(ops, "set_audio") == [] and ops.state.endpoints[0].muted is False


def test_an_already_admitted_os_call_is_reported_in_flight_and_may_finish():
    ops = FixtureOps()
    engine = HelperEngine(ops)
    gate = Gate()
    ops.before_hooks["set_audio"] = gate  # runs after admission, i.e. inside the (simulated) OS call
    t, out = start(engine, 1, "op_admitted", "SET_AUDIO_ENDPOINT", AUDIO)
    assert gate.arrived.wait(10)
    ack = fence(engine, 2)
    assert ack["in_flight_operation_id"] == "op_admitted" and ack["in_flight_phase"] == "ADMITTED"
    assert "op_admitted" not in ack["pending_operation_ids"]
    gate.release.set()
    t.join(10)
    assert out["r"]["ok"] is True and out["r"]["result"]["executed"] is True  # it finished, as reported
    assert ops.state.endpoints[0].muted is True
    assert engine.handle({"op": "health"})["result"]["in_flight_operation_id"] is None
    retry = engine.handle({"op": "execute", "revision": 1, "operation_id": "op_retry", "action": "SET_AUDIO_ENDPOINT",
                           "params": {**AUDIO, "mute": False, "expect_muted": True}})
    assert retry["error"]["code"] == "FENCED"  # a stale retry of the old authority is refused


def test_repeated_stop_never_lowers_the_fence_and_stale_retries_stay_refused():
    ops = FixtureOps()
    engine = HelperEngine(ops)
    assert fence(engine, 2)["fence"] == 2
    assert fence(engine, 2)["fence"] == 2  # repeated Stop: same answer
    assert fence(engine, 1)["fence"] == 2  # an older fence request cannot lower it
    stale = engine.handle({"op": "execute", "revision": 1, "operation_id": "op_stale", "action": "SET_AUDIO_ENDPOINT",
                           "params": AUDIO})
    assert stale["error"]["code"] == "FENCED" and mutations(ops, "set_audio") == []
    fresh = engine.handle({"op": "execute", "revision": 2, "operation_id": "op_fresh", "action": "SET_AUDIO_ENDPOINT",
                           "params": AUDIO})
    assert fresh["ok"] is True and len(mutations(ops, "set_audio")) == 1  # new authority works


@pytest.mark.parametrize("action,params,mutation,point", [
    ("SET_MOUSE_PRIMARY", {"swap": True, "expect_swap": False}, "set_mouse_swap", "queue:set_mouse_swap"),
    ("PLAY_TEST_TONE", {"endpoint_id": SPEAKERS, "duration_ms": 600, "frequency_hz": 660, "expect_muted": False,
                        "expect_volume_scalar": 0.4}, "play_tone", "queue:play_tone"),
    ("SHOW_CLICK_TEST", {"test_id": "ct_fence"}, "show_click_test", "queue:show_click_test"),
])
def test_every_mutation_path_goes_through_the_admission_gate(action, params, mutation, point):
    ops = FixtureOps()
    engine = HelperEngine(ops)
    gate = Gate()
    ops.pause_points[point] = gate
    t, out = start(engine, 1, f"op_{mutation}", action, params)
    assert gate.arrived.wait(10)
    fence(engine, 2)
    gate.release.set()
    t.join(10)
    assert out["r"]["error"]["code"] == "FENCED" and mutations(ops, mutation) == []
    assert ops.tones == []


def _pause_on_nth(ops: FixtureOps, point: str, n: int, gate: Gate) -> None:
    """Pause on the n-th time `point` is reached (earlier passes continue normally)."""
    seen = {"count": 0}

    def hit() -> None:
        seen["count"] += 1
        if seen["count"] >= n:
            gate()
        else:
            ops.pause_points[point] = hit

    ops.pause_points[point] = hit


pytestmark_anyio = pytest.mark.anyio


@pytestmark_anyio
async def test_service_stop_during_the_helpers_precondition_check_is_confirmed_and_nothing_changes(env):
    # The audited sequence through the real service: approve under revision 1, pause the helper's precondition
    # observation (2nd audio read: the 1st is the service's own fresh observation), Stop, resume.
    env.ops.state.endpoints[0].muted = True
    iid = env.svc.start_recovery(env.phone, "no sound", [{"category": "no_sound"}])["created_issue_ids"][0]
    await env.svc.inspect(env.phone, iid)
    p = env.ctx.store.one("SELECT * FROM proposals WHERE issue_id = ? AND status = 'PENDING'", (iid,))
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    gate = Gate()
    _pause_on_nth(env.ops, "observe:audio", 2, gate)
    async with anyio.create_task_group() as tg:
        result: dict[str, Any] = {}

        async def apply() -> None:
            result["r"] = await env.svc.apply(env.phone, p["id"])

        tg.start_soon(apply)
        assert await anyio.to_thread.run_sync(gate.arrived.wait, 10)
        stop = await env.svc.stop(env.phone_ui)
        assert stop["stop_state"] == "CONFIRMED" and stop["in_flight_operation_id"] is None
        gate.release.set()
    assert result["r"]["operation"]["outcome"] == "REJECTED_OR_EXPIRED"
    assert [c for c in env.ops.calls if c[0] == "set_audio"] == [] and env.ops.state.endpoints[0].muted is True
    assert env.ctx.store.get("issues", iid)["state"] == "STOPPED"


@pytestmark_anyio
async def test_service_stop_while_an_undo_waits_in_the_queue_prevents_the_undo(env):
    env.ops.state.endpoints[0].muted = True
    iid = env.svc.start_recovery(env.phone, "no sound", [{"category": "no_sound"}])["created_issue_ids"][0]
    await env.svc.inspect(env.phone, iid)
    p = env.ctx.store.one("SELECT * FROM proposals WHERE issue_id = ? AND status = 'PENDING'", (iid,))
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    op_id = (await env.svc.apply(env.phone, p["id"]))["operation"]["operation_id"]
    undo = (await env.svc.request_undo(env.phone, op_id))["proposal"]
    env.svc.approve(env.phone_ui, undo["proposal_id"], undo["digest"])
    gate = Gate()
    env.ops.pause_points["queue:set_audio"] = gate
    async with anyio.create_task_group() as tg:
        result: dict[str, Any] = {}

        async def apply_undo() -> None:
            result["r"] = await env.svc.apply(env.phone, undo["proposal_id"])

        tg.start_soon(apply_undo)
        assert await anyio.to_thread.run_sync(gate.arrived.wait, 10)
        stop = await env.svc.stop(env.phone_ui)
        assert stop["stop_state"] == "CONFIRMED" and stop["in_flight_operation_id"] is None
        gate.release.set()
    assert result["r"]["operation"]["outcome"] == "REJECTED_OR_EXPIRED"
    assert len([c for c in env.ops.calls if c[0] == "set_audio"]) == 1  # only the original repair
    assert env.ops.state.endpoints[0].muted is False  # the undo did not re-mute
