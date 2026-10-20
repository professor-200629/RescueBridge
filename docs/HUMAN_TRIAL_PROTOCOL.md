# Human trial protocol (ready to run — zero human participants so far)

No human participants have used RescueBridge yet. No results exist. This protocol is prepared so a small,
informal usability check can be run honestly later.

## Purpose

Learn whether people can recover from the three supported problems using the phone channel, where they get
stuck, and whether they understand approval, Stop, and "confirm it yourself". This is not a clinical or
accessibility-efficacy study and must not be reported as one.

## Participants and consent

- 3–5 adults who use Windows; record only a participant number (P1…), not names.
- Read aloud: "This is a prototype. We will create harmless, reversible problems on this test laptop (mute, a
  moved demo window, optionally swapped mouse buttons). You can stop at any time. We record your answers on
  paper and the app's own logs on this laptop, not audio or video unless you agree separately."
- Use the owner's test laptop, a synthetic WorkPad document, and the live lab armed for the session.

## Tasks (one at a time, order varied)

1. "You are about to join an interview but cannot hear anything. Use the phone to fix it."
2. "Your notes window has disappeared. Get it back without closing anything."
3. (Optional, only if the participant is comfortable) "Your clicks behave strangely. Use the phone."
4. "Something else is wrong: your pointer is frozen." (unsupported; observe how they react)

The facilitator injects the fault with `rescuebridge lab inject …` before each task and restores after.

## Recording sheet (per task)

| Field | Value |
|---|---|
| Participant / task | |
| Start time / end time | |
| First words used (paraphrase) | |
| Interpreted correctly on first try? (Y/N) | |
| Needed the on-screen buttons instead of voice? (Y/N) | |
| Read the proposal before approving? (observed / asked) | |
| Approved / declined / stopped | |
| Observed system result (from the app's evidence) | |
| Person's own result (heard / saw / clicks OK) | |
| Any moment they thought it was fixed when it was not? | |
| Confusion points (verbatim, short) | |
| Facilitator help needed (none / hint / took over) | |

## After the session

- Ask: "What did Approve mean to you?", "What did Stop do?", "Would you trust this before an interview?".
- Restore the lab, check `lab status`, and delete the session's data if the participant asks.
- Report counts exactly as observed, including failures; keep fixture results separate.
