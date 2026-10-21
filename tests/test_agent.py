"""Agent layer: claim guard, answer-agreement policy, bounds, and visible model failure (no silent fallback)."""

from __future__ import annotations

import pytest

from rescuebridge.agent.interpret import Interpretation, interpret
from rescuebridge.agent.llm_interpret import CombinedInterpreter, _combine
from rescuebridge.agent.loop import Agent, guard_claims
from rescuebridge.agent.mcp_client import McpToolClient
from rescuebridge.agent.providers import ProviderError
from tests.harness import pair_device, running_backend

pytestmark = pytest.mark.anyio

NOT_RESOLVED = {"issues": [{"state": "AWAITING_USER_CONFIRMATION"}]}
RESOLVED = {"issues": [{"state": "RESOLVED"}]}


def test_claim_guard_blocks_unsupported_completion_and_any_approval_claim():
    text, blocked = guard_claims("I unmuted the speaker. It's fixed now. Enjoy your interview!", NOT_RESOLVED)
    assert "It's fixed now" not in text and blocked == ["It's fixed now."]
    assert "Nothing is confirmed fixed" in text
    text, blocked = guard_claims("You confirmed it. It's fixed now.", RESOLVED)
    assert blocked == [] and "fixed now" in text
    text, blocked = guard_claims("I approved the change for you.", RESOLVED)
    assert blocked and "approved" not in text.lower().replace("nothing is confirmed", "")
    text, blocked = guard_claims("It is not fixed yet. Once you approve, it should work.", NOT_RESOLVED)
    assert blocked == []


def test_answer_agreement_policy():
    assert _combine("yes", "yes") == ("yes", False)
    assert _combine(None, "no") == ("no", False)
    assert _combine("left", None) == ("left", False)
    assert _combine("left", "right") == (None, True)


class _FakeLLM:
    model = "fake"
    data_destination = "test"

    def __init__(self, it: Interpretation | None = None, fail: str | None = None) -> None:
        self.it, self.fail = it, fail

    async def interpret(self, text, pending_question, timeout_s):  # noqa: ANN001
        if self.fail:
            raise ProviderError(self.fail)
        return self.it, 5


async def test_combined_interpreter_asks_again_on_conflicting_answer():
    llm = _FakeLLM(Interpretation(primary_button="left"))
    combined = CombinedInterpreter(llm)  # type: ignore[arg-type]
    it, _ = await combined.interpret("I use my left hand", "Which physical button do you want?", 5)
    assert interpret("I use my left hand").primary_button == "right"
    assert it.primary_button is None and it.ambiguous_answer is True


async def _agent_run(tmp_path, agent: Agent, text: str, setup=None):  # noqa: ANN001
    async with running_backend(tmp_path) as be:
        if setup:
            setup(be.ops)
        phone, _ = await pair_device(be)
        dev = be.ctx.store.one("SELECT id FROM devices WHERE revoked_at IS NULL")
        token = be.auth.mint_mcp_token_for_device(dev["id"])
        msg = {"id": "msg_test000001", "mission_id": None, "device_id": dev["id"], "role": "user", "text": text,
               "input_mode": "text", "created_at": 1, "meta": None}
        be.ctx.store.insert("messages", msg)
        async with McpToolClient(be.mcp_url, token) as mcp:
            res = await agent.run(mcp, msg["id"], text, [])
        calls = list(be.ops.calls)
        await phone.aclose()
        return res, calls


async def test_model_failure_is_visible_and_changes_nothing(tmp_path):
    agent = Agent(provider_kind="ollama", ollama=None, interpreter=_FakeLLM(fail="model timed out after 60s"),
                  max_turns=4, max_tool_calls=8, timeout_s=60)
    res, calls = await _agent_run(tmp_path, agent, "I can't hear anything")
    assert res.stop_reason == "model_timeout"
    assert "couldn't interpret" in res.text and "Nothing was changed" in res.text
    assert [c["tool"] for c in res.trace] == ["get_recovery_status", "get_recovery_status"]  # no fallback actions
    assert calls == []


async def test_tool_call_budget_is_enforced(tmp_path):
    agent = Agent(provider_kind="rules", ollama=None, max_turns=4, max_tool_calls=2, timeout_s=60)
    res, _ = await _agent_run(tmp_path, agent, "my clicks are wrong, no sound, and my notes vanished")
    assert res.tool_calls == 2
    assert res.stop_reason == "tool_call_limit"


