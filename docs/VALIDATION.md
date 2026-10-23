# Validation

Sections 1–5b were run on 2026-10-20 (IST) on the development laptop; later sections carry their own dates.
Results are copied from command output or evidence files; nothing is estimated. **Fixture**, **real Windows**,
and **not run** are kept separate; section 6 is the current summary.

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

### 5e. First real Windows repair from the phone (2026-10-21 18:03–18:07, owner)

`start.ps1 -Usb -DataDir %LOCALAPPDATA%\RescueBridge-real` (**Real Windows**, keyword interpreter; helper log:
`mode=real_windows`). Not the live lab: the owner muted the laptop themself, then used the phone. Evidence
from the session database (read-only) and both logs (no errors):

| Time | Step | Evidence |
|---|---|---|
| 18:04:21–18:04:27 | Scanned the QR code, accepted on the laptop | pairing request CLAIMED |
| 18:05:16 | Spoke "I can't hear anything" (phone mic) | message `input_mode=voice`, transcript exact |
| 18:05:18 | Real inspection | observation `real_windows`: default 'Speaker (Realtek(R) Audio)' **MUTED**, volume 72% → proposal "Unmute … and leave its volume at 72%" |
| 18:05:23–18:05:24 | Approved on the phone | operation SET_AUDIO_ENDPOINT, adapter `real_windows`, **APPLIED_STATE_VERIFIED** (fresh observation: unmuted, 72%) |
| 18:05:47–18:05:50 | Approved the test tone | PLAY_TEST_TONE `real_windows`, APPLIED_STATE_NOT_VERIFIED (the playback call returned; audibility is the person's answer) |
| 18:06:10 | Tapped "Yes, it works" after the tone | person result `works`, `ui_button`, test `tone` → issue RESOLVED |
| 18:06:40–18:06:41 | Spoke "my notes window disappeared" | real window inspection: 1 display, 3 eligible windows, **0 off-screen** → "nothing was moved", manual next steps; no proposal, no operation |

Totals: 2 operations, both owner-approved on the phone; 8 observations, all `real_windows`. This verifies one
real repair (unmute) and the real tone path once, on this laptop. Mouse swap, real window move, and the
click-test window remain unverified on real Windows.

### 5f. First live-lab session: real WorkPad window recovery (2026-10-21 18:12–18:15)

The owner asked Claude to run the rehearsal ("you do all this by yourself, I am giving full access") after
WorkPad crashed on their laptop with "Can't find a usable init.tcl" (venv Tcl lookup; fixed in this commit).
Scope armed: **workpad only, 10 minutes** (`lab arm --session rehearsal-1 --minutes 10 --allow workpad`), data
dir `%LOCALAPPDATA%\RescueBridge-real`. The phone steps were done by Claude on the owner's phone through the
RescueBridge tab (CDP over adb); the owner was not at the phone, so Chrome was brought to the front once.

| Time | Step | Evidence |
|---|---|---|
| 18:12 | Armed; clean state recorded | mouse swapped=False; audio 'Speaker (Realtek(R) Audio)' unmuted 72%; WorkPad running (145 chars, sha256 `ec8605d2…`) |
| 18:12 | `lab inject workpad-offscreen` | WorkPad moved to (2320,188)–(3340,987), right of the 1920-px display |
| 18:14:11 | Phone (typed): "my notes window disappeared" | badge **Controlled Live Lab**; real inspection: 1 display, 4 eligible windows, WorkPad 0 % on screen → proposal "Move … centered, keeping its size (1020x799)" |
| 18:14:22 | Approved on the phone | MOVE_WINDOW, adapter `controlled_live_lab`, **APPLIED_STATE_VERIFIED**: before 1 off-screen, after 0; WorkPad text fingerprint unchanged |
| 18:14 | Independent read-only measurement (GetWindowRect, per-monitor DPI) | WorkPad (450,170)–(1470,969) fully inside work area (0,0)–(1920,1140); visible; not minimized; same 145 chars / `ec8605d2…` |
| 18:14:52 | `lab disarm` | restore actions: none needed (already back); watchdog exited 0; lab inactive |

The phone's question "Can you see and use the window?" was **left for the owner**: no person result was entered
by Claude. This verifies one real window move (`SetWindowPos`) on real Windows under the live lab.

### 5g. Visual redesign (2026-10-21 evening)

Dark "mission control" theme: voice orb with listening / thinking / speaking states, large reply caption,
tappable example phrases, chat-bubble captions, a per-issue progress rail (Heard → Checked → Approval →
Verified → Your check), before/after evidence tags, gradient-bordered proposals, a session progress meter,
sticky Stop. Behaviour, ids and texts are unchanged. Checked: `pytest` 82 passed including the Edge
end-to-end browser test on the new markup; Claude browser pane at 375×812 and 1280×860 (pairing, three-issue
report, approve, before/after evidence, person confirmation, meter 1/3); `prefers-reduced-motion` turns off all
animation; `prefers-contrast: more` switches to solid surfaces. On the owner's phone (USB, real-mode backend)
the owner reported the new design showing at ~18:56; the session database shows the phone's session active at
18:56:03. No screen-reader pass was done after the redesign.

### 5h. MCP App card and shorter spoken replies (2026-10-21 evening)

- `tests/test_mcp_app.py` (3): `get_recovery_status` declares `_meta.ui.resourceUri`; `resources/list` and
  `resources/read` over real Streamable HTTP return the card with `text/html;profile=mcp-app`; unknown `ui://`
  rejected; the card loads nothing external, never uses innerHTML/eval/fetch, and can only ask for
  `get_recovery_status`; the simulator serves it with one sandboxing CSP (`sandbox allow-scripts`,
  `frame-ancestors 'self'`, `connect-src 'none'`), requires a paired session, refuses `apply_recovery` and a
  wrong CSRF token.
- Edge end-to-end test: after the three repairs, the card renders inside its sandboxed iframe after the
  `ui/initialize` handshake ("3/3 confirmed", "Fixture Simulation"), and its Refresh button round-trips
  view → host → MCP `tools/call` → view. Passed.
- Replies: one short headline per issue plus the first sentence of the exact proposal; the cards keep the full
  text. Fixture evaluation unchanged (24/24, held-out 2/6, 0 incorrect changes, 0 false claims). 86 tests pass.
- Not done: no third-party MCP Apps host (e.g. a desktop AI client) was used to render the card.

### 5i. Review repairs (2026-10-21 night): reproduced first, then fixed

Each defect was reproduced in real Edge (Playwright, fixture backend) **before** the fix; the same tests pass
after it (`tests/test_browser_repairs.py`, 9 tests; `tests/test_repairs_backend.py`, 8 tests).

| Finding | Reproduction (before) | Fix and check (after) |
|---|---|---|
| Send error overwritten | a failed Send left the status line at `''` (the message was set, then cleared in the same `render()`) | dedicated `role="alert"` box with Retry/Dismiss, separate from progress; survives 2 polling cycles; transcript kept; Retry succeeds. Lost connection after delivery: state checked, message **not** resent, no Retry offered |
| First reply not spoken | speech substitute recorded nothing for the first reply | history (first snapshot) captioned, never spoken; each reply id spoken once across Send + polling; nothing replayed after reload; toggle off respected |
| Stale snapshot after Stop | an ACTIVE snapshot fetched before Stop and delivered after it brought back an **Approve** button and removed Continue | `state_seq` (SQLite triggers on 8 tables) in every payload with device + mission; client keeps only seq ≥ last shown; polls never overlap; Stop CONFIRMED only on the helper fence ack, HELPER_UNREACHABLE (unknown) without it |
| Duplicate approval / lost answer | (new test) | approval control disabled on tap; double tap → 1 request; an approval whose answer was lost shows "may or may not have happened", reconciles from the server ("Change made and the new state was observed"), sends nothing again; 1 OS call |
| Empty pairing code reached the server | an empty code produced a `/api/pair/request` call | client: exactly 8 digits after removing spaces/dashes, inline `aria-invalid` error, no request; server: `MALFORMED_CODE` (not counted as a guess; 9 digits no longer truncated to 8), `CODE_EXPIRED`, `NO_ACTIVE_CODE`, `WRONG_CODE`, `RATE_LIMITED` |
| First-run dead end | `/host` without a link only said "use the one-time link" | start page: Connect this phone / Set up this laptop / How this phone reaches the laptop (127.0.0.1 explained); `scripts\host-console.ps1` launcher; host page explains the launcher; link errors say expired / used / invalid / laptop-only; an already-open guide tab picks up a new link |
| Launcher wrote a link into the wrong database | (found while testing the live instance: a wrong `-DataDir` still passed the port health check and created a new DB) | the folder's own `backend.pid` must be a live process (checked with `OpenProcess`, not `os.kill`); no DB is created |
| Judge preview | — | "Try a simulated recovery": recorded from the fixture engine, replayed in the browser; the test walks the whole flow and asserts **zero** `/api` and `/mcp` requests |

Also checked: 20 protected endpoints return 401/403 without a session; Tab reaches every control on the pairing,
recovery and preview screens, no positive `tabindex`, visible focus, no horizontal overflow at 390 px. Full suite:
103 passed; ruff, mypy, tsc clean; evaluation unchanged (fixture 24/24, held-out 2/6, 0 incorrect, 0 false
claims; trigger overhead measured at ≤ 0.1 ms per write). The running instance at `http://127.0.0.1:8740/`
(real mode, restarted) serves `assets/index-91_L_oPt.js`, byte-identical to `web/dist`, and answers an empty code
with `MALFORMED_CODE`.

Not covered: real microphone or audio output for the new speech logic (substitute only); the redesigned flows on
the owner's phone after these fixes; a screen reader; real Windows changes (none were made).

### 5j. Everything re-tested on the owner's real phone and laptop (2026-10-21 22:19–22:27, owner: "test everything … full access")

Claude drove only the RescueBridge tab of the phone's Chrome through its own DevTools socket (Playwright could no
longer attach because another tab did not answer; no other tab was read), with request interception for the
fault cases and a wrapper that records *and still speaks* every reply. Real-mode backend (`RescueBridge-real`).
Real Windows changes ran only under the live lab, scope **audio + workpad**, then disarmed; the mouse swap was
not run (its click test needs a person at the laptop).

