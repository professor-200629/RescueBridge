# Threat model

Scope: the prototype as built (laptop backend + helper, browser on the same laptop or a paired phone on the
same Wi-Fi). Not a formal assessment; no external review or penetration test has been done.

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
| Stray "yes" interpreted as approval | Voice never approves; approval is a button with the exact proposal; confirmations via model need a later utterance passing a polarity check, otherwise buttons | Polarity check is English keyword-based |
| Replay / stale approval | Unique approval per proposal; expiry 5 min; digest; permission revision; one operation per proposal; restart revokes unused approvals | — |
| Target swap (HWND reuse, endpoint switch, monitor change) | Helper-issued target refs bound to HWND + PID + process creation time + exe + class; backend and helper re-check preconditions immediately before the change; mismatch → rejected + revised proposal | Small TOCTOU window between helper check and the OS call |
| Stop not honoured by queued work | Revision fence in DB and in the helper; queued helper writes re-check after the lock; tested | A write already inside its OS call completes (reported) |
| Cross-device / cross-session access | All lookups scoped by device; other devices get NOT_FOUND; MCP principal from the bearer token, never from arguments; tested | Single-user, single-laptop design |
| CSRF / malicious web page | SameSite=Strict HttpOnly cookies, CSRF header, Origin allow-list, Host allow-list (DNS rebinding), CSP `default-src 'self'`, `frame-ancestors 'none'` | — |
| Pairing code guessing | 8 digits, one use, 5 min, 5 tries per code, 20 failures/10 min global, plus explicit acceptance on the laptop | Codes are visible on the laptop screen (shoulder surfing) |
| Credentials in URLs/logs | Cookies only; host bootstrap and QR use URL fragments (never sent to the server); no secret appears in any URL path or query; tokens stored hashed; servers log at warning level (no access lines) | The one-time host link is written to a current-user-only file |
| Helper reachable by others | Named pipe with current-user-only DACL, `PIPE_REJECT_REMOTE_CLIENTS`, first-instance flag (no squatting), mutual HMAC with a per-start key in a current-user-only file; browsers cannot open pipes; tested DACL | Administrators/SYSTEM can still access (expected on Windows) |
| MCP endpoint exposed | Bound to 127.0.0.1 only, bearer required, no browser Origin allowed; LAN mode exposes only the BFF, never MCP or the helper | — |
| Elevation / integrity bypass | Runs non-elevated; windows of higher-integrity processes reported unsupported; no privileged APIs | — |
| Persistent side effects | No firewall rules, certificates in trust stores, startup items, services, or drivers are created | Self-signed LAN cert must be accepted per phone |
| Lab faults left behind | Lab requires explicit arming with scope and ≤30 min; snapshot; foreground watchdog restores at expiry/Ctrl+C; manual `lab restore`; temporary mouse swap reverts at sign-out | Power loss or a killed watchdog leaves audio/WorkPad faults until `lab restore` |
| LAN eavesdropping | HTTPS with a locally generated certificate | Self-signed: the person must verify they are on their own laptop's address |
| Denial of service from the LAN | Rate limits on pairing only | No general rate limiting; prototype |

## Not addressed

Multi-user laptops with mutually hostile accounts, malware running as the same user, physical attackers
with the unlocked laptop, side channels, supply-chain verification beyond pinned lockfiles.
