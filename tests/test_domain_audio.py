"""Audio workflow + authority behaviour through the real RecoveryService and HelperEngine (fixture OS)."""

from __future__ import annotations

import threading
import time

import anyio
import pytest

from rescuebridge.domain.enums import UserResultSource
from rescuebridge.domain.service import DomainError, Principal
from rescuebridge.host.system_ops import Endpoint, OpsError
from rescuebridge.ids import now_ms

pytestmark = pytest.mark.anyio


def mute_default(env, vol: float = 0.24) -> None:
    env.ops.state.endpoints[0].muted = True
    env.ops.state.endpoints[0].volume_scalar = vol


def pending(env, issue_id: str, kind: str = "REPAIR") -> dict:
    p = env.ctx.store.one("SELECT * FROM proposals WHERE issue_id = ? AND status = 'PENDING' AND kind = ? "
                          "ORDER BY version DESC LIMIT 1", (issue_id, kind))
    assert p is not None, "expected a pending proposal"
    return p


def audio_calls(env) -> list:
    return [c for c in env.ops.calls if c[0] == "set_audio"]


async def start_audio(env) -> str:
    res = env.svc.start_recovery(env.phone, "Interview soon, I can't hear anything",
                                 [{"category": "no_sound", "user_words": "I cannot hear anything"}])
    return res["created_issue_ids"][0]


async def test_muted_endpoint_full_flow_unresolved_when_not_heard(env):
    mute_default(env, vol=0.24)
    iid = await start_audio(env)
    res = await env.svc.inspect(env.phone, iid)
    assert res["state"] == "PROPOSED"
    assert any("MUTED" in f for f in res["observed_facts"])
    assert res["fresh_observations"][0]["source"] == "Fixture Simulation"
    p = pending(env, iid)
    assert "Unmute 'Speakers (Fixture Audio)'" in p["description"] and "24%" in p["description"]
    assert p["params"]["volume_scalar"] is None  # volume is audible: unmute only, do not change level

    # no approval -> nothing happens
    with pytest.raises(DomainError) as e:
        await env.svc.apply(env.phone, p["id"])
    assert e.value.code == "NOT_APPROVED"
    assert audio_calls(env) == []

    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    out = await env.svc.apply(env.phone, p["id"])
    assert out["operation"]["outcome"] == "APPLIED_STATE_VERIFIED"
    assert "unmuted" in out["operation"]["observed_after"]
    assert env.ops.state.endpoints[0].muted is False
    issue = env.ctx.store.get("issues", iid)
    assert issue["state"] == "VERIFYING"  # API success alone does not resolve anything

    ver = await env.svc.verify(env.phone, iid)
    assert ver["state"] == "AWAITING_USER_CONFIRMATION"
    tone = pending(env, iid, "TEST")
    env.svc.approve(env.phone_ui, tone["id"], tone["digest"])
    tout = await env.svc.apply(env.phone, tone["id"])
    assert tout["operation"]["outcome"] == "APPLIED_STATE_NOT_VERIFIED"  # audibility is not observable by API
    assert len(env.ops.tones) == 1

    # muted=false but the person still cannot hear: the symptom stays unresolved
    res = env.svc.record_user_result(env.phone_ui, iid, "still_broken", source=UserResultSource.UI_BUTTON)
    assert res["state"] == "UNRESOLVED"
    assert "headphones" in res["next_manual_step"]
    st = env.svc.status(env.phone)
    assert "0 of 1" in st["mission"]["server_summary"]


async def test_resolved_only_after_person_confirms(env):
    mute_default(env, vol=0.0)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    assert p["params"]["volume_scalar"] == 0.2  # effectively silent: bounded default test level 20%
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    await env.svc.apply(env.phone, p["id"])
    await env.svc.verify(env.phone, iid)
    assert env.ctx.store.get("issues", iid)["state"] == "AWAITING_USER_CONFIRMATION"
    tone = pending(env, iid, "TEST")
    res = env.svc.record_user_result(env.phone_ui, iid, "works", source=UserResultSource.UI_BUTTON)
    assert res["state"] == "RESOLVED"
    # Found on the owner's phone: confirming before playing the tone left an approvable tone on a resolved issue.
    assert env.ctx.store.get("proposals", tone["id"])["status"] == "SUPERSEDED"
    assert not any(p["status"] == "PENDING" for p in res["open_proposals"])
    with pytest.raises(DomainError):
        env.svc.approve(env.phone_ui, tone["id"], tone["digest"])
    assert env.ops.tones == []


