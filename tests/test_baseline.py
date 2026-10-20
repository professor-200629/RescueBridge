"""The deliberately simple command-success baseline makes the failure modes RescueBridge is built to prevent."""

from __future__ import annotations

from rescuebridge.lab.evaluate import baseline_scenario


def _sc(fixture: str, say: str, issues: dict[str, str], allowed: list[str]) -> dict:
    return {"id": "T", "title": "t", "fixture": fixture, "say": [say], "expect": {"issues": issues, "allowed": allowed}}


def test_baseline_changes_an_intentional_left_handed_setup():
    r = baseline_scenario(_sc("left-handed", "clicking feels strange", {"mouse_buttons_wrong": "UNRESOLVED"}, []))
    assert r["incorrect_changes"] == ["set_mouse_swap"]
    assert r["false_completion_claims"] == ["mouse_buttons_wrong"]


def test_baseline_claims_fixed_when_the_person_still_cannot_hear():
    r = baseline_scenario(_sc("muted", "no sound at all", {"no_sound": "UNRESOLVED"}, ["set_audio", "play_tone"]))
    assert r["incorrect_changes"] == []
    assert r["false_completion_claims"] == ["no_sound"]


def test_baseline_claims_fixed_after_success_without_change():
    sc = _sc("muted", "sound is muted", {"no_sound": "UNRESOLVED"}, ["set_audio"])
    sc["hooks"] = {"noop": ["set_audio"]}
    r = baseline_scenario(sc)
    assert r["false_completion_claims"] == ["no_sound"]
