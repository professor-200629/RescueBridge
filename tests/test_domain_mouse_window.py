"""Mouse preference, off-screen window target validation, unsupported symptoms, combined partial results."""

from __future__ import annotations

import pytest

from rescuebridge.domain.enums import UserResultSource
from rescuebridge.domain.service import DomainError
from rescuebridge.host.engine import HelperEngine
from rescuebridge.host.fixture_ops import FixtureOps
from rescuebridge.host.system_ops import Monitor

pytestmark = pytest.mark.anyio


def pending(env, issue_id: str, kind: str = "REPAIR") -> dict | None:
    return env.ctx.store.one("SELECT * FROM proposals WHERE issue_id = ? AND status = 'PENDING' AND kind = ? "
                             "ORDER BY version DESC LIMIT 1", (issue_id, kind))


def start(env, *symptoms: dict) -> list[str]:
    return env.svc.start_recovery(env.phone, "Get me ready for my interview", list(symptoms))["created_issue_ids"]


def move_offscreen(env, hwnd: int, rect=(2500, 300, 3300, 900)) -> None:
    w = next(w for w in env.ops.state.windows if w.hwnd == hwnd)
    w.rect = rect
    w.frame = (rect[0] + 7, rect[1], rect[2] - 7, rect[3] - 7)


# --------------------------------------------------------------------------------------- mouse
async def test_swapped_mapping_asks_preference_before_proposing(env):
    env.ops.state.swap_effective = True
    (iid,) = start(env, {"category": "mouse_buttons_wrong", "user_words": "my clicks are wrong"})
    res = await env.svc.inspect(env.phone, iid)
    assert res["state"] == "NEEDS_CLARIFICATION"
    assert "LEFT" in res["question"] and "RIGHT" in res["question"]
    assert pending(env, iid) is None
    assert env.ops.calls == []


async def test_intentional_left_handed_mapping_is_not_changed(env):
    env.ops.state.swap_effective = env.ops.state.swap_saved = True
    (iid,) = start(env, {"category": "mouse_buttons_wrong", "user_words": "clicking feels odd"})
    await env.svc.inspect(env.phone, iid)
    res = await env.svc.propose(env.phone, iid, primary_button="right")  # the person IS left-handed
    assert res["state"] == "UNRESOLVED"
    assert "already matches" in " ".join(res["observed_facts"])
    assert pending(env, iid) is None
    assert env.ops.calls == []
    assert env.ops.state.swap_effective is True


async def test_mouse_repair_flow_with_click_test_and_undo(env):
    env.ops.state.swap_effective = True
    (iid,) = start(env, {"category": "mouse_buttons_wrong", "user_words": "left click opens menus"})
    await env.svc.inspect(env.phone, iid)
    res = await env.svc.propose(env.phone, iid, primary_button="left")
    assert res["state"] == "PROPOSED"
    p = pending(env, iid)
    assert "LEFT mouse button your primary" in p["description"]
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    out = await env.svc.apply(env.phone, p["id"])
    assert out["operation"]["outcome"] == "APPLIED_STATE_VERIFIED"
    assert env.ops.state.swap_effective is False
    assert out["click_test_id"]
    assert ("show_click_test", {"test_id": out["click_test_id"]}) in env.ops.calls
    env.ops.state.click_tests[out["click_test_id"]] = {"status": "primary_click_received", "primary_clicks": 1,
                                                       "secondary_clicks": 0}
    ver = await env.svc.verify(env.phone, iid)
    assert ver["state"] == "AWAITING_USER_CONFIRMATION"
    assert any(o["kind"] == "click_test" and "primary_click_received" in o["summary"] for o in ver["fresh_observations"])
    env.svc.record_user_result(env.phone_ui, iid, "works", source=UserResultSource.UI_BUTTON)
    assert env.ctx.store.get("issues", iid)["state"] == "RESOLVED"
    undo = await env.svc.request_undo(env.phone, out["operation"]["operation_id"])
    assert undo["blocked"] is False and "RIGHT" in undo["proposal"]["description"]


async def test_mouse_mapping_changed_by_someone_else_before_apply(env):
    env.ops.state.swap_effective = True
    (iid,) = start(env, {"category": "mouse_buttons_wrong", "user_words": "wrong clicks"})
    await env.svc.inspect(env.phone, iid)
    await env.svc.propose(env.phone, iid, primary_button="left")
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    env.ops.state.swap_effective = False  # fixed meanwhile via Settings
    out = await env.svc.apply(env.phone, p["id"])
    assert out["operation"]["outcome"] == "NO_CHANGE_NEEDED"
    assert [c for c in env.ops.calls if c[0] == "set_mouse_swap"] == []