async def test_unmuted_audible_default_has_no_supported_cause_and_changes_nothing(env):
    iid = await start_audio(env)
    res = await env.svc.inspect(env.phone, iid)
    assert res["state"] == "UNRESOLVED"
    assert "do not explain" in res["next_manual_step"]
    assert "Headset (Fixture Bluetooth)" in res["next_manual_step"]
    assert env.ops.calls == []


async def test_wrong_digest_other_device_and_model_path_cannot_approve(env):
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    with pytest.raises(DomainError) as e:
        env.svc.approve(env.phone_ui, p["id"], "0" * 64)
    assert e.value.code == "STALE"
    with pytest.raises(DomainError) as e:
        env.svc.approve(env.other_ui, p["id"], p["digest"])
    assert e.value.code == "NOT_FOUND"
    with pytest.raises(DomainError) as e:  # a model/MCP principal can never approve
        env.svc.approve(env.phone, p["id"], p["digest"])
    assert e.value.code == "FORBIDDEN"
    with pytest.raises(DomainError) as e:
        await env.svc.apply(env.other_ui, p["id"])
    assert e.value.code == "NOT_FOUND"
    assert audio_calls(env) == []


async def test_expired_proposal_cannot_be_approved(env):
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    # tamper-proofing: changing expires_at changes the digest, so emulate expiry by re-signing
    p2 = dict(p, expires_at=now_ms() - 1)
    p2["digest"] = env.svc.proposal_digest(p2)
    env.ctx.store.update("proposals", p["id"], {"expires_at": p2["expires_at"], "digest": p2["digest"]})
    with pytest.raises(DomainError) as e:
        env.svc.approve(env.phone_ui, p["id"], p2["digest"])
    assert e.value.code == "EXPIRED"


async def test_tampered_proposal_parameters_invalidate_approval(env):
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    env.ctx.store.update("proposals", p["id"], {"params": {**p["params"], "volume_scalar": 1.0}})
    with pytest.raises(DomainError) as e:
        await env.svc.apply(env.phone, p["id"])
    assert e.value.code == "APPROVAL_INVALID"
    assert audio_calls(env) == []


async def test_default_endpoint_changes_between_proposal_and_execution(env):
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    # the person plugs in a headset: it becomes the (muted) default endpoint
    env.ops.state.endpoints[0].is_default = False
    env.ops.state.endpoints[1].is_default = True
    env.ops.state.endpoints[1].muted = True
    out = await env.svc.apply(env.phone, p["id"])
    assert out["operation"]["outcome"] == "REJECTED_OR_EXPIRED"
    assert "default playback device changed" in out["rejected_because"]
    assert audio_calls(env) == []
    revised = pending(env, iid)
    assert revised["version"] == p["version"] + 1
    assert "Headset (Fixture Bluetooth)" in revised["description"]
    assert env.ctx.store.get("issues", iid)["state"] == "PROPOSED"
    # the old approval cannot be reused for the revised proposal
    with pytest.raises(DomainError):
        await env.svc.apply(env.phone, revised["id"])


async def test_endpoint_switch_inside_helper_toctou_window_is_rejected_by_helper(env):
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])

    def switch(state):
        state.endpoints[0].is_default = False
        state.endpoints[1].is_default = True

    orig_audio = env.ops.audio_endpoints
    calls = {"n": 0}

    def flip_after_backend_check():
        calls["n"] += 1
        if calls["n"] == 2:  # 1st read: backend before-observation, 2nd read: helper precondition check
            switch(env.ops.state)
        return orig_audio()

    env.ops.audio_endpoints = flip_after_backend_check  # type: ignore[method-assign]
    out = await env.svc.apply(env.phone, p["id"])
    assert out["operation"]["outcome"] == "REJECTED_OR_EXPIRED"
    assert "ENDPOINT_CHANGED" in (out["operation"]["error"] or "") or "changed" in out["rejected_because"]
    assert audio_calls(env) == []


