# RescueBridge — durable checkpoint

Read this first after any context reset, then `spec/RescueBridge-Claude-Code-Build-Prompt.md` (original
spec, SHA-256 3C4EC4EF…9A8E), `docs/VALIDATION.md`, `docs/KNOWN_LIMITATIONS.md`.

## Environment (observed 2026-10-20)

Windows 11 Home 10.0.26300, HP Pavilion 16, Core Ultra 5 125U, 16 GB RAM (often only 1–3 GB free), Intel iGPU.
Standard (non-admin) user account, Medium integrity. Python 3.13.0 via uv 0.12.9; Node 24.14.0; Ollama 0.32.3 with
qwen2.5:3b-instruct and llama3.2:3b (no downloads by this project). MCP SDK 2.3.0 (handshake max 2025-11-25).

## Gate status

| Gate | Status |
|---|---|
| 0 Inspect + plan | done |
| 1 Vertical slice | done for fixture (all 3 workflows, approve → apply → verify → person result) and real Windows read-only. Real Windows **changes** on the owner's laptop, approved on the owner's phone: unmute, tone, guarded Undo, WorkPad window move (VALIDATION 5e, 5f, 5j). Not on real Windows: mouse swap, click test, volume change. Phone: USB verified (QR pairing, voice, approvals; 5c–5e, 5j). Wi-Fi/LAN phone: not tested. |
| 2 Domain engine + adapters | done: SQLite state, proposals/digests/approvals, fence with admission gate (5k), idempotent apply, reconciliation, guarded Undo, 3 recipes, real + fixture adapters, named-pipe helper |
| 3 UX + model/voice | browser app done; phone microphone and speech used by the owner (5c, 5e); local LLM measured (tool-calling 0/8; schema interpretation 20/20 held-out v1 symptoms) |
| 4 Validation + submission | tests/eval/bench/docs and live lab done; repo published, including the 2026-10-23 audit fixes; pending: video, independent participants (none so far), Devpost submission |

## Last verified checks (2026-10-23)

See `docs/VALIDATION.md` 5k and 5l. `pytest` 210 passed (incl. Edge browser, helper over the real pipe, real Windows
read-only); ruff and mypy clean; web typecheck + build pass; fixture evaluation 24/24, held-out 2/6 (keyword),
0 incorrect changes, 0 false claims; clean clone: `uv sync --frozen` picks Python 3.13.0 from `.python-version`
with no warning (warm uv cache).

## 2026-10-21 update

Owner's first phone attempt: the QR code did not open (without `-Lan` it encodes `http://127.0.0.1:8740`,
the phone itself). Fixed with USB cable mode (`be3b822`): `start.ps1 -Usb` keeps `adb reverse tcp:8740 tcp:8740`
(re-added within 10 s after a replug while the host console is open), checks from the phone with its own
`curl`, host console shows "Phone by USB cable: linked"; processes now run hidden with logs in
`<data>\logs`. 79 tests pass. Owner's phone (Samsung SM-A366E, Android 16) has USB debugging authorized and
adb at `C:\platform-tools-latest-windows\platform-tools` (on PATH).

Then the owner scanned the QR code, paired, and spoke one problem on the phone (recognised imperfectly); Claude,
at the owner's request, drove the phone's RescueBridge tab over adb-forwarded CDP through every fixture flow
and fixed 7 defects (`aae0f76`, VALIDATION 5c/5d). 81 tests pass. Not done: real Windows from the phone (the
session's permission policy blocked the real-mode host console), voice without the owner (the laptop voice did
not reach the phone mic), any real Windows change (live lab never armed). (All but the second were done later
that day: 5e, 5f, 5j.)

## 2026-10-21 night: review repairs

Six review items reproduced in Edge, then fixed (VALIDATION 5i): persistent Send errors + reconciliation,
first-reply speech, monotonic `state_seq` snapshots (stale-after-Stop rejected, no overlapping polls), pairing
validation + distinct errors, first-run guidance + `scripts\host-console.ps1`, and the browser-only
"Try a simulated recovery" preview (`web/src/preview-data.json`, regenerate with `scripts\make_preview_data.py`).
103 tests pass. Live instance restarted (real mode, `RescueBridge-real`); phone was unplugged at restart.

## 2026-10-23: audit fixes (committed and pushed at the owner's request)

An independent audit of `424acea` reproduced four defects, all fixed with deterministic tests (VALIDATION 5k):
Stop admission gate at the OS-call boundary (`tests/test_stop_fence.py`), hedged answers no longer resolve
issues (`domain/confirm.py`, `tests/test_confirmation.py`), test tone bound to the approved volume
(`tests/test_tone_binding.py`), `.python-version` without BOM. No real Windows change was made. The running
instance (if any) still runs the old code until restarted (none was running when the fixes were committed).

A second review of `68f98b9` reproduced two more defects, both fixed (VALIDATION 5l): a timed-out Windows call
was dropped from Stop's in-flight tracking and could still change the setting after Stop
(`tests/test_helper_timeouts.py`), and "It was working yesterday" / "I wish it worked" resolved an issue (a yes
must now be a recognised present-tense confirmation).

## Next actions (in order)

1. (done 2026-10-21, VALIDATION 5f) live-lab WorkPad rehearsal: real window move verified. WorkPad's Tk
   start-up in the venv was broken and is fixed. Owner still has to answer the phone's "can you see it?".
2. (done 2026-10-21) phone over USB: QR pairing, voice, real unmute + tone (VALIDATION 5c–5e).
3. (done 2026-10-21 evening) futuristic redesign (5g), MCP App recovery card + simulator MCP Apps host, shorter
   spoken replies (5h). 86 tests pass. Phone was unplugged at the last restart: re-link with `usb-link`.
4. (done 2026-10-23) Demo video recorded by Claude at the owner's request and published on the owner's
   YouTube channel: https://youtu.be/xQFmAb1c6qg (VALIDATION 5m; the first version https://youtu.be/r5YrfoCfszw is unlisted).
5. (done 2026-10-21) Published at https://github.com/professor-200629/RescueBridge (public, Apache-2.0 detected,
   `main`). The 2026-10-23 audit fixes are pushed too. Push later commits with `git push`. Video URL is in
   `docs/SUBMISSION.md`.
6. Optional, high value for "Impact": 1–2 family members try it for 10 min per `docs/HUMAN_TRIAL_PROTOCOL.md`
   (none has so far; do not describe RescueBridge as user-tested until this happens).
7. Submit on Devpost yourself after re-reading the official rules page (deadline 24 Oct 00:30 IST).

## Where things are

- Code: `src/rescuebridge/` (domain, host, mcp_server, bff, agent, lab, workpad), web: `web/src/`.
- Tests: `tests/` (fixture by default; `windows_readonly` reads real state; helper-process tests use a
  fixture-backed helper over the real pipe).
- Scenarios: `scenarios/` (fixture set, held-out v1/v2 phrasings, held-out scenarios).
- Evidence: `evidence/` (fixture eval, model and interpreter benchmarks, setup timing).
- Smoke data folders `.smoke-data/` and `.smoke-real/` are git-ignored local test state.
