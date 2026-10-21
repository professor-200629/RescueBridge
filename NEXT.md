# RescueBridge — durable checkpoint

Read this first after any context reset, then `spec/RescueBridge-Claude-Code-Build-Prompt.md` (original
spec, SHA-256 3C4EC4EF…9A8E), `docs/VALIDATION.md`, `docs/KNOWN_LIMITATIONS.md`.

## Environment (observed 2026-10-20)

Windows 11 Home 10.0.26300, HP Pavilion 16, Core Ultra 5 125U, 16 GB RAM (often only 1–3 GB free), Intel iGPU.
User `professor04\balu`, Medium integrity. Python 3.13.0 via uv 0.12.9; Node 24.14.0; Ollama 0.32.3 with
qwen2.5:3b-instruct and llama3.2:3b (no downloads by this project). MCP SDK 2.3.0 (handshake max 2025-11-25).

## Gate status

| Gate | Status |
|---|---|
| 0 Inspect + plan | done |
| 1 Vertical slice | done in browser for fixture (all 3 workflows, approve → apply → verify → person result) and real Windows **read-only** (observe, question, no-cause, Stop fence). Real Windows **changes**: unmute + tone verified 2026-10-21 from the owner's phone (VALIDATION 5e); mouse swap / window move / click test not yet on real Windows. Phone: USB verified (QR pairing, voice, approvals; VALIDATION 5c–5e). Wi-Fi/LAN phone: not tested. |
| 2 Domain engine + adapters | done: SQLite state, proposals/digests/approvals, fence, idempotent apply, reconciliation, guarded Undo, 3 recipes, real + fixture adapters, named-pipe helper |
| 3 UX + model/voice | browser app done; voice code written but not exercised with a microphone; local LLM measured (tool-calling 0/8; schema interpretation 20/20 held-out v1 symptoms) |
| 4 Validation + submission | tests/eval/bench/docs done; pending: live lab, phone, fresh-clone setup timing, video, publishing |

## Last verified checks (2026-10-20, ~23:55 IST)

See `docs/VALIDATION.md` for exact commands and numbers. Summary: `pytest` 70 passed (also in a fresh clone);
ruff and mypy clean; Edge browser smoke test passes; fixture evaluation 24/24 (keyword and LLM providers),
held-out 2/6 (keyword) and 5/6 (LLM); 0 incorrect changes and 0 false completion claims in every evaluation run;
start/stop/check scripts exercised (stop.ps1 parse bug found and fixed).

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
not reach the phone mic), any real Windows change (live lab never armed).

## Next actions (in order)

1. (done 2026-10-21, VALIDATION 5f) live-lab WorkPad rehearsal: real window move verified. WorkPad's Tk
   start-up in the venv was broken and is fixed. Owner still has to answer the phone's "can you see it?".
2. (done 2026-10-21) phone over USB: QR pairing, voice, real unmute + tone (VALIDATION 5c–5e).
3. Decide provider for the demo (`ollama` + qwen2.5:3b-instruct recommended for understanding; ~5–6 s/request).
4. Publish the repo (license visible), record the < 3 min video per `docs/DEMO_SCRIPT.md`, fill URLs in
   `docs/SUBMISSION.md`. Do not submit without re-reading the official rules page.

## Where things are

- Code: `src/rescuebridge/` (domain, host, mcp_server, bff, agent, lab, workpad), web: `web/src/`.
- Tests: `tests/` (fixture by default; `windows_readonly` reads real state; helper-process tests use a
  fixture-backed helper over the real pipe).
- Scenarios: `scenarios/` (fixture set, held-out v1/v2 phrasings, held-out scenarios).
- Evidence: `evidence/` (fixture eval, model and interpreter benchmarks, setup timing).
- Smoke data folders `.smoke-data/` and `.smoke-real/` are git-ignored local test state.
