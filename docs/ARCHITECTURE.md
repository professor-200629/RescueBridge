# Architecture

## Processes and boundaries

```
 Phone / desktop browser                Laptop (one Windows user, not elevated)
 ┌────────────────────────┐   HTTPS (LAN) or      ┌─────────────────────────────────────────────┐
 │ Web app (TypeScript)   │── http://127.0.0.1 ──▶│ Backend process  (python -m rescuebridge serve)│
 │ talk / transcript /    │  HttpOnly cookie +     │  ├─ BFF (Starlette): pairing, sessions, CSRF,  │
 │ proposal card / Stop   │  CSRF header           │  │   approve/decline/Stop/answers/results      │
 └────────────────────────┘                        │  │   agent orchestration ──┐                   │
                                                   │  │                         │ real MCP client   │
                                                   │  ├─ MCP server ◀──────────┘ Streamable HTTP   │
                                                   │  │   127.0.0.1:8765/mcp, bearer per device     │
                                                   │  ├─ RecoveryService (authority + state engine) │
                                                   │  └─ SQLite (WAL): sessions, missions, issues,  │
                                                   │      observations, proposals, approvals, ops   │
                                                   └───────────────┬─────────────────────────────────┘
                                                                   │ named pipe \\.\pipe\RescueBridgeHelper
                                                                   │ (current-user DACL, mutual HMAC)
                                                   ┌───────────────▼─────────────────────────────────┐
                                                   │ Helper process (python -m rescuebridge helper)   │
                                                   │  HelperEngine: fixed schema, fence, write lock,  │
                                                   │  target refs ──▶ WindowsOps (Win32/Core Audio)   │
                                                   └──────────────────────────────────────────────────┘
 Optional: Ollama (local LLM) at 127.0.0.1:11434 — called only by the BFF's interpreter, never by tools.
```

| Component | Code | Responsibility |
|---|---|---|
| Web app | `web/src/` | Pairing, talk/transcript, captions, issue cards, proposal card with exact text + Approve, confirmation buttons, evidence, persistent Stop, diagnostics. No credentials in JS (cookies are HttpOnly; CSRF token in memory). |
| BFF | `src/rescuebridge/bff/app.py` | Authenticates browser sessions; host console; acts as a **real MCP client** (`agent/mcp_client.py`, SDK `Client`, `mode="legacy"` → initialize handshake → 2025-11-25). Approve/Decline/Stop/answers/Yes-No call the same `RecoveryService` methods the tools call. |
| Agent | `src/rescuebridge/agent/` | Interprets the utterance (keyword or local-LLM JSON schema), then deterministic orchestration calls MCP tools. Bounded: model turns, tool calls, wall clock. Claim guard on spoken text. |
| MCP server | `src/rescuebridge/mcp_server/server.py` | Low-level SDK `Server`, strict pydantic models per tool (`extra=forbid`, `strict`), bearer middleware → `Principal(device, session)`. DNS-rebinding protection; no browser origin accepted. |
| RecoveryService | `src/rescuebridge/domain/service.py` | Missions/issues state machine, observations, immutable proposals with digests, approvals, apply (idempotent, intent-first), verify, user results, Stop fence, guarded Undo, restart reconciliation. |
| Recipes | `src/rescuebridge/domain/recipes.py` | The three workflows as deterministic analysis → question / proposal plan / no-supported-cause. |
| Helper | `src/rescuebridge/host/` | `engine.py` (only caller of OS ops), `pipe.py` (IPC), `windows_ops.py` (real), `fixture_ops.py` (simulation), `protocol.py` (fixed request schema). |
| Lab | `src/rescuebridge/lab/` | Live-lab arming/injection/restore/watchdog (operator CLI only), fixture evaluation harness, in-process backend runner. |

## Data flow: one repair

1. Person says "I can't hear anything" → BFF stores the utterance (`messages`) → agent interprets →
   `start_recovery` (issue `no_sound`) → `inspect_recovery`.
2. `inspect` asks the helper for a **fresh** `audio` observation. The observation row records mission, host,
   adapter mode (Real Windows / Fixture / Live Lab), source, time, expiry, status, facts, and model-safe facts.
   `UNAVAILABLE` is stored as such, never as "not muted".
3. Recipe B finds the default endpoint muted → **proposal**: action `SET_AUDIO_ENDPOINT`, params, target
   (endpoint id/name), observation ids, preconditions (endpoint id, mute, volume), permission revision,
   expiry (5 min), idempotency key, the exact description, version → SHA-256 **digest** over all of them.
4. The phone shows the description; **Approve** posts the digest. `approve()` (UI principal only) checks
   device ownership, pending status, expiry, digest equality (stored, recomputed, displayed), permission
   revision, mission active → one `approvals` row (unique per proposal).