| Part | Result |
|---|---|
| A — repairs on the phone, read-only (16 checks) | **16/16**: rebuilt bundle `index-91_L_oPt.js`; no overflow at 384 px; history not spoken after reload; first reply spoken exactly once with real phone speech (`speaking=true`); injected 500 error stays through polling, words kept, Retry clears it; no overlapping polls; Stop confirmed by the real helper fence and kept when an older ACTIVE snapshot arrives afterwards; Continue resumes; unpaired view (`localhost`) explains 127.0.0.1 and setup; empty/malformed codes never sent; `NO_ACTIVE_CODE` answer; simulated preview completed with 0 laptop requests and spoken replies |
| B — live lab audio (9 checks) | lab muted the Realtek speaker → phone report → **double tap = 1 approval request**, button disabled at once → independent read: unmuted, 64% → real test tone played → **real guarded Undo** approved on the phone → independent read: muted again → disarm restored unmuted 64%. WorkPad part of B did not run as intended: WorkPad had started **minimized** (launched from a hidden process), the lab "moved" the minimized window, and RescueBridge correctly answered "No supported off-screen window was found, so nothing was moved" |
| Fix | `lab inject workpad-offscreen` now refuses a minimized or hidden WorkPad (`tests/test_lab.py::test_workpad_fault_is_refused_while_workpad_is_minimized`) |
| C — live lab WorkPad (7 checks) | **7/7** after restoring WorkPad: off-screen at (2320,188) → phone report → approve → independent read: (450,170)–(1470,969) fully on screen, text fingerprint `ec8605d2…` unchanged → Stop confirmed → disarm; sound, mouse, WorkPad all as before |
| Launcher | `scripts\host-console.ps1 -DataDir …RescueBridge-real` opened the host console in the laptop's browser; the new one-time link was consumed 1.1 s later |

