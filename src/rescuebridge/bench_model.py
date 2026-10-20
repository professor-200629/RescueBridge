"""Small local latency/correctness check for tool-capable Ollama models (no downloads).

For each case the model gets the real system prompt and the real MCP tool schemas and must answer the
person's first utterance with a `start_recovery` call carrying the right symptom categories. Measures
first-turn latency (including cold load for the first case) and correctness. Results are written as JSON
evidence; nothing here changes Windows state.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any

import anyio

from rescuebridge.agent.loop import SYSTEM_PROMPT
from rescuebridge.agent.providers import OllamaProvider, ProviderError
from rescuebridge.mcp_server.server import StartArgs, _tool_defs

CASES: list[tuple[str, set[str]]] = [
    ("My clicks are wrong and I can't hear anything", {"mouse_buttons_wrong", "no_sound"}),
    ("The sound is gone completely", {"no_sound"}),
    ("My notes window disappeared", {"window_missing"}),
    ("Left click opens the right-click menu", {"mouse_buttons_wrong"}),
    ("The mouse pointer is frozen and won't move", {"mouse_not_moving"}),
    ("My wifi keeps disconnecting", {"other"}),
    ("I can't hear the interviewer and WorkPad vanished off the screen", {"no_sound", "window_missing"}),
    ("Nothing plays through the speakers", {"no_sound"}),
]


def _tools() -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in _tool_defs()]


async def bench(models: list[str], url: str, timeout_s: float) -> dict[str, Any]:
    tools = _tools()
    status: dict[str, Any] = {"adapter": "Fixture Simulation", "mission": None, "issues": []}
    out: dict[str, Any] = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": platform.node(),
                           "cpu": platform.processor(), "ollama_url": url, "cases": len(CASES), "models": {}}
    for model in models:
        prov = OllamaProvider(url, model)
        out["ollama_version"] = await prov.version()
        rows: list[dict[str, Any]] = []
        for i, (text, expected) in enumerate(CASES):
            messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n\nCurrent server status (authoritative):\n"
                         + json.dumps(status)},
                        {"role": "user", "content": f"{text}\n\n[utterance_id: msg_bench{i:04d}]"}]
            t0 = time.perf_counter()
            try:
                reply = await prov.chat(messages, tools, timeout_s=timeout_s)
            except ProviderError as exc:
                rows.append({"text": text, "error": str(exc), "ms": round((time.perf_counter() - t0) * 1000)})
                continue
            call = next((c for c in reply.tool_calls if c.name == "start_recovery"), None)
            got: set[str] = set()
            schema_ok = False
            if call:
                try:
                    args = StartArgs.model_validate(call.arguments)
                    schema_ok = True
                    got = {s.category for s in args.symptoms}
                except Exception:  # noqa: BLE001 - counted as a schema failure
                    got = {str(s.get("category")) for s in call.arguments.get("symptoms", []) if isinstance(s, dict)} \
                        if isinstance(call.arguments.get("symptoms"), list) else set()
            rows.append({"text": text, "expected": sorted(expected), "tool_calls": [c.name for c in reply.tool_calls],
                         "categories": sorted(got), "schema_ok": schema_ok, "correct": schema_ok and got == expected,
                         "ms": reply.latency_ms, "cold": i == 0, "content_preview": reply.content[:120]})
        ok = [r for r in rows if r.get("correct")]
        warm: list[int] = [int(r["ms"]) for r in rows if "ms" in r and not r.get("cold") and "error" not in r]
        out["models"][model] = {
            "correct": len(ok), "total": len(rows), "schema_ok": sum(1 for r in rows if r.get("schema_ok")),
            "errors": sum(1 for r in rows if "error" in r),
            "cold_first_ms": rows[0].get("ms") if rows else None,
            "warm_median_ms": sorted(warm)[len(warm) // 2] if warm else None,
            "warm_max_ms": max(warm) if warm else None,
            "rows": rows,
        }
    return out


def run(models: list[str], url: str, timeout_s: float, out_dir: Path) -> Path:
    res = anyio.run(bench, models, url, timeout_s)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"model_bench_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(res, indent=2), encoding="utf-8")
    for m, r in res["models"].items():
        print(f"{m}: {r['correct']}/{r['total']} correct, schema_ok {r['schema_ok']}, errors {r['errors']}, "
              f"cold {r['cold_first_ms']} ms, warm median {r['warm_median_ms']} ms, warm max {r['warm_max_ms']} ms")
    print(f"evidence: {path}")
    return path
