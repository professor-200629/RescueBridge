# Demo video script (under 3:00)

Nothing has been recorded yet. Everything below uses steps that already worked on the owner's laptop
(`VALIDATION.md` 5e–5h). **Do not speed up or cut footage to make it look faster or more automatic**; if you cut
a wait, put "cut: N s removed" on screen. Keep the "Independent Alexa+ concept simulator" label and the mode badge
(**Controlled Live Lab** during the faults) visible. No claims of Amazon endorsement.

Run these in PowerShell inside the RescueBridge folder. All commands use the real-mode data folder in which the phone is already paired:
`$env:LOCALAPPDATA\RescueBridge-real` (written as `DATA` below).

## Before recording (about 10 minutes)

1. Plug the phone in with the USB cable. Turn on Do Not Disturb on the phone. Close personal apps and
   notifications on the laptop (nothing private on screen).
2. Start RescueBridge (real Windows, phone over USB):
   `powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Usb -DataDir $env:LOCALAPPDATA\RescueBridge-real`
   If it says the phone is not linked, run:
   `.venv\Scripts\python.exe -m rescuebridge.cli --data-dir $env:LOCALAPPDATA\RescueBridge-real usb-link`
3. On the phone, open `http://127.0.0.1:8740/` in Chrome (already paired). Check the badge says **Real Windows**.
4. Open WorkPad (window 1, leave it open):
   `.venv\Scripts\python.exe -m rescuebridge.cli --data-dir $env:LOCALAPPDATA\RescueBridge-real workpad`
5. Arm the test lab for 15 minutes (window 2, leave it open):
   `.venv\Scripts\python.exe -m rescuebridge.cli --data-dir $env:LOCALAPPDATA\RescueBridge-real lab arm --session demo-1 --minutes 15 --allow audio,workpad`
6. Recording: phone → Samsung **Screen recorder** (quick panel; sound: media). Laptop → **Snipping Tool**
   video (Win+Shift+R, whole screen, with audio) so the test tone is heard. Or film both with a second phone.

## Script

| Time | Show | Do and say |
|---|---|---|
| 0:00–0:15 | You / laptop | "When your laptop's sound, mouse or a window breaks, you usually need the broken thing to fix it. RescueBridge is a second channel: my phone." Caption: *Real laptop. Faults created by RescueBridge's test lab for this demo.* |
| 0:15–0:25 | Laptop, window 3 | Run `lab inject audio-mute` and `lab inject workpad-offscreen` (same `--data-dir`). The sound mutes and WorkPad disappears. |
| 0:25–0:55 | Phone | Tap the **orb**, say: "My interview starts soon. I can't hear anything and my notes disappeared." Check the words, tap **Send**. Show the short reply caption, the progress line, and the two cards. Badge: **Controlled Live Lab**. |
| 0:55–1:25 | Phone + laptop | Sound card: read the exact change, tap **Approve and apply** → "Done, and observed: unmuted". Tap **Approve and play** → the tone plays on the laptop → tap **Yes, it works**. Point at **BEFORE / AFTER**. |
| 1:25–1:50 | Phone + laptop | Window card: tap **Approve and apply** → WorkPad comes back to the middle of the screen with the same notes → "WorkPad's unsaved text: unchanged". Tap **Yes, it works**. The session bar shows all confirmed. |
| 1:50–2:05 | Phone | Open **Alexa+ card view (MCP App)**: "This card is not drawn by the phone page. The MCP server ships it as an MCP App, so any MCP Apps host can show it. Approvals stay on my phone." |
| 2:05–2:20 | Phone | Tap **STOP all changes** → "Stopped — the laptop helper confirmed it will reject further changes." Say: "Nothing changes without my approval, and Stop is enforced on the laptop." |
| 2:20–2:50 | Screen (README) | Architecture: phone → backend (a real MCP client) → RescueBridge MCP server (protocol 2025-11-25, Streamable HTTP, MCP App card) → Windows helper running as me. Evidence: 141 automated tests (simulated Windows); 24/24 simulated scenarios with 0 wrong changes and 0 false "fixed" claims (a naive "just fix it" baseline made 4 wrong changes and 7 false claims); real repairs verified on this laptop. Honest limits: mouse repair not yet shown on real Windows; not yet tried by anyone but me; Windows only; English only. |
| 2:50–3:00 | Laptop, window 2 | Press **Ctrl+C** in the lab window (restores and disarms). "RescueBridge — fix your laptop from your phone, safely." |

## If something goes wrong while recording

- Voice not recognised: tap an example phrase or type, and say "typing instead". Never fake recognition.
- A step fails: say what happened and show it; do not cut it out to look successful.
- Anything stuck: Ctrl+C in window 2 (lab restores), then `scripts/stop.ps1 -DataDir …`.

## After recording

Upload to YouTube as **Public** (rules: public on YouTube or Vimeo, under 3 minutes). Send Claude the link to
put in `SUBMISSION.md`.
