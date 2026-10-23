"""Whether a spoken or typed answer to "does it work now?" is a clear yes, a clear no, or neither.

This is the single rule for confirmations. The service applies it authoritatively before any interpreted answer
can resolve an issue (an LLM label cannot bypass it), and the keyword and combined interpreters use it too.
Anything tentative, conditional, interrogative, intermittent or contradictory is "unclear": the issue keeps
waiting for a confirmation and the person is asked again (or uses the Yes / No buttons).
"""

from __future__ import annotations

import re
from typing import Literal

Polarity = Literal["yes", "no", "unclear"]

POSITIVE = re.compile(r"\b(yes|yeah|yep|yup|heard|hear it|i can hear|works|working|it worked|that worked|can see|"
                      r"i see it|visible|fine|it'?s back|back now|fixed|correct|right one|sorted)\b", re.I)
NEGATIVE = re.compile(r"\b(no|nope|not|didn'?t|did not|doesn'?t|does not|don'?t|isn'?t|can'?t|cannot|still|nothing|"
                      r"never|wrong|broken)\b", re.I)
# A positive word in the scope of a negation is negative evidence ("not working", "doesn't work", "can't hear").
NEGATED_POSITIVE = re.compile(r"\b(?:not|never|no longer|cannot|\w+n'?t)\s+(?:\w+\s+){0,2}?"
                              r"(?:work\w*|hear\w*|see\w*|fine|fixed|visible|audible|right)\b", re.I)
TENTATIVE = re.compile(r"\b(maybe|perhaps|might|may be|i think|i guess|i suppose|i believe|probably|possibly|"
                       r"not sure|unsure|seems?|kind of|sort of|i hope|hopefully|almost)\b", re.I)
CONDITIONAL = re.compile(r"\b(if|unless|when it|once it)\b", re.I)
INTERMITTENT = re.compile(r"\b(sometimes|occasionally|on and off|off and on|intermittent(ly)?|now and then|"
                          r"comes and goes|partly|partially|half the time|a bit|not always)\b", re.I)


def confirmation_polarity(text: str) -> Polarity:
    t = (text or "").strip()
    if not t:
        return "unclear"
    if "?" in t or TENTATIVE.search(t) or CONDITIONAL.search(t) or INTERMITTENT.search(t):
        return "unclear"
    positive = bool(POSITIVE.search(NEGATED_POSITIVE.sub(" ", t)))
    negative = bool(NEGATIVE.search(t))
    if positive and negative:
        return "unclear"  # contradictory: "it works, but I still can't hear anything"
    if positive:
        return "yes"
    if negative:
        return "no"
    return "unclear"


def looks_like_an_answer(text: str) -> bool:
    """True when the words are about the confirmation at all (so an unclear one deserves a follow-up question)."""
    t = text or ""
    return bool(POSITIVE.search(t) or NEGATIVE.search(t) or TENTATIVE.search(t) or INTERMITTENT.search(t)
                or "?" in t)