async def test_duplicate_apply_returns_recorded_operation_without_second_execution(env):
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    first = await env.svc.apply(env.phone, p["id"])
    second = await env.svc.apply(env.phone, p["id"])
    assert second["duplicate_request"] is True
    assert second["operation"]["operation_id"] == first["operation"]["operation_id"]
    assert len(audio_calls(env)) == 1


async def test_concurrent_apply_requests_execute_once(env):
    mute_default(env)
    env.ops.delays["set_audio"] = 0.2
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    results = []

    async def call():
        results.append(await env.svc.apply(env.phone, p["id"]))

    async with anyio.create_task_group() as tg:
        for _ in range(3):
            tg.start_soon(call)
    assert len(audio_calls(env)) == 1
    assert sum(1 for r in results if r.get("duplicate_request")) == 2


async def test_client_timeout_after_application_is_unknown_and_never_retried(env):
    mute_default(env)
    env.ops.after_delays["set_audio"] = 0.6  # change happens, reply is late
    env.svc.execute_timeout_s = 0.2
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    out = await env.svc.apply(env.phone, p["id"])
    assert out["operation"]["outcome"] == "OUTCOME_UNKNOWN"
    assert "Outcome unknown" in out["note"]
    await anyio.sleep(0.7)
    again = await env.svc.apply(env.phone, p["id"])
    assert again["duplicate_request"] is True
    assert len(audio_calls(env)) == 1  # not repeated blindly


async def test_os_failure_and_success_without_change(env):
    mute_default(env)
    env.ops.fail["set_audio"] = OpsError("OS_ERROR", "E_ACCESSDENIED from fixture")
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    out = await env.svc.apply(env.phone, p["id"])
    assert out["operation"]["outcome"] == "FAILED"
    assert env.ctx.store.get("issues", iid)["state"] == "FAILED"

    env.ops.fail.clear()
    env.ops.noop.add("set_audio")  # API "succeeds" but nothing changes
    await env.svc.inspect(env.phone, iid)
    p2 = pending(env, iid)
    env.svc.approve(env.phone_ui, p2["id"], p2["digest"])
    out2 = await env.svc.apply(env.phone, p2["id"])
    assert out2["operation"]["outcome"] == "APPLIED_STATE_NOT_VERIFIED"
    ver = await env.svc.verify(env.phone, iid)
    assert ver["state"] == "UNRESOLVED"


async def test_unobservable_state_is_not_a_negative_finding(env):
    env.ops.unobservable.add("audio")
    iid = await start_audio(env)
    res = await env.svc.inspect(env.phone, iid)
    assert res["state"] == "INSPECTING"
    assert "says NOTHING" in res["note"]
    assert res["fresh_observations"][0]["status"] == "UNAVAILABLE"
    assert res["observed_facts"] == []  # no "not muted" style claim


async def test_helper_unavailable_inspection_and_stop_report_unknown(env):
    env.ctx.transport.available = False  # type: ignore[attr-defined]
    iid = await start_audio(env)
    res = await env.svc.inspect(env.phone, iid)
    assert res["fresh_observations"][0]["status"] == "UNAVAILABLE"
    stop = await env.svc.stop(env.phone_ui)
    assert stop["stop_state"] == "HELPER_UNREACHABLE"
    assert "unknown" in stop["detail"]


async def test_stop_revokes_approved_proposal_before_execution(env):
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    stop = await env.svc.stop(env.phone_ui)
    assert stop["stop_state"] == "CONFIRMED"
    assert stop["revoked_proposals"] == 1
    with pytest.raises(DomainError) as e:
        await env.svc.apply(env.phone, p["id"])
    assert e.value.code in ("STOPPED", "NOT_APPROVED")
    assert audio_calls(env) == []
    assert env.ctx.store.get("issues", iid)["state"] == "STOPPED"