Session database for the window 22:22–22:25: REPAIR SET_AUDIO_ENDPOINT, TEST PLAY_TEST_TONE, **UNDO
SET_AUDIO_ENDPOINT**, REPAIR MOVE_WINDOW — all `controlled_live_lab`, verified (the tone "not verified" by design);
4 approvals; mission stop detail "helper fence 4 acknowledged". No person answered the tone question (Claude
cannot hear the laptop). 104 tests pass after the lab fix.

### 5k. Audit fixes (2026-10-23): four independently reproduced defects

An independent audit of commit `424acea` reproduced four defects. Each fix has deterministic regression tests:
threading events and one-shot pause points in the fixture OS adapter (`FixtureOps.pause_points`), not timing
sleeps. **No real Windows setting was changed, no tone was played and no window was moved for this work.**

| Defect | Root cause | Fix | Tests |
|---|---|---|---|
| A write whose authority Stop had revoked could still reach the OS | The helper compared the revision with the fence once, before its own precondition observation. The real adapter then waited in its single COM worker queue before the OS call, so Stop could land in between and the write still ran. The fence ack also reported any started operation as "in flight", even one that was only queued or observing. | **Admission gate.** Every mutation (mouse, audio including Undo, window move, tone, click test) calls `admit()` in the context that performs the OS call — on the COM worker thread for real Windows, after any queue wait — immediately before the call. `admit()` and fence advancement take the same lock: an operation is either admitted before the fence moved (ack: `in_flight_operation_id`, phase `ADMITTED`; it may finish) or refused (`FENCED`, phase `REJECTED_BY_FENCE`). Phases `QUEUED`/`OBSERVING`/`ADMITTED`/`COMPLETED`/`NOT_ADMITTED`; queued and observing operations are listed separately as `pending_operation_ids`. | `tests/test_stop_fence.py` (9): Stop during a paused precondition observation → no mutation; Stop while each mutation kind is queued → none; Stop during an admitted call → reported in flight, completes, a stale retry is fenced; repeated and lower fences are idempotent; service level: Stop during the helper's precondition check, and Stop while an Undo is queued. With the gate's fence check disabled, 7 of the 9 fail. |
| Hedged answers resolved issues | The `AFFIRM` regex found "works" inside "I think it works, maybe", "It works?", "It works sometimes"; the LLM path accepted a model "yes" when the keyword side had no answer; the service accepted a model-interpreted `works` whenever that regex matched. | One rule, `domain/confirm.py::confirmation_polarity` → yes / no / unclear (a question, tentative, conditional or intermittent wording, or positive and negative together → unclear). The **service** enforces it before a model-interpreted answer can resolve or fail an issue (`AMBIGUOUS`); both interpreters use it, and an LLM label cannot override an unclear reading. An unclear answer is recorded as `unsure` citing the utterance id; the issue stays `AWAITING_USER_CONFIRMATION`; the reply asks for yes/no or the buttons. | `tests/test_confirmation.py` (20): the seven audit phrases through the service and through the phone API; buttons still confirm directly; a fake LLM that labels everything "yes" cannot override; a clear "no" that names the symptom is one answer, not a new report. |
| A tone approved at one volume could play at another | `tone_plan` bound only the endpoint and "unmuted"; the helper checked only the endpoint. | The volume is in the tone's parameters (`expect_volume_scalar`, `expect_muted: false`) and preconditions, both under the approval digest; backend tolerance for the tone 0.005 (half the smallest user-visible 1 % step; Windows reads back the scalar it set); the helper protocol requires the fields; the helper checks before queueing and the OS adapter re-checks inside the worker immediately before `PlaySound`. On a mismatch nothing plays and nothing is adjusted: a fresh test proposal for the current settings is offered (new approval), none if muted. | `tests/test_tone_binding.py` (8): unchanged → plays once; volume up, volume down, other endpoint, muted → not played, no playback call, volume untouched, new proposal (none when muted); a change while the tone waits in the helper queue → refused + new proposal; tampered expected volume → digest rejected; protocol requires the fields. Fixture OS: nothing audible. |
| `.python-version` ignored by uv | The file was UTF-8 **with BOM** (`EF BB BF 33 2E 31 33`); uv read `﻿3.13` as an unsupported request and ignored the pin. | The file is exactly `3.13\n` (5 bytes). `requires-python` and `uv.lock` unchanged. | Clean clone, below. |

