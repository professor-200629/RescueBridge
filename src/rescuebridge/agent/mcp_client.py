"""Real MCP client (Streamable HTTP, initialize handshake) used by the backend-for-frontend.

A fresh MCP connection (and transport session) is opened per agent run / UI action. Application state is
bound to the device's bearer token, not to the transport session, so replacing transport sessions never
loses or crosses state.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation


class McpToolClient:
    def __init__(self, url: str, bearer_token: str, *, timeout_s: float = 30.0) -> None:
        self.url = url
        self._token = bearer_token
        self._timeout_s = timeout_s
        self._http: httpx2.AsyncClient | None = None
        self._client: Client | None = None
        self.protocol_version: str | None = None
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> McpToolClient:
        self._http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {self._token}"},
                                        timeout=httpx2.Timeout(self._timeout_s, read=self._timeout_s))
        self._client = Client(streamable_http_client(self.url, http_client=self._http), mode="legacy", cache=None,
                              client_info=Implementation(name="rescuebridge-bff", version="0.1.0"),
                              read_timeout_seconds=self._timeout_s)
        await self._client.__aenter__()
        self.protocol_version = self._client.protocol_version
        return self

    async def __aexit__(self, *exc: Any) -> None:
        try:
            if self._client is not None:
                await self._client.__aexit__(*exc)
        finally:
            if self._http is not None:
                await self._http.aclose()

    async def list_tools(self) -> list[dict[str, Any]]:
        assert self._client is not None
        res = await self._client.list_tools()
        return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in res.tools]

    async def call(self, name: str, arguments: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
        assert self._client is not None
        t0 = time.perf_counter()
        res = await self._client.call_tool(name, arguments or {})
        payload: dict[str, Any]
        if isinstance(res.structured_content, dict):
            payload = res.structured_content
        else:
            text = "".join(getattr(c, "text", "") for c in res.content)
            try:
                payload = json.loads(text) if text else {}
            except ValueError:
                payload = {"text": text}
        ms = round((time.perf_counter() - t0) * 1000)
        self.calls.append({"tool": name, "arguments": arguments, "is_error": bool(res.is_error), "ms": ms})
        return payload, bool(res.is_error)
