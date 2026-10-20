"""Language-model providers. Exactly one is configured explicitly; there is no silent fallback.

- `ollama`: a local Ollama model with tool calling (data stays on this laptop).
- `rules`: NOT a language model. A deterministic keyword interpreter, labelled as such everywhere. Used for
  tests, for machines without a suitable local model, and as a deliberately simple baseline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx2


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ProviderReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    latency_ms: int = 0
    raw_error: str | None = None


class ProviderError(Exception):
    pass


class OllamaProvider:
    kind = "ollama"

    def __init__(self, url: str, model: str) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.data_destination = f"local Ollama at {self.url} (this laptop)"

    async def version(self) -> str | None:
        try:
            async with httpx2.AsyncClient(timeout=3.0) as c:
                r = await c.get(f"{self.url}/api/version")
                return str(r.json().get("version"))
        except Exception:  # noqa: BLE001 - reported as unreachable
            return None

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout_s: float) -> ProviderReply:
        body = {
            "model": self.model, "messages": messages, "stream": False, "keep_alive": "15m",
            "options": {"temperature": 0.1, "num_ctx": 4096, "num_predict": 400},
            "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                        "parameters": t["input_schema"]}} for t in tools],
        }
        t0 = time.perf_counter()
        try:
            async with httpx2.AsyncClient(timeout=httpx2.Timeout(timeout_s)) as c:
                r = await c.post(f"{self.url}/api/chat", json=body)
        except httpx2.TimeoutException as exc:
            raise ProviderError(f"model timed out after {timeout_s:.0f}s") from exc
        except httpx2.HTTPError as exc:
            raise ProviderError(f"Ollama unreachable at {self.url}: {type(exc).__name__}") from exc
        ms = round((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            raise ProviderError(f"Ollama HTTP {r.status_code}: {r.text[:200]}")
        msg = r.json().get("message", {})
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments")
            if isinstance(args, str):
                import json

                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"_unparseable": args[:200]}
            calls.append(ToolCall(name=str(fn.get("name", ""))[:80], arguments=args if isinstance(args, dict) else {}))
        return ProviderReply(content=str(msg.get("content") or "").strip(), tool_calls=calls, latency_ms=ms)