**Clean clone** (`git clone` into `%TEMP%`, no `.venv`, `VIRTUAL_ENV`/`UV_PYTHON` unset, no `--python`):

| Checkout | `uv sync --frozen` |
|---|---|
| `424acea` (before) | `warning: Ignoring unsupported Python request '﻿3.13' in version file`, `Using CPython 3.12.13`, `error: The Python request from .python-version resolved to Python 3.12.13, which is incompatible with the project's Python requirement: ==3.13.*` — **exit 2** |
| fixed file | `Using CPython 3.13.0 interpreter at: …\Python313\python.exe`, 49 packages installed, **exit 0, no warning**; `uv python find` → the clone's `.venv`, no warning |
| the whole final tree (staged as a commit in a throwaway clone, then cloned again) | same: CPython 3.13.0, exit 0, 0 warnings; then `pytest -m "not browser"` in that checkout: **131 passed**, 10 deselected (the browser tests need `npm ci` + build, not run there) |

The packages came from the warm local uv cache; an install with an empty cache (network to PyPI) was not run.

**Real adapter, nothing written:** a probe called the real `WindowsOps.set_audio` with `mute=None, volume=None`
(writes nothing even without a gate) while the single COM worker was held busy: the call was observed queued, a
fence advanced, the worker was released, and the gate ran **on the worker thread after the queue wait** and refused
it (`FENCED`, not `OS_ERROR`); the default endpoint's mute and volume were identical before and after. The real
mouse, window, tone and click-test gates follow the same code pattern but were not exercised on real Windows.

