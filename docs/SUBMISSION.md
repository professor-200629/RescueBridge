# Submission draft — Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track)

**Submitted on Devpost on 23 October 2026, 21:33 IST** (confirmation email from Devpost): https://devpost.com/software/rescuebridge-fvari0. Track: Alexa+. Editable until the deadline, 24 October 2026, 00:30 IST.

| Item | Value |
|---|---|
| Track | Alexa+ (self-hosted MCP server, protocol 2025-11-25, Streamable HTTP) with an independent web simulator |
| Mini challenges | none entered |
| Code repository | https://github.com/professor-200629/RescueBridge (public, Apache-2.0 `LICENSE`) |
| Demo video | https://youtu.be/xQFmAb1c6qg (public on YouTube, 1:57) |
| Deadline | Friday 23 October 2026, 12:00 PT = 24 October 00:30 IST (target: 23 October 21:00 IST) |

## Rules recheck

Retrieved 2026-10-20 around 23:45 IST in a regular browser (an automated fetch returned HTTP 403):
`https://amazonappdev2026.devpost.com/rules`, `/details/faqs`, `/resources`.

- Alexa+: "A working Agent Skill or a self-hosted MCP server, implementing MCP spec version 2025-11-25 (or a
  later version, once confirmed) over Streamable HTTP." A simulated Alexa+ experience is an allowed
  alternative path.
- The FAQ confirms a web page acting as a real MCP client (initialize, tools/list, tools/call over Streamable
  HTTP) satisfies the requirement; gated Alexa+ tools are select-partners only; hosting is not required.
- Repo must contain source, assets and setup/run instructions; public repos need a visible OSS license.
- Video < 3 minutes, public on YouTube or Vimeo, showing the project functioning.
- Product feedback for each tool is required; friction log entries are optional with up to a 10% bonus.
- English materials. India is not in the excluded list.
- Dated updates seen on the pages: "September 16, 2026 UPDATE: Hackathon submission requirements: Code
  repository" and "October 7th Update: … out of credit codes". No change affects this plan.

## Project description (draft)

**RescueBridge — a second channel for getting your Windows laptop back.**
When your clicks do the wrong thing, the sound is silent, or a window has drifted off-screen, the usual
fix needs exactly the thing that is broken. RescueBridge lets you talk to your laptop from your phone. A
self-hosted MCP server exposes nine goal-oriented recovery tools. A narrow Windows helper, running as you,
observes the real state. You get one focused question at a time and an exact proposal, and nothing changes
until you tap Approve on your paired phone. After a change, RescueBridge looks again and asks you to confirm
with a real check: a test tone, a test click, or "can you see it". Stop works at any moment and is enforced by
the helper, not just the UI.

What makes it different is what it refuses to do. There is no remote mouse or keyboard control and no shell.
The model cannot approve anything. API success is never reported as "fixed", and partial recovery is
reported as partial. Evidence is labelled Real Windows / Fixture Simulation / Controlled Live Lab.

How it uses the track technology: the browser simulator's backend is a real MCP client (SDK 2.3.0,
initialize → tools/list → tools/call, negotiated protocol 2025-11-25 over Streamable HTTP) talking to
RescueBridge's MCP server; any MCP host with a device-bound bearer token can call the same tools.

## Testing instructions for judges

1. Windows 10/11, Python 3.13, uv, Node.js. `git clone <repo>`; `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`.
2. Safe simulation (no Windows changes): `powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Fixture -Scenario interview`.
   The host console opens; create a pairing code; open `http://localhost:8740/` in another browser profile
   (or an Android phone by USB cable: add `-Usb`; LAN/Wi-Fi mode exists but is untested on a real phone), enter
   the code, accept on the host console; type "My clicks are wrong, I can't hear anything and my notes
   disappeared". Without installing anything: the unpaired start page's **Try a simulated recovery**.
3. Real Windows, read-only until you approve: `scripts\start.ps1` (same pairing). Nothing changes until you
   approve a proposal on the paired device.
4. Automated: `scripts\check.ps1`; `rescuebridge eval --sets fixture,heldout`.

## Track fit

- Self-hosted MCP server, Streamable HTTP, protocol 2025-11-25 (verified in tests and recorded per agent run).
- Independent Alexa+ concept simulator: voice-first phone UI with captions, single focused questions, explicit
  approval and Stop. It is not an Alexa product.
- Maintains state across sessions and transport reconnects (device-bound missions in SQLite).
- **MCP Apps / cards:** `get_recovery_status` ships a read-only recovery card as an MCP App
  (`ui://rescuebridge/recovery-card`, `text/html;profile=mcp-app`, ui protocol 2026-01-26). The simulator hosts it
  in a sandboxed frame after the `ui/initialize` handshake; an Edge end-to-end test checks it renders the live
  status and refreshes through `tools/call`. Approval deliberately stays on the paired phone, not in the card.

## What the evidence is (do not overstate it in the description or video)

- **Automated, fixture OS:** 210 tests (3 read real Windows state without changing it) and 30 scripted scenarios with a simulated person (`VALIDATION.md` 1, 3, 5k, 5l).
- **Real devices, the owner's only** (one laptop, one phone; by the owner or by Claude at the owner's request):
  unmute, test tone, guarded Undo and WorkPad window move on real Windows; QR pairing, voice and approvals on
  the phone over USB (`VALIDATION.md` 5c–5j).
- **Independent participants: none.** Not user-tested by anyone else.
- **Not verified for real:** mouse repair and click test, volume change, Wi-Fi/LAN phone, screen readers, a
  third-party MCP Apps host.
- **Demo video:** https://youtu.be/xQFmAb1c6qg. Real laptop under the live lab. Part 1: the owner's real phone over USB, the owner speaks, approves and answers (the laptop microphone filtered most of the test tone out). Part 2: phone app in a phone-sized browser, typed and tapped by a script. Synthetic voice; waits cut and labelled (`VALIDATION.md` 5m).

## Pending before submission

- [x] Live-lab runs for real changes: audio (incl. Undo) and WorkPad (`VALIDATION.md` 5f, 5j). Mouse not run.
- [x] Real phone test over USB (QR pairing, microphone, speech) — `VALIDATION.md` 5c–5j. Wi-Fi/LAN not tested.
- [x] Publish GitHub repository (public, Apache-2.0).
- [x] Commit and push the 2026-10-23 audit fixes (`VALIDATION.md` 5k).
- [x] Record and upload the demo (public on YouTube).
- [x] Re-read the official pages on submission day (requirements, schedule: judging 27 Oct – 21 Nov, winners 4 Dec 01:30 IST).
- [x] Submit on Devpost (https://devpost.com/software/rescuebridge-fvari0); English captions uploaded to the video.
