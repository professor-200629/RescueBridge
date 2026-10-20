# RescueBridge — durable checkpoint

Read this first after any context reset. Then read `spec/RescueBridge-Claude-Code-Build-Prompt.md`
(original specification, SHA-256 3C4EC4EF…9A8E) and `docs/VALIDATION.md`.

## Gate 0 (done 2026-10-20)

Environment observed (not assumed):
- Windows 11 Home Single Language 10.0.26300, HP Pavilion 16, Intel Core Ultra 5 125U, 16 GB RAM, Intel iGPU.
- User `professor04\balu`, Medium integrity (not elevated).
- Python 3.13.0 (also 3.10/3.11/3.14), uv 0.12.9, Node 24.14.0, npm 11.9.0, git 2.51.2, gh present.
- Ollama 0.32.3 with local models: qwen2.5:3b-instruct, llama3.2:3b, hermes-3-llama-3.1 (8B), dolphin-llama3,
  llava:7b, moondream, bge-m3. No model downloaded by this project.
- MCP Python SDK 2.3.0 (FastMCP renamed MCPServer). Handshake protocol max = 2025-11-25; SDK also speaks 2026-07-28.
  Client pinned to `mode="legacy"` so it negotiates 2025-11-25 via initialize.
- Read-only probe (no changes): SM_SWAPBUTTON=0, saved SwapMouseButtons="0", default render endpoint
  "Speaker (Realtek(R) Audio)" unmuted at 24%, 1 monitor 1920x1200 @120 DPI, work area 1920x1140.

## Plan (small, in order)

1. Domain: enums, schemas, SQLite store, issue state machine, authority (proposal digest, approval, fence).
2. Host layer: fixed op protocol; FixtureSystemOps + WindowsSystemOps; HelperEngine (target refs, fence,
   write lock); named-pipe helper server (current-user DACL + HMAC key) and client.
3. Recipes: audio (Gate 1 first), mouse preference, off-screen window (WorkPad).
4. MCP server (Streamable HTTP, loopback, bearer token bound to paired device) + BFF acting as real MCP client.
5. Agent loop: bounded (4 model turns / 8 tool calls / wall clock), providers = Ollama (local) or explicit
   `rules` keyword interpreter; completion-claim guard.
6. Browser app (Vite + TypeScript): pairing, talk/transcript, proposal card, Stop, evidence, diagnostics.
7. Tests: unit, MCP protocol through real client, helper process, browser smoke; scenario evaluation.
8. Lab: arming, fault injection, watchdog restore, WorkPad; docs.

## Status

See bottom section "Current status" — updated at each checkpoint.

## Current status

- Gate 0 complete. Gate 1 in progress.
