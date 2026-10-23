"""The three supported recovery workflows, as deterministic code.

Each recipe turns fresh observation facts (plus the person's stated preference/answers) into one of:
- a supported explanation + an exact proposal plan,
- one focused clarification question,
- "no supported cause" with an honest manual next step.

Nothing here talks to the OS or the model. Wording is plain language for the person; the model only
paraphrases these server-generated statements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from rescuebridge.domain.enums import ActionKind, IssueKind, ProposalKind
from rescuebridge.host import geometry

DEFAULT_TEST_VOLUME_PERCENT = 20
MIN_TEST_VOLUME_PERCENT = 5
MAX_TEST_VOLUME_PERCENT = 50
LOW_VOLUME_SCALAR = 0.05
TONE_DURATION_MS = 1200
TONE_FREQUENCY_HZ = 660

AnalysisOutcome = Literal["propose", "clarify", "no_supported_cause", "unavailable"]


@dataclass
class ProposalPlan:
    action: ActionKind
    params: dict[str, Any]
    target: dict[str, Any]
    preconditions: dict[str, Any]
    description: str
    original_state: dict[str, Any]
    expected_post_state: dict[str, Any]
    kind: ProposalKind = ProposalKind.REPAIR


@dataclass
class Analysis:
    outcome: AnalysisOutcome
    findings: list[str] = field(default_factory=list)
    explanation: str | None = None
    question: str | None = None
    options: list[dict[str, str]] = field(default_factory=list)
    plan: ProposalPlan | None = None
    next_manual_step: str | None = None


@dataclass
class Answers:
    primary_button: Literal["left", "right"] | None = None
    target_ref: str | None = None
    volume_percent: int | None = None


OBSERVE_KINDS: dict[IssueKind, list[str]] = {
    IssueKind.MOUSE_BUTTONS: ["mouse"],
    IssueKind.AUDIO_OUTPUT: ["audio"],
    IssueKind.OFFSCREEN_WINDOW: ["windows", "workpad"],
    IssueKind.UNSUPPORTED: [],
}


# ------------------------------------------------------------------------------------------------
# A. Mouse button mapping
# ------------------------------------------------------------------------------------------------
def _side(swap: bool) -> str:
    return "RIGHT" if swap else "LEFT"


def analyze_mouse(facts: dict[str, Any], answers: Answers) -> Analysis:
    m = facts["mouse"]
    swap = bool(m["swap_effective"])
    findings = [
        f"Windows currently uses the {_side(swap)} physical button as the primary (main) click button"
        + (" — buttons are swapped from the default." if swap else " (the Windows default).")
    ]
    if m.get("swap_saved") is not None and bool(m["swap_saved"]) != swap:
        findings.append("The saved setting differs from the active one, so a temporary change may be in effect.")
    if answers.primary_button is None:
        return Analysis(
            outcome="clarify",
            findings=findings,
            question=("Which physical button do you want for normal clicking: the LEFT button (usual for "
                      "right-handed use) or the RIGHT button (often chosen for left-handed use)?"),
            options=[{"value": "left", "label": "Left button for normal clicks"},
                     {"value": "right", "label": "Right button for normal clicks (left-handed)"}],
        )
    desired = answers.primary_button == "right"
    if desired == swap:
        return Analysis(
            outcome="no_supported_cause",
            findings=findings + ["This already matches the preference you gave, so this setting does not explain "
                                 "the wrong clicks."],
            next_manual_step=("No setting was changed. Next manual checks: try the touchpad or another mouse, a "
                              "different USB port, or fresh batteries. If the pointer does not move at all, that is "
                              "a hardware or connection problem this workflow cannot repair."),
        )
    want, other = _side(desired), _side(not desired)
    plan = ProposalPlan(
        action=ActionKind.SET_MOUSE_PRIMARY,
        params={"swap": desired, "expect_swap": swap},
        target={"setting": "Primary mouse button (current Windows account)"},
        preconditions={"swap_effective": swap},
        description=(f"Make the {want} mouse button your primary (main) click button. Windows will stop using the "
                     f"{other} button for normal clicks. This changes the 'Primary mouse button' setting for your "
                     "Windows account and is saved. Afterwards a click-test target appears on the laptop screen. "
                     "Undo is available."),
        original_state={"swap_effective": swap},
        expected_post_state={"swap_effective": desired},
    )
    return Analysis(
        outcome="propose", findings=findings, plan=plan,
        explanation=(f"The active mapping uses the {other} button as primary, which conflicts with your stated "
                     f"preference ({want}). That would make normal clicks behave like right-clicks (or vice versa)."),
    )


def mouse_matches(expected: dict[str, Any], facts: dict[str, Any]) -> bool:
    return bool(facts["mouse"]["swap_effective"]) == bool(expected["swap_effective"])


def undo_mouse(op: dict[str, Any], facts: dict[str, Any]) -> ProposalPlan:
    original = bool(op["original_state"]["swap_effective"])
    current = bool(facts["mouse"]["swap_effective"])
    return ProposalPlan(
        kind=ProposalKind.UNDO,
        action=ActionKind.SET_MOUSE_PRIMARY,
        params={"swap": original, "expect_swap": current},
        target={"setting": "Primary mouse button (current Windows account)"},
        preconditions={"swap_effective": current},
        description=(f"Undo the earlier repair: set the primary mouse button back to the {_side(original)} button, "
                     "as it was before RescueBridge changed it."),
        original_state={"swap_effective": current},
        expected_post_state={"swap_effective": original},
    )


# ------------------------------------------------------------------------------------------------
# B. Muted default playback endpoint
# ------------------------------------------------------------------------------------------------
def _pct(scalar: float) -> int:
    return round(scalar * 100)


def analyze_audio(facts: dict[str, Any], answers: Answers) -> Analysis:
    a = facts["audio"]
    d = a.get("default")
    others = [e for e in a.get("endpoints", []) if not e.get("is_default")]
    if d is None:
        return Analysis(
            outcome="no_supported_cause",
            findings=["Windows reports no default playback device."],
            next_manual_step=("Connect speakers or headphones, then check Settings > System > Sound > Output. "
                              "No setting was changed."),
        )
    findings = [f"Default playback device '{d['name']}' is {'MUTED' if d['muted'] else 'not muted'}, "
                f"volume {_pct(d['volume_scalar'])}%."]
    if others:
        findings.append("Other active outputs: " + ", ".join(
            f"'{e['name']}' ({'muted' if e['muted'] else 'unmuted'}, {_pct(e['volume_scalar'])}%)" for e in others[:4]))
    low = d["volume_scalar"] < LOW_VOLUME_SCALAR
    if not d["muted"] and not low:
        step = ("The default device is unmuted with audible volume, so these settings do not explain the silence. "
                "Next manual checks: the app's own volume, physical volume keys, headphones plugged in")
        if others:
            step += f", or whether sound should come from '{others[0]['name']}' (Settings > System > Sound > Output)"
        return Analysis(outcome="no_supported_cause", findings=findings, next_manual_step=step + ". No setting was changed.")
    vol_pct = answers.volume_percent if answers.volume_percent is not None else DEFAULT_TEST_VOLUME_PERCENT
    vol_pct = max(MIN_TEST_VOLUME_PERCENT, min(MAX_TEST_VOLUME_PERCENT, int(vol_pct)))
    set_volume = low  # only change volume when it is effectively silent
    new_vol = vol_pct / 100 if set_volume else d["volume_scalar"]
    parts = []
    if d["muted"]:
        parts.append(f"Unmute '{d['name']}'")
    if set_volume:
        parts.append(f"set its volume from {_pct(d['volume_scalar'])}% to {vol_pct}%")
    else:
        parts.append(f"leave its volume at {_pct(d['volume_scalar'])}%")
    description = (" and ".join(parts) + ". Only this device is changed. Afterwards you can play a short test tone "
                   "to check whether you can actually hear it. Undo is available.")
    description = description[0].upper() + description[1:]
    plan = ProposalPlan(
        action=ActionKind.SET_AUDIO_ENDPOINT,
        params={"endpoint_id": d["endpoint_id"], "mute": False if d["muted"] else None,
                "volume_scalar": round(new_vol, 4) if set_volume else None,
                "expect_muted": d["muted"], "expect_volume_scalar": d["volume_scalar"]},
        target={"endpoint_id": d["endpoint_id"], "endpoint_name": d["name"]},
        preconditions={"default_endpoint_id": d["endpoint_id"], "muted": d["muted"],
                       "volume_scalar": d["volume_scalar"]},
        description=description,
        original_state={"endpoint_id": d["endpoint_id"], "muted": d["muted"], "volume_scalar": d["volume_scalar"]},
        expected_post_state={"endpoint_id": d["endpoint_id"], "muted": False, "volume_scalar": round(new_vol, 4)},
    )
    why = "muted" if d["muted"] else f"at {_pct(d['volume_scalar'])}% volume"
    return Analysis(outcome="propose", findings=findings, plan=plan,
                    explanation=f"The default playback device is {why}, which would silence most apps on it.")


def audio_matches(expected: dict[str, Any], facts: dict[str, Any]) -> bool:
    d = facts["audio"].get("default")
    return bool(d and d["endpoint_id"] == expected["endpoint_id"] and d["muted"] == expected["muted"]
                and abs(d["volume_scalar"] - expected["volume_scalar"]) <= 0.02)


def tone_plan(facts: dict[str, Any]) -> ProposalPlan | None:
    d = facts["audio"].get("default")
    if not d or d["muted"]:
        return None
    volume = round(float(d["volume_scalar"]), 4)
    return ProposalPlan(
        kind=ProposalKind.TEST,
        action=ActionKind.PLAY_TEST_TONE,
        # The approval (digest over params + preconditions) covers this endpoint, unmuted, at exactly this volume;
        # the helper re-checks all three where the tone is played.
        params={"endpoint_id": d["endpoint_id"], "duration_ms": TONE_DURATION_MS, "frequency_hz": TONE_FREQUENCY_HZ,
                "expect_muted": False, "expect_volume_scalar": volume},
        target={"endpoint_id": d["endpoint_id"], "endpoint_name": d["name"]},
        preconditions={"default_endpoint_id": d["endpoint_id"], "muted": False, "volume_scalar": volume},
        description=(f"Play a {TONE_DURATION_MS / 1000:.1f}-second test tone ({TONE_FREQUENCY_HZ} Hz, moderate level) "
                     f"on '{d['name']}' at its current {_pct(d['volume_scalar'])}% volume. Nothing else changes."),
        original_state={},
        expected_post_state={},
    )


def undo_audio(op: dict[str, Any], facts: dict[str, Any]) -> ProposalPlan:
    orig = op["original_state"]
    d = facts["audio"]["default"]
    return ProposalPlan(
        kind=ProposalKind.UNDO,
        action=ActionKind.SET_AUDIO_ENDPOINT,
        params={"endpoint_id": d["endpoint_id"], "mute": bool(orig["muted"]),
                "volume_scalar": round(float(orig["volume_scalar"]), 4),
                "expect_muted": d["muted"], "expect_volume_scalar": d["volume_scalar"]},
        target={"endpoint_id": d["endpoint_id"], "endpoint_name": d["name"]},
        preconditions={"default_endpoint_id": d["endpoint_id"], "muted": d["muted"], "volume_scalar": d["volume_scalar"]},
        description=(f"Undo the earlier repair on '{d['name']}': set it back to "
                     f"{'muted' if orig['muted'] else 'unmuted'} at {_pct(orig['volume_scalar'])}% volume."),
        original_state={"endpoint_id": d["endpoint_id"], "muted": d["muted"], "volume_scalar": d["volume_scalar"]},
        expected_post_state={"endpoint_id": d["endpoint_id"], "muted": bool(orig["muted"]),
                             "volume_scalar": round(float(orig["volume_scalar"]), 4)},
    )


# ------------------------------------------------------------------------------------------------
# C. Off-screen window
# ------------------------------------------------------------------------------------------------
def _label_matches(hint: str, cand: dict[str, Any]) -> bool:
    h = hint.strip().lower()
    if not h:
        return False
    hay = f"{cand['app_label']} {cand.get('exe', '')}".lower()
    if cand.get("is_workpad"):
        hay += " workpad notes notepad interview"
    return any(tok in hay for tok in h.replace(",", " ").split() if len(tok) >= 3)


def analyze_window(facts: dict[str, Any], answers: Answers, app_hint: str | None) -> Analysis:
    w = facts["windows"]
    cands = w.get("candidates", [])
    off = [c for c in cands if c["offscreen"]]
    off_ok = [c for c in off if c["supported"]]
    off_bad = [c for c in off if not c["supported"]]
    findings = [f"{len(w.get('monitors', []))} active display(s); {w.get('eligible_count', 0)} eligible app window(s) "
                f"found; {len(off)} of them mostly off-screen or with an unreachable title bar."]
    excl = w.get("excluded_counts", {})
    if excl.get("minimized"):
        findings.append(f"{excl['minimized']} window(s) are minimized (this workflow does not restore minimized windows).")
    for c in off_bad:
        reason = str(c["unsupported_reason"]).replace("_", " ")
        findings.append(f"'{c['app_label']}' is off-screen but unsupported here: {reason}.")
    if not off_ok:
        return Analysis(
            outcome="no_supported_cause",
            findings=findings,
            next_manual_step=("No supported off-screen window was found, so nothing was moved. Try Alt+Tab or the "
                              "taskbar; Win+Tab shows other virtual desktops. Windows that run as administrator "
                              "cannot be moved by RescueBridge."),
        )
    chosen: dict[str, Any] | None = None
    if answers.target_ref:
        chosen = next((c for c in cands if c["target_ref"] == answers.target_ref), None)
        if chosen is None:
            return Analysis(outcome="clarify", findings=findings + ["That window reference is not in the latest observation."],
                            question="Which app is missing?", options=_window_options(off_ok))
        if not chosen["offscreen"]:
            return Analysis(outcome="no_supported_cause", findings=findings + [
                f"'{chosen['app_label']}' is already {round(chosen['visible_fraction'] * 100)}% on-screen with a reachable "
                "title bar."], next_manual_step="It may be behind other windows: try Alt+Tab. Nothing was moved.")
        if not chosen["supported"]:
            return Analysis(outcome="no_supported_cause", findings=findings,
                            next_manual_step="That window is not supported by this workflow. Nothing was moved.")
    elif app_hint:
        matches = [c for c in off_ok if _label_matches(app_hint, c)]
        if len(matches) == 1:
            chosen = matches[0]
    if chosen is None and len(off_ok) == 1 and not app_hint:
        chosen = off_ok[0]
    if chosen is None:
        return Analysis(outcome="clarify", findings=findings,
                        question="Which app's window is missing? " + ", ".join(c["app_label"] for c in off_ok) + ".",
                        options=_window_options(off_ok))
    primary_work = tuple(w["primary_work_area"])
    rect = tuple(chosen["rect"])
    new_rect = geometry.placement_on(primary_work, rect)  # type: ignore[arg-type]
    width, height = new_rect[2] - new_rect[0], new_rect[3] - new_rect[1]
    resized = (width, height) != (rect[2] - rect[0], rect[3] - rect[1])
    desc = (f"Move the '{chosen['app_label']}' window back onto your main display, centered, "
            + (f"resized to {width}x{height} pixels so it fits. " if resized else f"keeping its size ({width}x{height} pixels). ")
            + "Its contents are not touched.")
    if chosen.get("is_workpad"):
        desc += " RescueBridge will then check that WorkPad's unsaved text is unchanged."
    plan = ProposalPlan(
        action=ActionKind.MOVE_WINDOW,
        params={"target_ref": chosen["target_ref"], "rect": list(new_rect),
                "monitors_fingerprint": w["monitors_fingerprint"]},
        target={"target_ref": chosen["target_ref"], "app_label": chosen["app_label"], "is_workpad": chosen["is_workpad"],
                "pid": chosen["pid"], "process_create_time": chosen["process_create_time"], "exe": chosen["exe"]},
        preconditions={"target_ref": chosen["target_ref"], "rect": chosen["rect"],
                       "monitors_fingerprint": w["monitors_fingerprint"],
                       "workpad_text_sha256": (facts.get("workpad") or {}).get("text_sha256") if chosen["is_workpad"] else None},
        description=desc,
        original_state={"rect": chosen["rect"], "visible_fraction": chosen["visible_fraction"]},
        expected_post_state={"target_ref": chosen["target_ref"], "min_visible_fraction": 0.9, "caption_reachable": True},
    )
    return Analysis(outcome="propose", findings=findings, plan=plan,
                    explanation=(f"'{chosen['app_label']}' is only {round(chosen['visible_fraction'] * 100)}% on an active "
                                 "display" + ("" if chosen["caption_reachable"] else " and its title bar is unreachable") + "."))


def _window_options(cands: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"value": c["target_ref"], "label": c["app_label"]} for c in cands[:6]]


def window_matches(expected: dict[str, Any], facts: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    cand = next((c for c in facts["windows"].get("candidates", []) if c["target_ref"] == expected["target_ref"]), None)
    if cand is None:
        return False, None
    ok = cand["visible_fraction"] >= expected["min_visible_fraction"] and cand["caption_reachable"]
    return ok, cand
