# Validation

Everything below was run on 2026-10-20 (IST) on the development laptop unless marked otherwise. Results are
copied from command output or evidence files; nothing is estimated. **Fixture**, **real Windows read-only**,
and **not run** are kept separate.

## Environment

| Item | Value |
|---|---|
| OS | Windows 11 Home Single Language 10.0.26300, user account at Medium integrity (not elevated) |
| Hardware | HP Pavilion 16, Intel Core Ultra 5 125U, 16 GB RAM (1.3–2.5 GB free during model runs), Intel graphics |
| Display | 1 monitor, 1920×1200 at 120 DPI (work area 1920×1140) |
| Audio | default render endpoint "Speaker (Realtek(R) Audio)" |
| Python / uv / Node | 3.13.0 / 0.12.9 / 24.14.0 |
| Key packages | mcp 2.3.0, starlette 1.9.0, uvicorn 0.54.0, pydantic 2.14.1, pycaw 20260927, pywin32 312; vite 8.3.4, typescript 6.0.3 |
| Local LLM | Ollama 0.32.3; qwen2.5:3b-instruct, llama3.2:3b (already installed; nothing downloaded) |
| Browser for smoke tests | Claude desktop app built-in browser pane (Chromium-based); Microsoft Edge via Playwright (see below) |

