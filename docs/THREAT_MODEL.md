# Threat model

Scope: the prototype as built (laptop backend + helper, browser on the same laptop, or a paired phone on the
same Wi-Fi or on a USB cable via `adb reverse`). Not a formal assessment; no external review or penetration test has been done.

## Assets

- The ability to change three Windows settings for the current user (mouse primary button, default
  playback endpoint mute/volume, top-level window position) and to play a short test tone.
- Diagnostic data: endpoint names, app executable names, window geometry (titles stay in the helper).
- Credentials: session cookies, MCP bearer tokens, helper key, pairing and bootstrap codes, LAN TLS key.
- Recovery evidence (observations, approvals, operations, person results).

## Trust assumptions

- The laptop's Windows account is not compromised. Any process running as the same user can already change
  these settings directly, so RescueBridge does not try to defend against same-user malware beyond not
  adding new remote attack surface.
- The person physically controls the laptop at pairing time and the paired phone afterwards.
- The local LLM (if used) is untrusted for authorization: it can only produce interpretation fields.

## Threats and controls

| Threat | Control (implemented) | Residual gap |
|---|---|---|
| Model or prompt-injected text authorizes a change | No approve tool; `approve()` refuses non-UI principals; approval bound to digest of the displayed proposal; untrusted tool text tested (`test_mcp_protocol_initialize_list_call_and_rejections`) | The model can still *propose* (harmless) or mis-state facts in speech; claim guard removes unsupported completion/approval sentences only |
| Model claims "fixed" prematurely | Server-generated status; RESOLVED requires a person result; claim guard on spoken text; evaluation counts false completion claims | Guard is regex-based (English) |
| Stray "yes" interpreted as approval | Voice never approves; approval is a button with the exact proposal; confirmations via model need a later utterance that the service itself classifies as a clear yes/no (`domain/confirm.py`; hedged, conditional, questioning, intermittent or contradictory → `unsure`, asked again; an LLM label cannot override it), otherwise buttons; tested (`tests/test_confirmation.py`) | Polarity check is English keyword-based |
| Replay / stale approval | Unique approval per proposal; expiry 5 min; digest; permission revision; one operation per proposal; restart revokes unused approvals | — |
| Target swap (HWND reuse, endpoint switch, monitor change) | Helper-issued target refs bound to HWND + PID + process creation time + exe + class; backend and helper re-check preconditions immediately before the change; mismatch → rejected + revised proposal | Small TOCTOU window between helper check and the OS call |
| Stop not honoured by queued work | Revision fence in DB and in the helper; admission gate in the OS-call execution context, atomic with fence advancement, for every mutation incl. Undo; tested deterministically (`tests/test_stop_fence.py`) | A write already admitted to its OS call completes (reported as in flight) |
| Approved test tone plays under changed conditions | Endpoint, unmuted state and volume are in the digest-bound proposal and re-checked in the OS worker before playback; mismatch → not played, fresh proposal (`tests/test_tone_binding.py`) | — |
| Cross-device / cross-session access | All lookups scoped by device; other devices get NOT_FOUND; MCP principal from the bearer token, never from arguments; tested | Single-user, single-laptop design |
| CSRF / malicious web page | SameSite=Strict HttpOnly cookies, CSRF header, Origin allow-list, Host allow-list (DNS rebinding), CSP `default-src 'self'`, `frame-ancestors 'none'` | — |
| Pairing code guessing | 8 digits, one use, 5 min, 5 tries per code, 20 failures/10 min global, plus explicit acceptance on the laptop | Codes are visible on the laptop screen (shoulder surfing) |
| Credentials in URLs/logs | Cookies only; host bootstrap and QR use URL fragments (never sent to the server); no secret appears in any URL path or query; tokens stored hashed; servers log at warning level (no access lines) | The one-time host link is written to a current-user-only file |
| Helper reachable by others | Named pipe with current-user-only DACL, `PIPE_REJECT_REMOTE_CLIENTS`, first-instance flag (no squatting), mutual HMAC with a per-start key in a current-user-only file; browsers cannot open pipes; tested DACL | Administrators/SYSTEM can still access (expected on Windows) |
| MCP App card abused (script in the view, clickjacking, extra tool calls) | The view is served from the MCP resource unchanged into an iframe with `sandbox="allow-scripts"` (opaque origin, no cookies) plus its own CSP (`default-src 'none'`, `connect-src 'none'`, `sandbox allow-scripts`, `frame-ancestors 'self'`); the host answers only `ui/initialize`, size changes and `tools/call` for `get_recovery_status` (allow-listed again in the backend); the view renders data with `textContent` only; it has no approve, apply, stop or undo path | Simplified host: a single sandboxed frame, not the spec's separate-origin sandbox proxy; not tested in a third-party MCP Apps host |
| MCP endpoint exposed | Bound to 127.0.0.1 only, bearer required, no browser Origin allowed; LAN mode exposes only the BFF, never MCP or the helper | — |
| Elevation / integrity bypass | Runs non-elevated; windows of higher-integrity processes reported unsupported; no privileged APIs | — |
| Persistent side effects | No firewall rules, certificates in trust stores, startup items, services, or drivers are created | Self-signed LAN cert must be accepted per phone |
| Lab faults left behind | Lab requires explicit arming with scope and ≤30 min; snapshot; foreground watchdog restores at expiry/Ctrl+C; manual `lab restore`; temporary mouse swap reverts at sign-out | Power loss or a killed watchdog leaves audio/WorkPad faults until `lab restore` |
| USB mode: other apps on the phone, or a phone connection posing as "local" | `adb reverse` is added only for one authorized phone and only to the BFF port (never MCP or the helper); pairing still needs the code and acceptance on the laptop; the host console still needs the one-time bootstrap secret that exists only in a current-user file on the laptop; `stop.ps1` and a clean exit remove the mapping; device serials are never logged | While the tunnel exists, any app on that phone can reach the BFF like a browser on the laptop can; the host console's "laptop only" address check cannot tell adb-forwarded connections from local ones (the bootstrap secret is the real control); anyone with USB debugging access to the phone already controls it |
| LAN eavesdropping | HTTPS with a locally generated certificate | Self-signed: the person must verify they are on their own laptop's address |
| Denial of service from the LAN | Rate limits on pairing only | No general rate limiting; prototype |

## Limits of device identity in this prototype

A "paired device" is a browser session cookie issued after the person accepted the pairing request on the
laptop. There is no hardware attestation, no passkey, and no binding to the phone's OS account: anyone who
obtains that browser profile (or the cookie) is the device until it expires (12 h) or is revoked in the host
console. Revocation takes effect on the next request and bumps the permission revision, which invalidates any
outstanding proposal or approval.

## Not addressed

Multi-user laptops with mutually hostile accounts, malware running as the same user, physical attackers
with the unlocked laptop, side channels, supply-chain verification beyond pinned lockfiles.