async def test_unsupported_hardware_symptom_changes_nothing(env):
    ids = start(env, {"category": "mouse_not_moving", "user_words": "the pointer is frozen"},
                {"category": "other", "user_words": "my wifi is slow"})
    for iid in ids:
        issue = env.ctx.store.get("issues", iid)
        assert issue["state"] == "UNSUPPORTED"
        assert "No changes" in issue["next_manual_step"] or "cannot repair" in issue["next_manual_step"]
        res = await env.svc.inspect(env.phone, iid)
        assert "nothing to inspect" in res["note"]
    assert env.ctx.store.all("SELECT * FROM observations") == []
    assert env.ops.calls == []


# --------------------------------------------------------------------------------------- windows
async def test_single_offscreen_workpad_is_proposed_and_document_preserved(env):
    move_offscreen(env, 0x1A2B)
    (iid,) = start(env, {"category": "window_missing", "user_words": "my notes disappeared", "app_hint": "notes"})
    res = await env.svc.inspect(env.phone, iid)
    assert res["state"] == "PROPOSED"
    p = pending(env, iid)
    assert "WorkPad (RescueBridge demo)" in p["description"] and "unsaved text" in p["description"]
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    out = await env.svc.apply(env.phone, p["id"])
    assert out["operation"]["outcome"] == "APPLIED_STATE_VERIFIED"
    assert out["workpad_text_unchanged"] is True
    ver = await env.svc.verify(env.phone, iid)
    assert ver["state"] == "AWAITING_USER_CONFIRMATION"
    assert "notepad" not in str(ver)  # unrelated window titles never reach the model view
    assert "private-notes" not in str(env.svc.status(env.phone, for_model=True))


async def test_ambiguous_offscreen_windows_require_clarification(env):
    move_offscreen(env, 0x1A2B)
    move_offscreen(env, 0x2C3D, rect=(-1500, 200, -600, 800))
    (iid,) = start(env, {"category": "window_missing", "user_words": "a window vanished"})
    res = await env.svc.inspect(env.phone, iid)
    assert res["state"] == "NEEDS_CLARIFICATION"
    labels = [o["label"] for o in res["options"]]
    assert "WorkPad (RescueBridge demo)" in labels and "notepad" in labels
    notepad_ref = next(o["value"] for o in res["options"] if o["label"] == "notepad")
    res2 = await env.svc.propose(env.phone, iid, target_ref=notepad_ref)
    assert res2["state"] == "PROPOSED"
    assert "'notepad'" in pending(env, iid)["description"]


async def test_arbitrary_or_malformed_target_is_rejected(env):
    move_offscreen(env, 0x1A2B)
    move_offscreen(env, 0x2C3D, rect=(-1500, 200, -600, 800))
    (iid,) = start(env, {"category": "window_missing", "user_words": "a window vanished"})
    await env.svc.inspect(env.phone, iid)
    with pytest.raises(DomainError) as e:
        await env.svc.propose(env.phone, iid, target_ref="0x2C3D")  # raw HWND from a model
    assert e.value.code == "BAD_INPUT"
    res = await env.svc.propose(env.phone, iid, target_ref="wt_0123456789abcdef")  # well-formed but unknown
    assert res["state"] == "NEEDS_CLARIFICATION"


async def test_window_handle_reused_by_different_process_is_rejected(env):
    move_offscreen(env, 0x1A2B)
    (iid,) = start(env, {"category": "window_missing", "user_words": "WorkPad is gone", "app_hint": "workpad"})
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    w = next(w for w in env.ops.state.windows if w.hwnd == 0x1A2B)
    w.pid, w.exe, w.process_create_time = 9999, "malware.exe", w.process_create_time + 5000  # HWND reused
    env.ops.state.workpad_hwnd = None
    out = await env.svc.apply(env.phone, p["id"])
    assert out["operation"]["outcome"] == "REJECTED_OR_EXPIRED"
    assert [c for c in env.ops.calls if c[0] == "move_window"] == []


