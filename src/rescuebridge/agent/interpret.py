"""Deterministic keyword interpreter ("rules" provider). Not a language model.

Maps an utterance to symptom categories, clarification answers, confirmations, Stop and Undo requests.
It is intentionally simple and is reported as a baseline; its accuracy on held-out phrasings is measured
separately rather than assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("mouse_not_moving", re.compile(
        r"\b(mouse|pointer|cursor|arrow)\b[^.?!]{0,30}\b(not|n't|won'?t|doesn'?t|isn'?t|can'?t|cannot|never)\b[^.?!]{0,15}"
        r"\b(move|moving|moves|budge|respond)|\b(frozen|stuck|dead)\b[^.?!]{0,10}\b(mouse|pointer|cursor)|"
        r"\b(mouse|pointer|cursor)\b[^.?!]{0,15}\b(frozen|stuck|dead)\b", re.I)),
    ("mouse_buttons_wrong", re.compile(
        r"\b(click|clicks|clicking|clicked|right[- ]?click|left[- ]?click|mouse buttons?|buttons? (are|is) "
        r"(swapped|reversed|backwards|wrong)|context menu|menu (pops|opens|appears|keeps))\b", re.I)),
    ("no_sound", re.compile(
        r"\b(hear|hearing|sound|sounds|audio|muted?|silent|silence|speakers?|volume|quiet|can'?t hear|no noise)\b", re.I)),
]

KNOWN_APPS = ["workpad", "notes", "notepad", "word", "excel", "chrome", "edge", "firefox", "teams", "zoom",
              "outlook", "explorer", "vscode", "code", "slack", "powerpoint"]

_THING = r"(notes|app|apps|application|document|doc|file|program|editor|" + "|".join(KNOWN_APPS) + r")"
# Includes speech-recognition renderings of "disappeared" seen on a real phone ("my notes is appeared") and
# common misspellings. A false match only starts a read-only inspection; changes still need an observed cause.
_LOST = (r"(diss?app?ear(ed|s|ing)?|(is|this|dis|des) appeared|vanish(ed|es)?|gone|missing|off[- ]?screen|lost|"
         r"closed by itself|not there|not visible|invisible)")
CATEGORY_PATTERNS.append(("window_missing", re.compile(
    r"\b(window|windows|off[- ]?screen|workpad)\b|"
    rf"\b{_LOST}\b[^.?!]{{0,40}}\b{_THING}\b|\b{_THING}\b[^.?!]{{0,40}}\b{_LOST}\b|"
    rf"\b(can'?t|cannot|couldn'?t) (see|find)\b[^.?!]{{0,30}}\b{_THING}\b|\bwhere('?s| is) my\b[^.?!]{{0,20}}\b{_THING}\b",
    re.I)))

STOP_RE = re.compile(r"^\s*(stop|cancel|halt|abort|don'?t do (it|that|anything)|stop everything)\b", re.I)
UNDO_RE = re.compile(r"\b(undo|revert|put it back|change it back|roll ?back)\b", re.I)
YES_RE = re.compile(r"\b(yes|yeah|yep|yup|i (can )?hear it|heard it|it works|works now|working now|that worked|"
                    r"i can see it|i see it|it'?s (back|visible|fine|working))\b", re.I)
NO_RE = re.compile(r"\b(no|nope|didn'?t|did not|can'?t hear|cannot hear|not working|still (broken|wrong|silent|"
                   r"can'?t|cannot|no)|nothing)\b", re.I)
LEFT_HANDED = re.compile(r"\bleft[- ]?hand(ed)?\b", re.I)
RIGHT_HANDED = re.compile(r"\bright[- ]?hand(ed)?\b", re.I)
WANT_LEFT = re.compile(r"\b(left (button|click|one|side)|use the left|normal(ly)?|usual|default|regular|standard)\b", re.I)
WANT_RIGHT = re.compile(r"\b(right (button|click|one|side)|use the right)\b", re.I)
PERCENT = re.compile(r"\b(\d{1,3})\s*(%|percent)\b", re.I)


@dataclass
class Interpretation:
    categories: list[str] = field(default_factory=list)
    app_hint: str | None = None
    stop: bool = False
    undo: bool = False
    yes: bool = False
    no: bool = False
    primary_button: str | None = None
    volume_percent: int | None = None
    ambiguous_answer: bool = False  # two interpreters disagreed about a consequential answer


def interpret(text: str) -> Interpretation:
    t = text.strip()
    it = Interpretation()
    it.stop = bool(STOP_RE.search(t))
    it.undo = bool(UNDO_RE.search(t))
    neg_only = NO_RE.search(t)
    it.yes = bool(YES_RE.search(t)) and not neg_only
    it.no = bool(neg_only) and not bool(YES_RE.search(t))
    for cat, pat in CATEGORY_PATTERNS:
        if pat.search(t):
            if cat == "mouse_buttons_wrong" and "mouse_not_moving" in it.categories and not re.search(r"click", t, re.I):
                continue
            it.categories.append(cat)
    low = t.lower()
    for app in KNOWN_APPS:
        if re.search(rf"\b{re.escape(app)}\b", low):
            it.app_hint = app
            break
    if LEFT_HANDED.search(t):
        it.primary_button = "right"
    elif RIGHT_HANDED.search(t):
        it.primary_button = "left"
    elif WANT_RIGHT.search(t) and not WANT_LEFT.search(t):
        it.primary_button = "right"
    elif WANT_LEFT.search(t):
        it.primary_button = "left"
    if m := PERCENT.search(t):
        it.volume_percent = int(m.group(1))
    return it
