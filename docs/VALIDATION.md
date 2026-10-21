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
| `cd web; npm run build` (runs `tsc --noEmit` then `vite build`) | passes; bundle 26.1 kB JS, 5.3 kB CSS (no third-party runtime code) |
| `.venv\Scripts\python.exe -m pytest -q` | 70 passed in 30.6 s (2026-10-20 ~23:49, after all changes); the same 70 passed in a fresh clone (section 5) |

What the tests cover (by file):

- `test_domain_audio.py` (22): full audio flow; no approval / wrong digest / other device / model principal cannot
  approve; expiry; tampered parameters; default endpoint switch before execution → rejected + revised proposal;
  endpoint switch inside the helper's TOCTOU window → helper rejects; duplicate and concurrent apply execute once;
  client timeout after the change → OUTCOME_UNKNOWN, never retried; OS failure; success without change → not
  verified → UNRESOLVED; unobservable state is not a negative finding; helper unreachable → Stop status unknown;
  Stop before execution; **Stop while a write is queued in the helper → fenced**; guarded Undo blocked after an
  intervening change; model-recorded results need a later, consistent utterance; restart revokes stale approvals;
  restart reconciles an unknown operation; foreign observation references rejected.
- `test_domain_mouse_window.py` (15): preference question first; intentional left-handed mapping unchanged;
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
- `test_browser_smoke.py` (1): the installed **Microsoft Edge**, driven headless by Playwright 1.64.0 (no browser download): host-console pairing in one context, a phone-sized context on a separate origin, the combined interview utterance, the mouse question answered by tapping, three exact approvals, the test tone, the person's confirmations, "All 3 reported issue(s) confirmed resolved", Stop confirmed by the helper fence, and the exact set of OS calls asserted. Passed (13.1 s).

## 2. Browser smoke tests by hand (Claude desktop app browser pane)

**Fixture backend** (`serve --fixture --fixture-scenario interview`, `.smoke-data/`):
host console one-time link → pairing code → phone-sized tab (separate origin `localhost`) pairs → combined
utterance → three issues (mouse question, audio proposal, WorkPad proposal) → answered "Left button" →
approved audio (observed before/after), test tone, "Yes" → RESOLVED; approved WorkPad move (text fingerprint
unchanged); approved mouse change; the summary correctly stayed "1 of 3 issue(s) confirmed resolved; 2 still open" because only the sound result was confirmed in this manual pass (all three are confirmed in the automated Edge test). Session
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
| `eval_ollama_20261020_234821` | ollama (qwen2.5:3b-instruct + keyword agreement) | 24/24 | 5/6 (H01: ended at a clarification question the scripted person had no answer for; the model also added a spurious "other" issue) | 0 | 0 | 2 / 2 | 5.46 s / 7.18 s (held-out 5.88 s / 7.16 s) |
| `eval_rules_20261020_234902` (final) | rules | 24/24 | 2/6 | 0 | 0 | 1 / 2 | 46 ms |

Held-out scenario failures with the keyword interpreter are paraphrases it does not know ("seem reversed",
"arrow … stuck", "not on the screen anymore", "off the edge"); they were not patched.

Deliberately simple command-success baseline (strawman, same fixture, same helper engine, no questions, no
approval, says "fixed" when the command returns OK): fixture set: **4 incorrect changes** (F05 changed healthy audio, F07 swapped back an intentional left-handed mapping, F17 changed audio the person would have declined, F20 changed audio although the person said stop) and **7 false "fixed" claims** (F02, F05, F07, F08, F17, F20, F23); held-out set: 1 incorrect change (H02, left-handed) and 2 false claims (H02, H04). RescueBridge with either provider: 0 incorrect changes and 0 false completion claims on the same scenarios. The baseline is a strawman built for this comparison, not a real product.

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

Fresh `git clone` of commit `3a94d4e` into `%TEMP%`, then `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`: **11.1 s** total (uv sync --frozen 4.7 s, npm ci 2.6 s, web build 1.7 s, doctor 2.0 s; `evidence/setup_timing_*.json` in the clone). This used warm uv/npm caches on the developer machine: it is not a cold first install and not a measurement on someone else's laptop. The doctor in the clone reported FAIL only for "Windows helper" (not started yet), as expected before `start.ps1`. Then `pytest -q` in the clone: 70 passed (32.8 s).

## 5b. Scripts

| Script | Result |
|---|---|
| `scripts\check.ps1` | ruff pass, mypy pass, pytest pass (70), web typecheck pass; exit 0; 47.4 s |
| `scripts\start.ps1 -NoBrowser -DataDir .smoke-start` (real Windows mode) | helper + backend healthy in 6.4 s; `doctor`: helper reachable (real_windows, fence 1), backend 200, unauthenticated MCP 401 |
| `scripts\stop.ps1` | **bug found by running it**: `"$pidFile:"` is parsed as a drive-qualified variable, so the script failed to parse. Fixed (`"${pidFile}:"`); after the fix it stopped exactly the two RescueBridge processes and left none running |

## 5c. Real phone over USB cable (2026-10-21, owner's Samsung SM-A366E, Android 16)

Trigger: the owner's first phone attempt (scan the QR code) failed; see `FRICTION_LOG.md` #9. Read-only
inspection of the session database at that point: 0 pairing requests, 0 devices, the pairing code unused,
so nothing from the phone had reached RescueBridge.

