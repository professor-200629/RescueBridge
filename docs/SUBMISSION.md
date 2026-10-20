# Submission draft — Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track)

**Nothing has been submitted.** URLs below are pending until Balu publishes them.

| Item | Value |
|---|---|
| Track | Alexa+ (self-hosted MCP server, protocol 2025-11-25, Streamable HTTP) with an independent web simulator |
| Mini challenges | none entered |
| Code repository | `PENDING — GitHub URL not created yet` (public with Apache-2.0 `LICENSE`, or private shared with the reviewers listed in the FAQ) |
| Demo video | `PENDING — not recorded` (public YouTube/Vimeo, < 3 min; plan in `DEMO_SCRIPT.md`) |
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
   (or a phone in LAN mode), enter the code, accept on the host console; type "My clicks are wrong, I can't
   hear anything and my notes disappeared".
3. Real Windows, read-only until you approve: `scripts\start.ps1` (same pairing). Nothing changes until you
   approve a proposal on the paired device.
4. Automated: `scripts\check.ps1`; `rescuebridge eval --sets fixture,heldout`.

## Track fit

- Self-hosted MCP server, Streamable HTTP, protocol 2025-11-25 (verified in tests and recorded per agent run).
- Independent Alexa+ concept simulator: voice-first phone UI with captions, single focused questions, explicit
  approval and Stop. It is not an Alexa product.
- Maintains state across sessions and transport reconnects (device-bound missions in SQLite).

## Pending before submission

- [ ] Owner-run live-lab rehearsal for real changes (`LIVE_LAB.md`), then update `VALIDATION.md`.
- [ ] Real phone test over LAN (certificate, microphone, speech recognition) and update `VALIDATION.md`.
- [ ] Publish GitHub repository; check the license is visible; add URL above.
- [ ] Record and upload the demo; add URL above.
- [ ] Re-read the official pages on submission day.
