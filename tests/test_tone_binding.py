"""A test-tone approval covers one output device, unmuted, at one volume. Fixture OS only: no sound is played."""

from __future__ import annotations

import pytest

from rescuebridge.domain.service import DomainError

pytestmark = pytest.mark.anyio


async def tone_ready(env, volume: float = 0.24) -> tuple[str, dict]:
    """Muted speakers -> approved unmute -> verified: a pending, approved test tone at `volume`."""
    env.ops.state.endpoints[0].muted = True
    env.ops.state.endpoints[0].volume_scalar = volume
    iid = env.svc.start_recovery(env.phone, "no sound", [{"category": "no_sound"}])["created_issue_ids"][0]
    await env.svc.inspect(env.phone, iid)
    fix = env.ctx.store.one("SELECT * FROM proposals WHERE issue_id = ? AND status = 'PENDING'", (iid,))
    env.svc.approve(env.phone_ui, fix["id"], fix["digest"])
    await env.svc.apply(env.phone, fix["id"])
    await env.svc.verify(env.phone, iid)
    tone = env.ctx.store.one("SELECT * FROM proposals WHERE issue_id = ? AND status = 'PENDING' AND kind = 'TEST'", (iid,))
    assert f"at its current {round(volume * 100)}% volume" in tone["description"]
    assert tone["params"]["expect_volume_scalar"] == volume and tone["preconditions"]["volume_scalar"] == volume
    env.svc.approve(env.phone_ui, tone["id"], tone["digest"])
    return iid, tone


def played(env) -> list:
    return [c for c in env.ops.calls if c[0] == "play_tone"]


async def test_unchanged_volume_plays_the_approved_tone(env):
    _, tone = await tone_ready(env)
    out = await env.svc.apply(env.phone, tone["id"])
    assert out["operation"]["outcome"] == "APPLIED_STATE_NOT_VERIFIED" and len(env.ops.tones) == 1


@pytest.mark.parametrize("change,expect_new_test", [
    (lambda eps: setattr(eps[0], "volume_scalar", 0.99), True),   # increased
    (lambda eps: setattr(eps[0], "volume_scalar", 0.10), True),   # decreased
    (lambda eps: [setattr(eps[0], "is_default", False), setattr(eps[1], "is_default", True)], True),  # other device
    (lambda eps: setattr(eps[0], "muted", True), False),          # muted again: no test can be offered
])
async def test_changed_output_rejects_the_stale_tone_without_playing(env, change, expect_new_test):
    iid, tone = await tone_ready(env)
    change(env.ops.state.endpoints)
    out = await env.svc.apply(env.phone, tone["id"])
    assert out["test_not_played"] is True and out["operation"]["outcome"] == "REJECTED_OR_EXPIRED"
    assert played(env) == [] and env.ops.tones == []
    assert env.ctx.store.get("issues", iid)["state"] == "AWAITING_USER_CONFIRMATION"
    if expect_new_test:  # a fresh proposal for the current settings, needing its own approval
        new = out["new_test_proposal"]
        assert new["proposal_id"] != tone["id"] and new["status"] == "PENDING"
        current = next(e for e in env.ops.state.endpoints if e.is_default)
        assert f"at its current {round(current.volume_scalar * 100)}% volume" in new["description"]
        with pytest.raises(DomainError):
            await env.svc.apply(env.phone, new["proposal_id"])  # not approved: the old approval does not carry over
    else:
        assert "new_test_proposal" not in out
    assert env.ops.state.endpoints[0].volume_scalar in (0.99, 0.10, 0.24)  # never adjusted to fit the old approval


async def test_volume_change_during_the_helpers_queue_wait_is_caught_at_the_playback_boundary(env):
    iid, tone = await tone_ready(env)

    def another_actor() -> None:  # after the service's and the engine's checks, before the tone is played
        env.ops.state.endpoints[0].volume_scalar = 0.99

    env.ops.pause_points["queue:play_tone"] = another_actor
    out = await env.svc.apply(env.phone, tone["id"])
    assert out["test_not_played"] is True and "helper refused" in out["rejected_because"]
    assert env.ops.tones == [] and played(env) == []
    assert "99% volume" in out["new_test_proposal"]["description"]


async def test_tampering_with_the_approved_volume_invalidates_the_approval(env):
    _, tone = await tone_ready(env)
    params = dict(tone["params"], expect_volume_scalar=0.99)
    env.ctx.store.update("proposals", tone["id"], {"params": params})
    with pytest.raises(DomainError):
        await env.svc.apply(env.phone, tone["id"])
    assert env.ops.tones == []


def test_the_helper_protocol_requires_the_approved_volume_and_unmuted_state():
    from pydantic import ValidationError

    from rescuebridge.host.protocol import PlayToneParams

    with pytest.raises(ValidationError):
        PlayToneParams.model_validate({"endpoint_id": "x", "duration_ms": 600, "frequency_hz": 660})
    with pytest.raises(ValidationError):
        PlayToneParams.model_validate({"endpoint_id": "x", "duration_ms": 600, "frequency_hz": 660,
                                       "expect_muted": True, "expect_volume_scalar": 0.2})
    PlayToneParams.model_validate({"endpoint_id": "x", "duration_ms": 600, "frequency_hz": 660,
                                   "expect_muted": False, "expect_volume_scalar": 0.2})
