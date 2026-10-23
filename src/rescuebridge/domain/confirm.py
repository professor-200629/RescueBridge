"""Whether a spoken or typed answer to "does it work now?" is a clear yes, a clear no, or neither.

This is the single rule for confirmations. The service applies it authoritatively before any interpreted answer
can resolve an issue (an LLM label cannot bypass it), and the keyword and combined interpreters use it too.

A **yes** must be an unambiguous statement about now: the whole utterance has to consist of recognised present
confirmations ("yes", "it works now", "I heard the tone", "it's back on my screen") plus filler ("thanks",
"great"). Finding a positive word somewhere is not enough: "It was working yesterday" and "I wish it worked"
contain one but confirm nothing. Anything tentative, conditional, interrogative, intermittent, time-shifted,
wishful, second-hand, deferred or contradictory is "unclear": the issue keeps waiting and the person is asked
again (or uses the Yes / No buttons). A **no** needs negative evidence, no positive evidence, and none of those
qualifiers. Unknown phrasings are "unclear" by default: asking again is cheap, a false "fixed" is not.
"""

from __future__ import annotations

import re
from typing import Literal

Polarity = Literal["yes", "no", "unclear"]

POSITIVE = re.compile(r"\b(yes|yeah|yep|yup|heard|hear it|i can hear|works|working|it worked|that worked|can see|"
                      r"i see it|visible|fine|it'?s back|back now|fixed|correct|right one|sorted)\b", re.I)
NEGATIVE = re.compile(r"\b(no|nope|not|didn'?t|did not|doesn'?t|does not|don'?t|isn'?t|can'?t|cannot|still|nothing|"
                      r"never|wrong|broken|(?:could|would|was|were|are|has|have|wo|ain)n'?t)\b", re.I)
# A positive word in the scope of a negation is negative evidence ("not working", "doesn't work", "can't hear").
NEGATED_POSITIVE = re.compile(r"\b(?:not|never|no longer|cannot|\w+n'?t)\s+(?:\w+\s+){0,2}?"
                              r"(?:work\w*|hear\w*|see\w*|fine|fixed|visible|audible|right)\b", re.I)
TENTATIVE = re.compile(r"\b(maybe|perhaps|might|may be|i think|i guess|i suppose|i believe|probably|possibly|"
                       r"not sure|unsure|seems?|kind of|sort of|i hope|hopefully|almost|could)\b", re.I)
CONDITIONAL = re.compile(r"\b(if|unless|when it|once it|as long as|provided)\b", re.I)
INTERMITTENT = re.compile(r"\b(sometimes|occasionally|on and off|off and on|intermittent(ly)?|now and then|"
                          r"comes and goes|partly|partially|half the time|a bit|not always)\b", re.I)
# About another time than now: the past state ("was working", "yesterday", "used to") or the future ("will").
TIME_SHIFTED = re.compile(r"\b(yesterday|earlier|before|previously|ago|used to|last (night|week|time|month|year)|"
                          r"this morning|the other day|at first|initially|until|anymore|any more|for now|for a (second|"
                          r"moment|minute|while|bit)|tomorrow|later|will|gonna|going to|was|were|had)\b|'ll\b", re.I)
# Wishes, obligations, other people's opinions: none of them says what the person observes now.
WISHFUL_OR_REPORTED = re.compile(r"\b(wish|wishing|hope|want|wanted|would|should|supposed to|ought|needs? to|must|"
                                 r"if only|try|trying|says|said|told|tells|claims?|reckons?|according to)\b", re.I)
DEFERRED = re.compile(r"\b(wait|hold on|let me|let's see|one (sec|second|moment|minute)|checking|not yet|not now|"
                      r"i'?ll (check|see|tell))\b", re.I)
CONTRAST = re.compile(r"\b(but|though|although|except|however|only on|only in)\b", re.I)
# Negative words that are not a "no" to the question.
IDIOM = re.compile(r"\b(no (problems?|issues?|worries|idea|clue)|not (too )?bad|can'?t complain|never ?mind)\b", re.I)