Note on section 1: the earlier test "Stop while a write is queued in the helper → fenced" covered a write waiting
for the helper's lock only, not the worker queue or the precondition observation; 5k supersedes it.

Checks for this change (2026-10-23, this laptop):

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` (all tests, incl. Edge browser, helper process over the real named pipe, real Windows read-only) | **141 passed**, 0 failed, 0 skipped, 157 s |
| `.venv\Scripts\python.exe -m ruff check src tests scripts` | All checks passed |
| `.venv\Scripts\python.exe -m mypy` | Success: no issues found in 47 source files |
| `cd web; npx tsc --noEmit -p .; npm run build` | pass; bundle unchanged (`index-91_L_oPt.js`; no web source changed) |
| `rescuebridge.cli eval --sets fixture,heldout --provider rules` | fixture 24/24, held-out 2/6, 0 incorrect changes, 0 false claims (unchanged) |

Before/after through the phone API (clean clone of `424acea`, same fixture flow): "I think it works, maybe",
"It works?", "It works sometimes" and "If it works, I'll tell you" each **resolved** the issue (`works` recorded);
now each stays waiting, is recorded as `unsure`, and gets a follow-up question. "It works, but I still can't hear
anything" and "No, I still can't hear anything" were silently ignored (no answer recorded, no question), because a
sentence that also names a symptom skipped the answer routing; now the first is asked again and the second is
recorded as `still_broken` → `UNRESOLVED` with next steps.

### 5l. Second review (2026-10-23): timeouts and present-tense confirmations

A second review of `68f98b9` reproduced two remaining defects. Both were reproduced here before the fix, with the
same fixture-only / fake-COM rules as 5k (no real setting changed, nothing audible).

| Defect | Reproduction before the fix | Root cause | Fix | Tests |
|---|---|---|---|---|
| Stop lost track of an audio change after a timeout | Real `WindowsOps` worker, fake Core Audio objects, 0.3 s timeout, worker stalled in `GetDevice`: the request returned `OS_ERROR` ("Core Audio write failed: TimeoutError"); Stop then acknowledged **nothing in flight, nothing pending**; releasing the worker still called `SetMute(0)` (unmuted after a confirmed Stop) | The worker timeout ended only the *wait*; the engine's cleanup then cleared "in flight" although the worker could still run the call. Admission happened before the preparatory COM calls, so a stall there was already "admitted". A timeout was reported as a definite failure. | Admission is a context **entered and left in the execution context of the OS call**: an operation stays in flight until the call returns, even after its request gave up. Admission moved after the preparatory COM calls (`GetDevice`/`Activate`/`QueryInterface`), right around `SetMasterVolumeLevelScalar`/`SetMute` (same pattern for mouse, window, tone, click test). A timeout returns `OUTCOME_UNKNOWN` with `admitted`/`still_running`; an operation not yet admitted is cancelled atomically and can never start later. The backend treats `admitted` as unknown outcome, otherwise "not attempted"; it does not conclude while the helper still lists the operation (in flight or pending), and **Check again** settles it later from a fresh observation, without re-executing. | `tests/test_helper_timeouts.py` (8): stalled before the change → cancelled, never runs (with and without Stop); stalled inside `SetMute` → stays in flight across the timeout, Stop names it, it finishes, then nothing is in flight; Stop during a stalled preparatory call → refused; backend waits while the change still runs and settles it on Check again (one OS call); Stop after a backend timeout names the running change; timeout before / after the change started → not attempted / unknown outcome. Same sequence after the fix: `OUTCOME_UNKNOWN` "cancelled and will not run", no write after release, still muted. |
| Historical and wishful statements resolved issues | Phone API on `68f98b9`: "It was working yesterday" and "I wish it worked" each → **RESOLVED** (`works` recorded) | A yes was any positive word ("working", "it worked") not cancelled by a known qualifier. | A yes must be a **recognised present-tense confirmation**: the whole utterance consists of confirmations ("yes", "it works now", "I heard the tone", "it's back on my screen") and filler ("thanks"). Time-shifted, wishful, second-hand, deferred, contrasting and idiomatic wording ("no problem", "never mind") is unclear, and unknown wording is unclear by default; a no needs negative evidence and no positive evidence. Same service-side enforcement as 5k. | `tests/test_confirmation.py`: the two reported phrases plus "It should work now", "My son says it works", "It worked on my other laptop", "It works for now" through the service and the phone; 43 single-phrase cases (every confirmation phrase of the evaluation harness and the held-out sets, common negatives, and unclear idioms). After the fix both reported phrases stay `AWAITING_USER_CONFIRMATION`, recorded as `unsure`. |

Note: the held-out answer phrases (section 4, "v1 answers", "v2 answers") were used as required examples while
writing the new grammar, so they no longer measure how the keyword interpreter generalises to unseen answers; the
interpreter benchmark was not re-run.

Checks for this change (2026-10-23, this laptop):

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` (all tests, incl. Edge browser, helper over the real pipe, real Windows read-only, `WindowsOps` worker with fake Core Audio) | **210 passed**, 0 failed, 0 skipped, 154 s |
| `ruff check src tests scripts` / `mypy` | All checks passed / no issues in 47 source files |
| `rescuebridge.cli eval --sets fixture,heldout --provider rules` | fixture 24/24, held-out 2/6, 0 incorrect changes, 0 false claims (unchanged) |
| Read-only probe of the real `WindowsOps.set_audio` (no value to write; 5k) re-run on the new code | gate on the worker thread, refused after a queue wait, endpoint unchanged |

