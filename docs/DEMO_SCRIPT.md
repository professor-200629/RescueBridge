# Demo script (target < 3:00) — proposal, not a recording

Nothing here has been recorded yet. Times are targets; adjust to real measured latency and **do not speed up or
cut footage to imply faster or more autonomous behaviour**. Label every cut. Keep the
"Independent Alexa+ concept simulator" label and the mode badge (Controlled Live Lab / Fixture Simulation) on
screen.

## Before recording (owner-run, ~5 min)

1. Close personal apps and notifications (no personal windows, titles, or messages on screen).
2. `scripts\start.ps1 -Usb` with the phone on a USB cable (verified transport; or `-Lan` for Wi-Fi), pair the
   phone by scanning the QR code, open WorkPad
   (`rescuebridge workpad`) and leave its synthetic notes visible for a moment.
3. Arm the lab in a visible terminal: `rescuebridge lab arm --session demo-1 --minutes 15 --allow audio,workpad`
   (add `mouse` only for the optional mouse segment).
4. Screen-record the laptop **with system audio** (so the test tone is audible) and the phone screen
   (Samsung screen recorder) or film both with a camera.

## Script

| Time | Shot | What happens (all real effects come from the armed live lab) |
|---|---|---|
| 0:00–0:15 | Balu to camera / laptop | "I once had a mouse problem that made my laptop hard to use. RescueBridge is a second channel: my phone." Caption: *Faults injected by RescueBridge's live lab (audio + WorkPad) for this demo.* Run `lab inject audio-mute` and `lab inject workpad-offscreen` on camera. |
| 0:15–0:45 | Phone | Tap **Talk**: "My interview starts soon. I can't hear anything and my notes disappeared." Show the editable transcript, **Send**. Cards: *Sound — muted* and *Missing window — WorkPad 0 % on screen*, each with an exact proposal. Badge: **Controlled Live Lab**. |
| 0:45–1:15 | Phone + laptop | Read the Sound proposal aloud, tap **Approve and apply** → "Done, and observed: unmuted". Tap **Approve and play** → tone audible → say "yes I heard it" → card shows **Resolved — you confirmed**; evidence shows before/after separately from "Your result". |
| 1:15–1:40 | Phone + laptop | Approve the WorkPad proposal → WorkPad reappears with the same notes; evidence line "WorkPad's unsaved text: unchanged (same content fingerprint)". Say "yes I can see it". |
| 1:40–2:05 | Phone | Honest failure: "and my pointer is frozen" → *Not supported* with the manual next step, nothing changed. Optional (if mouse scope armed): swapped buttons → question → "I'm right-handed" → approve → click-test target → confirm. |
| 2:05–2:25 | Phone | Press **Stop**: "Stop requested" → "Stopped — the laptop helper confirmed it will reject further changes". Show that a stale proposal can no longer be approved. |
| 2:25–2:55 | Slides / screen | Architecture (phone → backend acting as a real MCP client → MCP server 2025-11-25 Streamable HTTP → current-user helper). Evidence: test count, fixture evaluation numbers, interpreter benchmark, and what is NOT verified (phone mic if not shown, other faults). Next step: real-user trial with the prepared protocol. |

## Rules for the recording

- If the local LLM is used, show the real wait (~5–6 s per request on the test laptop) or label any cut
  ("cut: 5 s of processing removed").
- If phone voice recognition fails, type and say so on screen. Do not fake recognition.
- If a segment is shown in Fixture Simulation, keep the **Fixture Simulation** badge visible and say it.
- Restore the lab at the end (`lab restore` / Ctrl+C in the arming window) and keep that on screen briefly.
- No third-party music or trademarks beyond factual mentions; no claims of Amazon endorsement.