async def test_helper_rejects_reused_handle_even_if_backend_check_is_bypassed():
    ops = FixtureOps()
    move = next(w for w in ops.state.windows if w.hwnd == 0x1A2B)
    move.rect, move.frame = (2500, 300, 3300, 900), (2507, 300, 3293, 893)
    engine = HelperEngine(ops)
    obs = engine.handle({"op": "observe", "kind": "windows"})
    cand = next(c for c in obs["result"]["candidates"] if c["is_workpad"])
    move.pid, move.process_create_time = 4242, move.process_create_time + 1
    res = engine.handle({"op": "execute", "revision": 1, "operation_id": "op_x", "action": "MOVE_WINDOW",
                         "params": {"target_ref": cand["target_ref"], "rect": [100, 100, 900, 700],
                                    "monitors_fingerprint": obs["result"]["monitors_fingerprint"]}})
    assert res["ok"] is False and res["error"]["code"] == "TARGET_CHANGED"
    assert [c for c in ops.calls if c[0] == "move_window"] == []


async def test_monitor_change_between_proposal_and_execution(env):
    env.ops.state.monitors.append(Monitor(device=r"\\.\DISPLAY2", rect=(1920, 0, 3840, 1080),
                                          work=(1920, 0, 3840, 1040), primary=False, dpi=96))
    move_offscreen(env, 0x1A2B, rect=(4000, 300, 4800, 900))
    (iid,) = start(env, {"category": "window_missing", "user_words": "notes gone", "app_hint": "workpad"})
    await env.svc.inspect(env.phone, iid)
    p = pending(env, iid)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    env.ops.state.monitors.pop()  # external monitor unplugged
    out = await env.svc.apply(env.phone, p["id"])
    assert out["operation"]["outcome"] == "REJECTED_OR_EXPIRED"
    assert "display configuration changed" in out["rejected_because"]
    assert [c for c in env.ops.calls if c[0] == "move_window"] == []
    assert pending(env, iid)["version"] == p["version"] + 1  # revised against the new display layout


async def test_elevated_offscreen_window_is_reported_unsupported(env):
    w = next(w for w in env.ops.state.windows if w.hwnd == 0x2C3D)
    w.integrity = "higher"
    move_offscreen(env, 0x2C3D)
    (iid,) = start(env, {"category": "window_missing", "user_words": "notepad is gone", "app_hint": "notepad"})
    res = await env.svc.inspect(env.phone, iid)
    assert res["state"] == "UNRESOLVED"
    assert any("elevated or protected window" in f for f in res["observed_facts"])
    assert env.ops.calls == []


async def test_no_offscreen_window_found(env):
    (iid,) = start(env, {"category": "window_missing", "user_words": "my app vanished"})
    res = await env.svc.inspect(env.phone, iid)
    assert res["state"] == "UNRESOLVED"
    assert "Alt+Tab" in res["next_manual_step"]


# --------------------------------------------------------------------------------------- combined
async def test_combined_symptoms_partial_recovery_is_never_all_fixed(env):
    env.ops.state.swap_effective = True
    env.ops.state.endpoints[0].muted = True
    move_offscreen(env, 0x1A2B)
    ids = start(env, {"category": "mouse_buttons_wrong", "user_words": "clicks are wrong"},
                {"category": "no_sound", "user_words": "can't hear"},
                {"category": "window_missing", "user_words": "notes disappeared", "app_hint": "notes"})
    mouse, audio, window = ids
    for iid in ids:
        await env.svc.inspect(env.phone, iid)
    # audio repaired and confirmed
    p = pending(env, audio)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    await env.svc.apply(env.phone, p["id"])
    await env.svc.verify(env.phone, audio)
    env.svc.record_user_result(env.phone_ui, audio, "works", source=UserResultSource.UI_BUTTON)
    # window repaired, person says still cannot see it
    p = pending(env, window)
    env.svc.approve(env.phone_ui, p["id"], p["digest"])
    await env.svc.apply(env.phone, p["id"])
    await env.svc.verify(env.phone, window)
    env.svc.record_user_result(env.phone_ui, window, "still_broken", source=UserResultSource.UI_BUTTON)
    st = env.svc.status(env.phone)
    states = {i["category"]: i["state"] for i in st["issues"]}
    assert states == {"mouse_buttons_wrong": "NEEDS_CLARIFICATION", "no_sound": "RESOLVED",
                      "window_missing": "UNRESOLVED"}
    assert st["mission"]["server_summary"].startswith("1 of 3 issue(s) confirmed resolved")


async def test_duplicate_symptom_reports_do_not_create_duplicate_issues(env):
    start(env, {"category": "no_sound", "user_words": "no sound"})
    res = env.svc.start_recovery(env.phone, "again", [{"category": "no_sound", "user_words": "still silent"}])
    assert res["created_issue_ids"] == []
    assert len(res["issues"]) == 1