# --- the grammar of a present-tense yes ---------------------------------------------------------------------
_FILLER = (r"(?:ok(?:ay)?|oh|ah|great|perfect|good|cool|nice|awesome|wonderful|brilliant|excellent|lovely|amazing|"
           r"yay|wow|finally|alright|all right|sure|thanks|thank you(?: (?:so|very) much)?|cheers|well|so|hey|hi|"
           r"now|alexa|rescuebridge)")
_CORE = (r"(?:yes|yeah|yep|yup|yes sir|correct|that'?s right|that is right|affirmative|definitely|absolutely|"
         r"of course|indeed|it does|it did|i did|i do|i can|sure does)")
_SUBJECT = (r"(?:it|that|this|they|both|everything|all|workpad|sound|audio|(?:the|my) (?:sound|audio|tone|beep|test tone|"
            r"speakers?|volume|mouse|clicks?|left click|buttons|mouse buttons|window|notes|app|workpad|fix|repair))")
_STATE = (r"(?:working|fixed|back|fine|ok(?:ay)?|good|right|correct|normal|visible|there|on screen|playing|"
          r"back on (?:my|the) screen)")
_STATEMENT = (rf"{_SUBJECT}(?:(?:'s|\s+is|\s+are)\s+{_STATE}|\s+(?:works|work|worked|plays|played|came back|"
              r"got fixed|did it|did the trick|helped|sounds (?:fine|good|right)|looks (?:fine|good|right)))")
_PERCEPTION = (r"(?:i )?(?:can )?(?:hear|heard|see|saw|found) (?:it|that|this|them|something|sound|everything|"
               r"(?:the|a) (?:tone|beep|sound|test tone|window|notes|app|workpad)|my (?:notes|window|workpad|app))")
_BARE = r"(?:works|working|fixed|all good|all fixed|all sorted|sorted|all working|loud and clear|crystal clear)"
_TRAIL = (r"(?:now|right now|just now|again|fine|perfectly|great|well|properly|clearly|loud and clear|too|as well|"
          r"thanks|thank you|yes|on (?:my|the) screen|back on (?:my|the) screen|on screen)")
_MAIN = rf"(?:{_CORE}\s+)*(?:{_STATEMENT}|{_PERCEPTION}|{_BARE}|{_CORE})"
YES_CHUNK = re.compile(rf"(?:{_FILLER}\s+)*{_MAIN}(?:\s+(?:and\s+)?(?:{_MAIN}|{_TRAIL}))*")
FILLER_CHUNK = re.compile(rf"{_FILLER}(?:\s+{_FILLER})*")


def _normalize(text: str) -> str:
    t = (text or "").lower().replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", t).strip()


def _is_present_yes(t: str) -> bool:
    """Every chunk is a recognised present confirmation or filler, and at least one is a confirmation."""
    chunks = [c.strip() for c in re.split(r"[,.!;:]+|\s+-\s+", t) if c.strip()]
    found = False
    for c in chunks:
        if YES_CHUNK.fullmatch(c):
            found = True
        elif not FILLER_CHUNK.fullmatch(c):
            return False
    return found


def confirmation_polarity(text: str) -> Polarity:
    t = _normalize(text)
    if not t:
        return "unclear"
    if "?" in t or any(p.search(t) for p in (TENTATIVE, CONDITIONAL, INTERMITTENT, TIME_SHIFTED, WISHFUL_OR_REPORTED,
                                              DEFERRED, CONTRAST, IDIOM)):
        return "unclear"
    positive = bool(POSITIVE.search(NEGATED_POSITIVE.sub(" ", t)))
    if NEGATIVE.search(t):
        return "unclear" if positive else "no"  # "yes and no", "it works, but I still can't hear" -> unclear
    return "yes" if _is_present_yes(t) else "unclear"


def looks_like_an_answer(text: str) -> bool:
    """True when the words are about the confirmation at all (so an unclear one deserves a follow-up question)."""
    t = text or ""
    return bool(POSITIVE.search(t) or NEGATIVE.search(t) or TENTATIVE.search(t) or INTERMITTENT.search(t)
                or "?" in t or re.search(r"\b(work|hear|see)\w*", t, re.I))