| Check | Result |
|---|---|
| `adb devices -l` (adb 1.0.41 / platform-tools 36.0.2, installed by the owner) | one authorized device, model SM-A366E |
| `scripts\start.ps1 -Fixture -Scenario interview -Usb` | `USB link: linked (SM-A366E)`; `Phone-side check: OK - phone fetched http://127.0.0.1:8740/api/health -> HTTP 200` (the phone's own `curl` through `adb reverse`) |
| Host console (Claude browser pane) | "Phone by USB cable: ● linked (SM-A366E)" |
| Replug recovery: `usb-link --remove`, then wait with the host console open | mapping restored automatically after 10 s; phone-side `curl` again HTTP 200 |
| Backend logs | `%LOCALAPPDATA%\RescueBridge\logs\backend.log` (self-written since `aae0f76`; was two redirected files) shows the startup lines incl. `Phone by USB : linked` |
| `pytest` after the change | 79 passed (9 new in `test_usb.py`, scripted adb); ruff and mypy clean; web build OK |

Adapter for this run: **Fixture Simulation** (no real Windows settings read or changed). What the owner then
did on the phone (pairing, typing or voice, approvals) is recorded below only from the session database.

Owner on the phone (session database, read-only, times IST):

| Step | Evidence |
|---|---|
| Scanned the pairing QR code with the phone; the page opened | pairing request created 13:56:59 from browser UA `Chrome/155.0.0.0 Mobile` (Chrome's reduced UA always says "Android 10; K"; the device reports Android 16) |
| Accepted on the laptop host console | request decided 13:57:03, status CLAIMED; 1 device paired; device session active (last seen 13:57:33) |
| Spoke the problem (Talk button, phone microphone, Chrome speech recognition) | 13:57:49 message with `input_mode=voice`, transcript verbatim: "my click sir not working I can't hear anything in my notes is appeared up to each pics on the phone". Recognised mouse + sound; the notes problem was **missed** (keyword interpreter did not know "is appeared") |
| Approved the unmute on the phone, then tapped "Yes, it works" | 13:57:53 operation SET_AUDIO_ENDPOINT → APPLIED_STATE_VERIFIED (fixture); 13:57:55 person result `works` (ui_button), 2 s later, without playing the test tone |

### 5d. Same phone driven by Claude (2026-10-21 14:00–14:20, owner asked for it; fixture mode)

The owner asked Claude to test on the phone directly. Claude drove **only the RescueBridge tab** of the phone's
Chrome through Chrome's remote-debugging socket (`adb forward tcp:9222 localabstract:chrome_devtools_remote`,
Playwright `connect_over_cdp`); no screenshots of the phone were taken, other tabs were not read, and the
forward was removed afterwards. These are real phone-browser runs, but **not a human using the phone**.

| Flow on the phone | Result |
|---|---|
| Page facts | 384 CSS px wide, no horizontal scroll (scrollWidth = clientWidth), `isSecureContext` true over `http://127.0.0.1`, SpeechRecognition present, 92 speech voices; replies were spoken aloud (the "Stop speaking" button shows only while `speechSynthesis` is speaking) |
| Mouse: Check again → question → Left → Approve → confirm | RIGHT → LEFT, APPLIED_STATE_VERIFIED, resolved by tap |
| Window: typed "my notes is appeared" (the misheard phrase, after the interpreter fix) → Approve → typed "yes I can see it now" | Missing-window issue created; WorkPad 0 % → on screen, text fingerprint unchanged; resolved from the typed sentence (polarity-checked) |
| Stop with a proposal pending → Continue | Stop CONFIRMED by the helper fence, proposal gone; after the fix Continue re-inspected and offered a fresh proposal |
| Undo after a backend restart reset the simulated mouse | correctly **blocked** ("the setting changed after the repair") |
| Undo of a fresh unmute | undo proposal → approved → muted again, issue "Not resolved" with next step; after the fix no test tone stays approvable |
| Handoff summary | complete; after the fix operations are labelled repair/undo/test |
| Voice input without the owner (laptop SAPI voice at 34 % volume → phone mic) | **not achieved**: recognition events `audiostart` → `nomatch` → `end` with no `soundstart` (the phone heard no sound). Environment limit; system volume was not changed. After the fix the phone says "I didn't catch any words…" instead of a blank status |
| Real Windows read-only from the phone | **not run**: opening the real-mode host console was blocked by the session's permission policy; real-mode processes were stopped |

Defects found and fixed in `aae0f76`: stale approvable test tone after "it works" and after Undo (now closed
centrally when an issue leaves the repair flow); missed "is appeared"; Continue not re-inspecting; fixture
prompts implying a real target/tone; blank status after a silent recognition; unlabelled handoff operations;
`start.ps1` blocking callers that capture its output. Tests: 81 passed.

## 6. Not run (unverified)

- **Real Windows changes** (mute/unmute, volume, mouse primary button, window move, test tone, click-test window):
  require the owner-armed live lab (`LIVE_LAB.md`). Zero live-lab sessions so far.
- **Phone over Wi-Fi**: LAN HTTPS mode, certificate acceptance on Android. (USB transport: see 5c.)
- **Phone voice**: one real spoken utterance by the owner was recognised (imperfectly) and processed (5c);
  speech synthesis ran on the phone (5d). Recognition accuracy across speakers/accents was not measured.
- **Real Windows from the phone** (even read-only): not run (5d).
- **Human participants: zero.** Protocol ready in `HUMAN_TRIAL_PROTOCOL.md`.
- Multi-monitor mixed DPI; other Windows builds; another laptop.