No web source changed (the bundle is unchanged). Not run: a real stall of a real Windows call, and any real
change with this code (no live-lab session).

## 6. Current status by kind of evidence (2026-10-23)

**Automated tests on the fixture OS adapter** (simulated Windows, simulated person in the evaluation): every
workflow, races, failures, Stop/fence, Undo, confirmation rule, tone binding, pairing and web security, browser
flows in headless Edge. These say nothing about real hardware.

**Real devices of the owner (this laptop + Samsung SM-A366E over USB)** — done by the owner, or by Claude at the
owner's request on the owner's devices; not by anyone else:

| Verified on real Windows / the real phone | Where |
|---|---|
| Read-only observation of mouse, audio, windows, monitors; Stop confirmed by the real helper fence | 2, 5j |
| Unmute (Core Audio `SetMute`) approved on the phone; the test tone (`PlaySound`) played once | 5e, 5j |
| Guarded Undo of the unmute | 5j |
| WorkPad off-screen window moved back (`SetWindowPos`), text fingerprint unchanged | 5f, 5j |
| QR pairing, phone microphone input (the owner's own spoken requests), phone speech output | 5c, 5e, 5j |
| Phone flows in the phone's real Chrome, driven by Claude over DevTools (not a person using the phone) | 5d, 5j |

**Independent participant testing: none.** No one other than the owner has used RescueBridge; no user study was
run. Protocol ready in `HUMAN_TRIAL_PROTOCOL.md`.

**Unverified (code exists, not run for real):**

- Mouse primary-button swap and the click-test window on real Windows.
- Volume change on real Windows (only unmute was ever needed); the new tone volume binding and the admission gate
  with a real change (5k exercised the gate on the real worker with a no-op call only).
- Phone over Wi-Fi/LAN (HTTPS, certificate acceptance on Android).
- Screen reader or other assistive technology; recognition accuracy across speakers and accents.
- A third-party MCP Apps host rendering the recovery card (only RescueBridge's own simulator host).
- Multi-monitor mixed DPI; other Windows builds; another laptop; a cold-cache fresh install.

**Demo:** planned in `DEMO_SCRIPT.md`; **not recorded, no video URL.**
