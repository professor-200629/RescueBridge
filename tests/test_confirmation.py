"""Only a clear answer resolves an issue. Tentative, conditional, interrogative, intermittent or contradictory
answers keep the issue waiting, are recorded as "unsure" (with the person's own words as evidence), and are
answered with a short follow-up question. Fixture OS only."""

from __future__ import annotations

import pytest

from rescuebridge.agent.interpret import Interpretation, interpret
from rescuebridge.agent.llm_interpret import CombinedInterpreter
from rescuebridge.domain.confirm import confirmation_polarity
from rescuebridge.domain.enums import UserResultSource
from rescuebridge.domain.service import DomainError
from rescuebridge.host.fixture_ops import make_fixture
from rescuebridge.ids import new_id, now_ms
from tests.harness import pair_device, running_backend

pytestmark = pytest.mark.anyio

NOT_A_CLEAR_YES = ["I think it works, maybe", "It works?", "It works sometimes", "If it works, I'll tell you",
                   "It works, but I still can't hear anything"]
CLEAR_YES = "Yes, it works now"
CLEAR_NO = "No, it still doesn't work"


def test_polarity_rule():
    assert [confirmation_polarity(t) for t in NOT_A_CLEAR_YES] == ["unclear"] * 5
    assert confirmation_polarity(CLEAR_YES) == "yes"
    assert confirmation_polarity(CLEAR_NO) == "no"
    assert all(interpret(t).uncertain and not interpret(t).yes for t in NOT_A_CLEAR_YES)
    assert interpret(CLEAR_YES).yes and interpret(CLEAR_NO).no


async def awaiting_confirmation(env) -> str:
    env.ops.state.endpoints[0].muted = True
    iid = env.svc.start_recovery(env.phone, "no sound", [{"category": "no_sound"}])["created_issue_ids"][0]
    await env.svc.inspect(env.phone, iid)
    p = env.ctx.store.one("SELECT * FROM proposals WHERE issue_id = ? AND status = 'PENDING'", (iid,))
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    await env.svc.apply(env.phone, p["id"])
    await env.svc.verify(env.phone, iid)
    assert env.ctx.store.get("issues", iid)["state"] == "AWAITING_USER_CONFIRMATION"
    return iid


def said(env, text: str) -> str:
    msg = {"id": new_id("msg"), "mission_id": None, "device_id": env.phone.device_id, "role": "user", "text": text,
           "input_mode": "voice", "created_at": now_ms() + 5, "meta": None}
    env.ctx.store.insert("messages", msg)
    return msg["id"]


@pytest.mark.parametrize("text", NOT_A_CLEAR_YES)
async def test_service_refuses_success_from_an_unclear_utterance_even_if_a_model_says_works(env, text):
    iid = await awaiting_confirmation(env)
    mid = said(env, text)
    with pytest.raises(DomainError) as e:
        env.svc.record_user_result(env.phone, iid, "works", source=UserResultSource.MODEL_INTERPRETED_UTTERANCE,
                                   utterance_id=mid)
    assert e.value.code == "AMBIGUOUS"
    res = env.svc.record_user_result(env.phone, iid, "unsure", source=UserResultSource.MODEL_INTERPRETED_UTTERANCE,
                                     utterance_id=mid)
    assert res["state"] == "AWAITING_USER_CONFIRMATION"
    row = env.ctx.store.one("SELECT * FROM user_results WHERE issue_id = ? ORDER BY at DESC LIMIT 1", (iid,))
    assert row["result"] == "unsure" and row["utterance_id"] == mid  # the person's words stay as evidence


async def test_service_accepts_a_clear_yes_and_a_clear_no(env):
    iid = await awaiting_confirmation(env)
    res = env.svc.record_user_result(env.phone, iid, "works", source=UserResultSource.MODEL_INTERPRETED_UTTERANCE,
                                     utterance_id=said(env, CLEAR_YES))
    assert res["state"] == "RESOLVED"


async def test_service_routes_a_clear_no_to_the_unsuccessful_path(env):
    iid = await awaiting_confirmation(env)
    mid = said(env, CLEAR_NO)
    with pytest.raises(DomainError):
        env.svc.record_user_result(env.phone, iid, "works", source=UserResultSource.MODEL_INTERPRETED_UTTERANCE,
                                   utterance_id=mid)
    res = env.svc.record_user_result(env.phone, iid, "still_broken", source=UserResultSource.MODEL_INTERPRETED_UTTERANCE,
                                     utterance_id=mid)
    assert res["state"] == "UNRESOLVED" and res["next_manual_step"]


async def test_buttons_still_confirm_directly(env):
    iid = await awaiting_confirmation(env)
    assert env.svc.record_user_result(env.phone_ui, iid, "works", source=UserResultSource.UI_BUTTON)["state"] == "RESOLVED"


async def _through_the_phone(tmp_path, text: str) -> tuple[dict, list]:
    async with running_backend(tmp_path, make_fixture("muted")) as be:
        phone, _ = await pair_device(be)
        out = (await phone.post("/api/utterance", json={"text": "I can't hear anything"})).json()
        prop = out["status"]["issues"][0]["open_proposals"][0]
        await phone.post(f"/api/proposals/{prop['proposal_id']}/approve", json={"digest": prop["digest"]})
        r = (await phone.post("/api/utterance", json={"text": text, "input_mode": "voice"})).json()
        results = be.ctx.store.all("SELECT result, source, utterance_id FROM user_results")
        msg = be.ctx.store.one("SELECT id FROM messages WHERE role = 'user' AND text = ?", (text,))
        await phone.aclose()
        return {"reply": r["reply"]["text"], "state": r["status"]["issues"][0]["state"], "msg_id": msg["id"]}, results


@pytest.mark.parametrize("text", NOT_A_CLEAR_YES)
async def test_through_the_phone_an_unclear_answer_is_asked_again(tmp_path, text):
    out, results = await _through_the_phone(tmp_path, text)
    assert out["state"] == "AWAITING_USER_CONFIRMATION"
    assert "haven't marked it resolved" in out["reply"] and "yes or no" in out["reply"]
    assert results == [{"result": "unsure", "source": "model_interpreted_utterance", "utterance_id": out["msg_id"]}]


async def test_through_the_phone_clear_answers_resolve_or_fail(tmp_path):
    yes, _ = await _through_the_phone(tmp_path / "y", CLEAR_YES)
    assert yes["state"] == "RESOLVED"
    no, results = await _through_the_phone(tmp_path / "n", CLEAR_NO)
    assert no["state"] == "UNRESOLVED" and results[0]["result"] == "still_broken"
    # a clear "no" that names the awaited symptom is an answer, not a second report of it
    no2, results2 = await _through_the_phone(tmp_path / "n2", "No, I still can't hear anything")
    assert no2["state"] == "UNRESOLVED" and [r["result"] for r in results2] == ["still_broken"]


class _YesLLM:
    model = "fake"
    data_destination = "test"

    async def interpret(self, text, pending_question, timeout_s):  # noqa: ANN001
        return Interpretation(yes=True), 5  # a model that labels everything "yes"


@pytest.mark.parametrize("text", NOT_A_CLEAR_YES)
async def test_an_llm_yes_label_cannot_override_an_unclear_answer(text):
    it, _ = await CombinedInterpreter(_YesLLM()).interpret(text, "Did you hear the tone?", 5)  # type: ignore[arg-type]
    assert it.yes is False and it.uncertain is True