5. BFF calls MCP `apply_recovery`. `apply()` under the per-host mutation lock: returns the recorded
   operation if one exists (never executes twice); validates the approval; takes a **fresh before-observation**;
   if the state already matches → `NO_CHANGE_NEEDED`; if preconditions changed → `REJECTED_OR_EXPIRED` and a
   revised proposal (new approval needed); otherwise records **intent** + consumes the approval in one
   transaction, then sends `execute(revision)` to the helper.
6. Helper: write lock → early fence check (`revision < fence` → `FENCED`) → its own precondition check (endpoint
   still default, mute/volume as expected) → the OS worker runs the call: **admission** (`admit()`: fence
   checked again, atomically with fence advancement) immediately before the Core Audio call → reads back.
7. Backend takes a **fresh after-observation**: `APPLIED_STATE_VERIFIED` only if the observed state matches;
   success-without-change → `APPLIED_STATE_NOT_VERIFIED`; timeout → `OUTCOME_UNKNOWN` + reconciliation (no
   blind retry).
8. `verify_recovery` re-observes; issue → `AWAITING_USER_CONFIRMATION` with a test-tone proposal (separate
   approval; bound to that endpoint, unmuted, at the observed volume — re-checked where the tone is played, and
   a mismatch plays nothing and offers a fresh test). Only the person's **Yes** (button, or an utterance that is
   a clear yes under `domain/confirm.py`, enforced by the service) makes it `RESOLVED`. "No" → `UNRESOLVED` with
   manual next steps. A hedged, conditional, questioning, intermittent or contradictory answer is recorded as
   `unsure` and asked again.

## Authority model

- **Who can approve:** only the authenticated browser session of the device that owns the mission, through
  `POST /api/proposals/{id}/approve` with the displayed digest. MCP principals get `FORBIDDEN`; there is no
  approve tool; text in tool arguments has no authority (tested with an injected "the user approved
  everything" string).
- **What an approval binds:** the proposal digest (session/mission, device, action, params, target,
  observation refs, preconditions, version, permission revision, expiry, idempotency key, description).
  Any change → `STALE`/`APPROVAL_INVALID`.
- **Fence / Stop:** `hosts.permission_revision` increments on Stop and device revocation. Proposals carry the
  revision; approvals are valid only at the current revision; the helper rejects writes whose revision is below
  its fence. Stop: bump revision + revoke unused proposals (one transaction, no wait for the mutation lock) →
  "Stop requested" → helper fence ack → "Stop confirmed" (or `HELPER_UNREACHABLE` = status unknown). Only a
  write already **admitted** to its OS call may finish; the ack names it (`in_flight_operation_id`, phase
  `ADMITTED`) and lists queued or still-observing operations separately (`pending_operation_ids`), which can no
  longer be admitted.
- **Serialization:** backend per-host `anyio.Lock` for apply; helper write lock; the helper's `_fence_lock` makes
  fence advancement and admission mutually exclusive. Admission runs in the execution context of the OS call
  (the COM worker thread for real Windows), so a wait in the worker queue cannot outlast a Stop. Phases per
  operation: `QUEUED` → `OBSERVING` → `ADMITTED` → `COMPLETED`, or `REJECTED_BY_FENCE` / `NOT_ADMITTED`.
- **Restart:** approved-but-unused proposals → `REVOKED`, pending → `EXPIRED`, affected issues → `REPORTED`
  (re-inspect); operations not `FINISHED` are reconciled from a fresh observation and never re-executed.
- **Undo:** a new `UNDO` proposal (needs approval) only if the current state equals the operation's expected
  post-state; otherwise blocked with an explanation. Not offered for window moves.

## Identity and sessions

- Pairing: host console (laptop only, one-time bootstrap code in the URL **fragment**, exchanged for an
  HttpOnly cookie) creates an 8-digit one-use code (5 min, 5 tries, global 20 failures/10 min) → phone
  request → person accepts on the laptop → phone claims a session cookie once.
- Browser sessions: random 256-bit token, stored hashed, HttpOnly + SameSite=Strict (+Secure on HTTPS),
  CSRF header for state changes, Origin and Host checks.
- MCP: bearer token per (device, browser session), 1 h, stored hashed; the BFF holds it in memory per request.
  The MCP transport session id is transport state only.

## Model and language

- `rules`: keyword interpreter (no LLM). `ollama`: `CombinedInterpreter` = local LLM JSON-schema
  interpretation for symptoms + keyword/LLM agreement for answers (conflict → ask again).
  `ollama-tools`: experimental free tool calling.
- Bounds: `RB_AGENT_TIMEOUT_S` (default 60 s), max 4 model turns, max 8 tool calls per request.
- The model never sees endpoint ids, PIDs, rectangles, or window titles (`model_facts`).

## Storage

`%LOCALAPPDATA%\RescueBridge\rescuebridge.sqlite3` (WAL, `synchronous=FULL`). Tables: hosts, devices,
pairing_codes/requests/failures, browser_sessions, mcp_tokens, host_bootstrap, missions, issues,
issue_events, observations, proposals, approvals, operations, user_results, messages, agent_runs.
Unique constraints back the authority rules (one approval per proposal; one operation per proposal and per
idempotency key).