async def test_stop_while_write_is_queued_in_helper_rejects_it(env):
    """A write waiting behind the helper's write lock must be rejected by the fence, not executed later."""
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    engine = env.ctx.transport.engine  # type: ignore[attr-defined]
    engine._write_lock.acquire()  # another write is in progress inside the helper
    released = threading.Event()

    def release_later():
        time.sleep(0.4)
        engine._write_lock.release()
        released.set()

    threading.Thread(target=release_later, daemon=True).start()
    result = {}

    async def do_apply():
        result["out"] = await env.svc.apply(env.phone, p["id"])

    async with anyio.create_task_group() as tg:
        tg.start_soon(do_apply)
        await anyio.sleep(0.15)  # apply is now queued at the helper write lock
        stop = await env.svc.stop(env.phone_ui)
        assert stop["stop_state"] == "CONFIRMED"
    assert released.is_set()
    assert result["out"]["operation"]["outcome"] == "REJECTED_OR_EXPIRED"
    assert "FENCED" in result["out"]["operation"]["error"]
    assert audio_calls(env) == []


async def test_guarded_undo_blocked_after_intervening_change_and_allowed_otherwise(env):
    mute_default(env, vol=0.3)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    out = await env.svc.apply(env.phone, p["id"])
    op_id = out["operation"]["operation_id"]

    env.ops.state.endpoints[0].volume_scalar = 0.55  # the person changes the volume afterwards
    blocked = await env.svc.request_undo(env.phone, op_id)
    assert blocked["blocked"] is True and "not overwritten" in blocked["reason"]

    env.ops.state.endpoints[0].volume_scalar = 0.3  # back to the post-repair state
    allowed = await env.svc.request_undo(env.phone, op_id)
    assert allowed["blocked"] is False
    up = env.ctx.store.get("proposals", allowed["proposal"]["proposal_id"])
    env.svc.approve(env.phone_ui, up["id"], up["digest"])
    res = await env.svc.apply(env.phone, up["id"])
    assert res["operation"]["outcome"] == "APPLIED_STATE_VERIFIED"
    assert env.ops.state.endpoints[0].muted is True
    assert env.ctx.store.get("issues", iid)["state"] == "UNRESOLVED"


async def test_undo_closes_the_pending_test_tone(env):
    # Found on the owner's phone: after Undo re-muted the speaker, "play a test tone" was still approvable.
    mute_default(env, vol=0.3)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    op_id = (await env.svc.apply(env.phone, p["id"]))["operation"]["operation_id"]
    await env.svc.verify(env.phone, iid)
    tone = pending(env, iid, "TEST")
    up = (await env.svc.request_undo(env.phone, op_id))["proposal"]
    env.svc.approve(env.phone_ui, up["proposal_id"], up["digest"])
    await env.svc.apply(env.phone, up["proposal_id"])
    assert env.ctx.store.get("issues", iid)["state"] == "UNRESOLVED"
    assert env.ctx.store.get("proposals", tone["id"])["status"] == "SUPERSEDED"
    with pytest.raises(DomainError):
        env.svc.approve(env.phone_ui, tone["id"], tone["digest"])
    assert env.ops.tones == []


async def test_model_recorded_result_requires_consistent_later_utterance(env):
    mute_default(env)
    iid = await start_audio(env)
    early = {"id": "msg_early", "mission_id": None, "device_id": "dev_phone", "role": "user",
             "text": "yes it works", "input_mode": "text", "created_at": now_ms() - 60_000, "meta": None}
    env.ctx.store.insert("messages", early)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    await env.svc.apply(env.phone, p["id"])
    await env.svc.verify(env.phone, iid)
    with pytest.raises(DomainError) as e:  # utterance predates the question
        env.svc.record_user_result(env.phone, iid, "works", source=UserResultSource.MODEL_INTERPRETED_UTTERANCE,
                                   utterance_id="msg_early")
    assert e.value.code == "BAD_INPUT"
    neg = {"id": "msg_neg", "mission_id": None, "device_id": "dev_phone", "role": "user",
           "text": "no, I still can't hear anything", "input_mode": "voice", "created_at": now_ms() + 1, "meta": None}
    env.ctx.store.insert("messages", neg)
    with pytest.raises(DomainError) as e:  # the model claims success against the person's words
        env.svc.record_user_result(env.phone, iid, "works", source=UserResultSource.MODEL_INTERPRETED_UTTERANCE,
                                   utterance_id="msg_neg")
    assert e.value.code == "AMBIGUOUS"
    res = env.svc.record_user_result(env.phone, iid, "still_broken", source=UserResultSource.MODEL_INTERPRETED_UTTERANCE,
                                     utterance_id="msg_neg")
    assert res["state"] == "UNRESOLVED"