async def test_llm_interpretation_drives_the_same_mcp_flow(tmp_path):
    llm = _FakeLLM(Interpretation(categories=["no_sound"]))
    agent = Agent(provider_kind="ollama", ollama=None, interpreter=CombinedInterpreter(llm),  # type: ignore[arg-type]
                  max_turns=4, max_tool_calls=8, timeout_s=60)

    def mute(ops):  # noqa: ANN001
        ops.state.endpoints[0].muted = True

    res, calls = await _agent_run(tmp_path, agent, "the laptop has gone quiet", setup=mute)
    assert res.model_turns == 1
    assert [c["tool"] for c in res.trace][:3] == ["get_recovery_status", "start_recovery", "inspect_recovery"]
    assert "Unmute" in res.text
    assert calls == []  # proposing changes nothing


async def test_misread_negative_answer_cannot_resolve_an_issue(tmp_path):
    """Measured failure: the 3B model read 'not at all' as yes. The server's polarity check must refuse it."""
    from rescuebridge.domain.enums import UserResultSource
    from rescuebridge.domain.service import DomainError, Principal

    async with running_backend(tmp_path) as be:
        be.ops.state.endpoints[0].muted = True
        phone, _ = await pair_device(be)
        out = (await phone.post("/api/utterance", json={"text": "I can't hear anything"})).json()
        prop = out["status"]["issues"][0]["open_proposals"][0]
        await phone.post(f"/api/proposals/{prop['proposal_id']}/approve", json={"digest": prop["digest"]})
        dev = be.ctx.store.one("SELECT id FROM devices WHERE revoked_at IS NULL")["id"]
        issue_id = out["status"]["issues"][0]["issue_id"]
        msg = {"id": "msg_notatall01", "mission_id": None, "device_id": dev, "role": "user", "text": "not at all",
               "input_mode": "voice", "created_at": 10**13, "meta": None}
        be.ctx.store.insert("messages", msg)
        with pytest.raises(DomainError) as e:  # what a model that misread the answer would request
            be.ctx.service.record_user_result(Principal(dev, None, "mcp"), issue_id, "works",
                                              source=UserResultSource.MODEL_INTERPRETED_UTTERANCE,
                                              utterance_id=msg["id"])
        assert e.value.code == "AMBIGUOUS"
        assert be.ctx.store.get("issues", issue_id)["state"] == "AWAITING_USER_CONFIRMATION"
        await phone.aclose()


def test_keyword_interpreter_examples():
    it = interpret("My clicks are wrong and I can't hear anything")
    assert set(it.categories) == {"mouse_buttons_wrong", "no_sound"}
    assert interpret("my sound is gone").categories == ["no_sound"]
    assert interpret("stop").stop is True
    assert interpret("I'm right-handed").primary_button == "left"
    assert interpret("no, I still can't hear anything").no is True


def test_keyword_interpreter_tolerates_real_phone_speech_recognition():
    # Verbatim transcript from the owner's Samsung phone (Chrome speech recognition), 2026-10-21.
    heard = "my click sir not working I can't hear anything in my notes is appeared up to each pics on the phone"
    assert set(interpret(heard).categories) == {"mouse_buttons_wrong", "no_sound", "window_missing"}
    for text in ("my notes dissapeared", "the notes window is not visible", "my notes this appeared"):
        assert "window_missing" in interpret(text).categories, text
    assert "window_missing" not in interpret("a new notification appeared").categories


def test_spoken_replies_are_short_and_keep_the_exact_change():
    from rescuebridge.agent.loop import describe_issue_result, short_issue_line

    r = {"kind": "AUDIO_OUTPUT", "state": "PROPOSED",
         "observed_facts": ["Default playback device 'Speakers' is MUTED, volume 24%."],
         "open_proposals": [{"description": "Unmute 'Speakers' and leave its volume at 24%. Only this device is "
                                            "changed. Undo is available."}]}
    assert describe_issue_result(r) == ("Your speaker is muted. I can fix it: Unmute 'Speakers' and leave its volume "
                                        "at 24%. Tap Approve if that's right.")
    assert short_issue_line(r) == "Sound: your speaker is muted."
    unresolved = {"kind": "AUDIO_OUTPUT", "state": "UNRESOLVED", "observed_facts": ["Default ... unmuted, volume 34%."],
                  "next_manual_step": "Check the headphones."}
    assert describe_issue_result(unresolved) == "Check the headphones."
    assert "fixed" not in describe_issue_result(r).lower()  # a proposal is never described as a fix that happened
