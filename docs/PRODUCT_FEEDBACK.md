# Product feedback

## Which developer tools, APIs and SDKs were used, and for what?

| Tool | Used for |
|---|---|
| Model Context Protocol, spec 2025-11-25, Streamable HTTP | The Alexa+ track surface: RescueBridge exposes nine recovery tools from a self-hosted MCP server. |
| MCP Python SDK 2.3.0 (`mcp`) | Server (low-level `Server` + `streamable_http_app`, transport security) and the real client in the backend (`Client`, `streamable_http_client`, `mode="legacy"`). |
| Ollama 0.32.3 + qwen2.5:3b-instruct (local) | Optional language understanding with JSON-schema structured outputs. |
| Windows APIs via pywin32 / ctypes / pycaw | Named-pipe IPC with DACLs; mouse, Core Audio, window and monitor operations. |
| Vite 8 + TypeScript 6 | Browser simulator (no runtime framework). |
| uv, pytest, ruff, mypy | Environment, tests, lint, types. |

No gated Alexa+ tools (not available to participants), no Amazon Devices Builder Tools, and no AWS services
were used. Product feedback below is therefore about the open MCP path the Alexa+ track specifies, and the
hackathon materials.

## What worked well

- The MCP SDK's Streamable HTTP server gives DNS-rebinding protection (Host/Origin allow-lists) out of the box
  and passes the HTTP request into each handler's context, which made per-request bearer authorization easy.
- The SDK's helpful `ModuleNotFoundError` for the FastMCP rename saved time.
- Protocol version negotiation is explicit and testable (`client.protocol_version == "2025-11-25"`).
- The hackathon FAQ answered the key question clearly: a web page acting as a real MCP client satisfies the
  Alexa+ requirement, and hosting is not required.

## What needs work

- Strict argument validation is not available for `@tool` functions (unknown properties are dropped).
- Client defaults favour the newer 2026-07-28 discovery; the way to target 2025-11-25 is easy to miss.
- No public way to try an Alexa+ host: participants cannot validate how an Alexa+ surface would present
  approval or confirmation steps for consequential actions.
- Guidance for small, on-device models using MCP tools is missing; tool-heavy surfaces fail on 3B models.

## Onboarding (zero to hello world)

About 30 minutes: reading the installed SDK started at roughly 22:30 and the first end-to-end test passing
`initialize`/`tools/list`/`tools/call` over Streamable HTTP was committed at 22:59 (commit `c6df304`), together
with the backend and pairing code. Much of that time went into reading the installed 2.x source because the
1.x patterns no longer applied.

## Would we build with these again?

Yes, for the MCP server/client path: the protocol and SDK made it possible to keep authorization in one
deterministic service while still letting a model or an external assistant call the tools. A public Alexa+
test surface would make it much easier to design the voice interaction for real.