## 1. Static checks and unit/integration tests (fixture adapters; no Windows changes)

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m ruff check src tests` | All checks passed |
| `.venv\Scripts\python.exe -m mypy` | Success: no issues found in 45 source files |
| `cd web; npm run build` (runs `tsc --noEmit` then `vite build`) | passes; bundle 25.6 kB JS, 5.3 kB CSS |
| `.venv\Scripts\python.exe -m pytest -q` | FINAL_PYTEST |

What the tests cover (by file):

- `test_domain_audio.py` (22): full audio flow; no approval / wrong digest / other device / model principal cannot
  approve; expiry; tampered parameters; default endpoint switch before execution → rejected + revised proposal;
  endpoint switch inside the helper's TOCTOU window → helper rejects; duplicate and concurrent apply execute once;
  client timeout after the change → OUTCOME_UNKNOWN, never retried; OS failure; success without change → not
  verified → UNRESOLVED; unobservable state is not a negative finding; helper unreachable → Stop status unknown;
  Stop before execution; **Stop while a write is queued in the helper → fenced**; guarded Undo blocked after an
  intervening change; model-recorded results need a later, consistent utterance; restart revokes stale approvals;
  restart reconciles an unknown operation; foreign observation references rejected.
- `test_domain_mouse_window.py` (16): preference question first; intentional left-handed mapping unchanged;
  mouse repair + click test + Undo; changed-by-someone-else → NO_CHANGE_NEEDED; unsupported symptoms change
  nothing; WorkPad text fingerprint preserved; ambiguous windows → clarification; raw HWND / unknown target refs
  rejected; **HWND reused by another process** rejected (backend and helper independently); monitor unplugged →
  rejected + revised; elevated window unsupported; combined symptoms → partial result reported as partial.
- `test_e2e_backend.py` (7): real sockets: browser HTTP → BFF → real MCP client → Streamable HTTP MCP server →
  service → helper engine; protocol version 2025-11-25 recorded; initialize / tools/list / tools/call; unknown tool,
  unknown properties, non-integer and NaN numbers, path-like ids rejected; injected "user approved" text cannot
  authorize; no token / bad token → 401; browser Origin → 403; transport-session replacement keeps state and does
  not cross devices; Origin/CSRF/Host checks; pairing code reuse and brute force; bootstrap one-use; device
  revocation bumps the permission revision; security headers; HttpOnly SameSite cookies; Check again.
- `test_helper_process.py` (5): the helper as a **separate process over the real named pipe** (fixture-backed):
  round trip, fence rejection, fixed schema refuses arbitrary ops, wrong key rejected, second helper cannot take the
  pipe, **pipe and key-file DACLs contain only the current user's SID**, killed helper reported unavailable.
- `test_windows_readonly.py` (2): **real Windows adapter, read-only**: mouse/audio/window observations have the
  expected shape and two reads agree (nothing changed); unknown window target refused.
- `test_lab.py` (6): live-lab rules on the fixture: nothing injectable unless armed and in scope; arming bounds;
  restore returns to snapshot; restore leaves the person's own changes alone; watchdog restores at expiry; arming
  file is current-user-only.
- `test_agent.py` (8), `test_baseline.py` (3), `test_certs.py` (1): claim guard, answer-agreement policy, visible
  model failure with no fallback, tool-call budget, misread negative answer cannot resolve an issue, baseline
  behaviour, LAN certificate.
- `test_browser_smoke.py` (1): BROWSER_TEST_RESULT

## 2. Browser smoke tests by hand (Claude desktop app browser pane)

**Fixture backend** (`serve --fixture --fixture-scenario interview`, `.smoke-data/`):
host console one-time link → pairing code → phone-sized tab (separate origin `localhost`) pairs → combined
utterance → three issues (mouse question, audio proposal, WorkPad proposal) → answered "Left button" →
approved audio (observed before/after), test tone, "Yes" → RESOLVED; approved WorkPad move (text fingerprint
unchanged); approved mouse change; summary "1 of 3 confirmed resolved" until the others were confirmed. Session
survived a backend restart. Defects found and fixed during this pass: focus lost on every 3 s re-render
(now re-render only on change + focus restore), QR code rendered as a thin bar (now a data-URI image), used pairing
code still displayed, stale "Next step" after re-inspection, awkward tone wording, overly long multi-issue replies.

**Real Windows, read-only** (real helper + backend, `.smoke-real/`): paired, then "My clicks are wrong, I can't hear
anything, and my notes disappeared" → observed the real state: primary button LEFT (default); "Speaker (Realtek(R)
Audio)" not muted, 24%; 1 display, 3 eligible windows, 0 off-screen → no supported causes, **no change made**;
answered "Left button" → "already matches, no setting changed"; **Stop → "Stopped — the laptop helper confirmed"**
(real helper fence). Labels showed **Real Windows** and "Laptop helper: reachable".

Accessibility spot-checks on that page (DOM script, not a certified audit): 0 buttons without accessible names,
0 unlabelled form controls, 0 images without alt, no button under 40 px, `lang="en"`, live regions present,
`prefers-reduced-motion` and `:focus-visible` rules loaded; keyboard Tab order intro → Talk → transcript → Send with
a visible focus ring. No screen reader or assistive-technology user testing.

## 3. Fixture scenario evaluation (simulated OS + simulated person, full stack)

`.venv\Scripts\python.exe -m rescuebridge.cli eval --sets fixture,heldout --provider <rules|ollama>`

| Run | Provider | Fixture set (24) | Held-out set (6) | Incorrect changes | False completion claims | Fallback taps | Utterance latency median / max |
|---|---|---|---|---|---|---|---|
| `eval_rules_20261020_232254` | rules | 23/24 (F15 failed: unrecognised "wifi" problem ignored) | 2/6 | 0 | 0 | 1 / 2 | 155 ms / — |
| `eval_rules_20261020_232358` (after the F15 fix) | rules | 24/24 | not re-run | 0 | 0 | 1 | 142 ms |
| EVAL_LLM_ROW |
| EVAL_RULES_FINAL_ROW |

Held-out scenario failures with the keyword interpreter are paraphrases it does not know ("seem reversed",
"arrow … stuck", "not on the screen anymore", "off the edge"); they were not patched.

Deliberately simple command-success baseline (strawman, same fixture, same helper engine, no questions, no
approval, says "fixed" when the command returns OK): BASELINE_ROW

## 4. Local model measurements (this laptop only)

**Free tool calling** (`bench-model`, evidence `model_bench_20261020_231602.json`): the model gets the real
system prompt and nine MCP tool schemas and must call `start_recovery` with the right categories.

| Model | Correct first calls | Cold first call | Warm median / max |
|---|---|---|---|
| qwen2.5:3b-instruct | 0/8 | 62.7 s | 4.3 s / 12.2 s |
| llama3.2:3b | 0/8 | 66.8 s | 4.5 s / 6.9 s |

Both models called `inspect_recovery` / `record_user_result` with invented ids instead. Consequence: the shipped
`ollama` provider uses the model only for schema-constrained interpretation.

**Interpretation accuracy** (`bench-interpret`, evidence `interpreter_bench_20261020_232719.json` and
`interpreter_bench_20261020_234134.json`; exact-match scoring):

| Interpreter | dev symptoms (8) | held-out v1 symptoms (20) | held-out v2 symptoms (10) | v1 answers (10) | v2 answers (10) | warm median |
|---|---|---|---|---|---|---|
| keyword (no LLM) | 7/8 | 11/20 | 8/10 | 8/10 | 7/10 | ~0 ms |
| qwen2.5:3b JSON schema | 8/8 | 20/20 | 9/10 | 6/10 | 7/10 | 5.3 s |
| qwen2.5:3b + keyword agreement (shipped `ollama`) | 8/8 | 20/20 | 9/10 | 9/10 ¹ | 8/10 ² | 5.4 s |
| llama3.2:3b JSON schema (first run only) | 6/8 | 9/20 | — | 4/10 | — | 6.6 s |

¹ post-hoc: the agreement policy was designed after inspecting v1 answer failures. ² v2 was written and
committed (`bccab05`) before the policy was implemented and evaluated once. Of the two v2 misses, one ("still
nothing") was a safe *ask again* after a conflict; the other ("not at all") was misread as **yes** — the
server's polarity check rejects recording that as a success (`test_misread_negative_answer_cannot_resolve_an_issue`).

## 5. Setup

SETUP_ROW

## 6. Not run (unverified)

- **Real Windows changes** (mute/unmute, volume, mouse primary button, window move, test tone, click-test window):
  require the owner-armed live lab (`LIVE_LAB.md`). Zero live-lab sessions so far.
- **Phone**: LAN HTTPS mode, certificate acceptance on Android, microphone, speech recognition, speech synthesis.
- **Voice in any browser**: no microphone was used in testing; typed input only.
- **Human participants: zero.** Protocol ready in `HUMAN_TRIAL_PROTOCOL.md`.
- Multi-monitor mixed DPI; other Windows builds; another laptop.