async def test_restart_does_not_resume_stale_approval(env, tmp_path):
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    # simulate a backend restart: new service instance over the same database and helper
    from rescuebridge.domain.service import RecoveryService

    svc2 = RecoveryService(env.ctx.store, env.ctx.host_client, env.ctx.settings, host_id=env.ctx.host_id)
    notes = await svc2.reconcile_on_startup()
    assert any("revoked 1 approved" in n for n in notes)
    with pytest.raises(DomainError) as e:
        await svc2.apply(env.phone, p["id"])
    assert e.value.code == "NOT_APPROVED"
    assert env.ctx.store.get("issues", iid)["state"] == "REPORTED"
    assert audio_calls(env) == []


async def test_restart_reconciles_operation_with_unknown_outcome(env):
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    # crash after intent was recorded and the OS change happened, before the result was stored
    original_execute = env.svc._execute

    async def crash(op, prop, mission, issue):
        env.ctx.store.update("operations", op["id"], {"phase": "EXECUTING"})
        env.ops.set_audio(prop["params"]["endpoint_id"], False, None)
        raise RuntimeError("process killed")

    env.svc._execute = crash  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await env.svc.apply(env.phone, p["id"])
    env.svc._execute = original_execute  # type: ignore[method-assign]
    from rescuebridge.domain.service import RecoveryService

    svc2 = RecoveryService(env.ctx.store, env.ctx.host_client, env.ctx.settings, host_id=env.ctx.host_id)
    notes = await svc2.reconcile_on_startup()
    assert any("requested state is present" in n for n in notes)
    op = env.ctx.store.one("SELECT * FROM operations WHERE proposal_id = ?", (p["id"],))
    assert op["outcome"] == "OUTCOME_UNKNOWN" and op["phase"] == "FINISHED"
    assert env.ctx.store.get("issues", iid)["state"] == "VERIFYING"
    assert len(audio_calls(env)) == 1


async def test_observation_reference_from_other_session_is_rejected(env):
    mute_default(env)
    iid = await start_audio(env)
    await env.svc.inspect(env.phone, iid)
    other = Principal("dev_other", "ses_other", "mcp")
    res = env.svc.start_recovery(other, "other device", [{"category": "no_sound", "user_words": "quiet"}])
    other_iid = res["created_issue_ids"][0]
    other_inspect = await env.svc.inspect(other, other_iid)
    foreign_obs = other_inspect["fresh_observations"][0]["observation_id"]
    with pytest.raises(DomainError) as e:
        await env.svc.propose(env.phone, iid, basis_observation_ids=[foreign_obs])
    assert e.value.code == "BAD_INPUT"
    with pytest.raises(DomainError) as e:
        await env.svc.inspect(env.phone, other_iid)  # cannot touch another device's issue
    assert e.value.code == "NOT_FOUND"


async def test_new_endpoint_list_is_reported_not_switched(env):
    env.ops.state.endpoints.append(Endpoint(id="{0.0.0.00000000}.{hdmi-0003}", name="HDMI Display Audio",
                                            is_default=False, muted=True, volume_scalar=0.9))
    iid = await start_audio(env)
    res = await env.svc.inspect(env.phone, iid)
    assert any("HDMI Display Audio" in f for f in res["observed_facts"])
    assert env.ops.calls == []  # no automatic output-device switching
