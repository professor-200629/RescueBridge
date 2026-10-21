# Friction log

Genuine problems encountered while building RescueBridge on 2026-10-20 (Windows 11, Python 3.13, MCP Python
SDK 2.3.0). Only tools actually used are listed.

### 1. MCP Python SDK 2.x: v1 examples no longer work

- **Task:** create an MCP server with Streamable HTTP.
- **Steps:** followed the common `from mcp.server.fastmcp import FastMCP` pattern.
- **Expected:** server object. **Actual:** `ModuleNotFoundError` explaining FastMCP is now
  `mcp.server.mcpserver.MCPServer` (helpful message with a migration-guide link).
- **Severity:** Medium (time lost reading installed source to confirm the new APIs).
- **Workaround:** read the installed package; used `MCPServer`/low-level `Server` APIs as installed.
- **Suggestion:** Alexa+ track resources could link the SDK v2 migration guide and a v2 Streamable HTTP sample.

### 2. MCPServer tool arguments silently ignore unknown properties

- **Task:** reject malformed tool calls (unknown properties) for security.
- **Steps:** registered tools with `@server.tool()`; inspected the generated argument model.
- **Expected:** `additionalProperties: false` or a rejection. **Actual:** the generated pydantic model has
  default `extra` handling, so unknown properties are dropped silently (e.g. `"approved": true` would vanish
  rather than fail).
- **Severity:** Medium for security-sensitive tools.
- **Workaround:** used the low-level `Server` with explicit `on_list_tools`/`on_call_tool` and my own strict
  pydantic models (`extra="forbid"`, `strict=True`), publishing `additionalProperties: false`.
- **Suggestion:** an opt-in strict mode on `@tool` (forbid extras, strict types).

### 3. Targeting protocol 2025-11-25 with the 2.x client needs `mode="legacy"`

- **Task:** make the client negotiate the version the track requires.
- **Actual:** the client default (`mode="auto"`) probes `server/discover` (2026-07-28) first. Using
  `mode="legacy"` forces the initialize handshake and negotiates 2025-11-25.
- **Severity:** Low. **Suggestion:** document which mode yields which protocol version in the client docstring.

### 4. Client cannot send non-finite numbers, so server-side NaN handling needs raw JSON-RPC to test

- **Task:** test that the server rejects non-finite numbers.
- **Actual:** the SDK client serialized `1e309` as `null`, so the server saw a valid call. Testing required a raw
  HTTP JSON-RPC request containing `NaN`.
- **Severity:** Low. **Workaround:** raw `httpx2` request in the test.

### 5. Custom headers on the Streamable HTTP client go through `httpx2`

- **Actual:** the SDK depends on `httpx2` (not `httpx`); the bearer header is set via
  `streamable_http_client(url, http_client=httpx2.AsyncClient(headers=...))`.
- **Severity:** Low. **Suggestion:** a `headers=` convenience parameter, or a docs snippet for bearer auth.

### 6. Gated Alexa+ tooling is unavailable to participants

- **Task:** test against a real Alexa+ surface.
- **Actual:** per the official FAQ, the Category SDK, MCP Toolkit, CLI and Web Simulator are select-partners
  only. Built an independent browser simulator instead (allowed by the rules).
- **Severity:** Medium for realism (no way to validate Alexa+ host behaviour such as turn-taking or approval UX).
- **Suggestion:** a public, limited Alexa+ MCP test harness or recorded host transcripts for participants.

### 7. Official rules page blocks non-browser fetches

- **Task:** re-verify rules programmatically before packaging.
- **Actual:** HTTP 403 for an automated fetch; the page loaded fine in a regular browser.
- **Severity:** Low. **Workaround:** read in a browser; recorded retrieval time in `SUBMISSION.md`.

### 8. Small local models cannot pick among nine MCP tools

- **Task:** let a local 3B model drive the MCP tools directly.
- **Actual:** qwen2.5:3b-instruct and llama3.2:3b called `inspect_recovery`/`record_user_result` with invented
  ids instead of `start_recovery`; 0/8 correct first calls (`evidence/model_bench_20261020_231602.json`).
- **Severity:** High for on-device agentic designs on 16 GB laptops.
- **Workaround:** the model fills one closed JSON schema; deterministic code calls the MCP tools.
- **Suggestion:** guidance for designing MCP tool surfaces that small on-device models can use (state-scoped
  tool lists, fewer tools per turn).

### 9. First real phone attempt: the pairing QR code pointed at the phone itself (our defect)

- **Task (2026-10-21, owner):** pair the Samsung phone by scanning the host console's QR code.
- **Steps:** `start.ps1 -Fixture -Scenario interview` (no `-Lan`), **Create pairing code**, scan with the phone.
- **Expected:** the RescueBridge page opens on the phone. **Actual:** the link did not open. Without LAN mode
  the backend listens on `127.0.0.1` only and the QR encodes `http://127.0.0.1:8740/#pair=…`, which on a phone
  is the phone. The database confirmed nothing reached RescueBridge (no pairing request, no device).
- **Severity:** High for the core story (the phone is the second channel), and the host console gave no hint.
- **Fix:** USB cable mode (`start.ps1 -Usb`, `adb reverse`), a phone-side reachability check, a warning under
  the QR code when no phone path is active, and backend logs to files (`be3b822`).
- **Suggestion (for MCP/voice-device builders generally):** a second-device demo needs a documented local
  transport; "same Wi-Fi + self-signed HTTPS" fails often enough that a cable fallback is worth shipping.
