"""Interpreter accuracy/latency on the dev cases and the frozen held-out phrasing set.

Compares the keyword interpreter (no LLM) with local Ollama models used for schema-constrained
interpretation. Exact-match scoring on symptom sets; answers scored on the expected field only.
Writes JSON evidence. Changes nothing on Windows; downloads nothing.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from statistics import median
from typing import Any

import anyio

from rescuebridge.agent.interpret import Interpretation, interpret
from rescuebridge.agent.llm_interpret import OllamaInterpreter
from rescuebridge.agent.providers import ProviderError
from rescuebridge.bench_model import CASES
from rescuebridge.domain.recipes import analyze_mouse  # noqa: F401 - documents where the mouse question comes from

MOUSE_Q = ("Which physical button do you want for normal clicking: the LEFT button (usual for right-handed use) or "
           "the RIGHT button (often chosen for left-handed use)?")
CONFIRM_Q = "Approve the test tone, then tell me: did you hear it?"


def _load_heldout(root: Path) -> dict[str, Any]:
    return json.loads((root / "scenarios" / "heldout_phrasings.json").read_text(encoding="utf-8"))


def _score_answer(it: Interpretation, expected: dict[str, Any]) -> bool:
    if "primary_button" in expected:
        return it.primary_button == expected["primary_button"]
    if "answer" in expected:
        got = "yes" if it.yes else "no" if it.no else "none"
        return got == expected["answer"]
    return False


async def _evaluate(name: str, fn: Any, symptom_sets: dict[str, list[tuple[str, set[str]]]],
                    answers: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"interpreter": name, "sets": {}}
    latencies: list[int] = []
    for set_name, cases in symptom_sets.items():
        rows = []
        for text, expected in cases:
            t0 = time.perf_counter()
            try:
                it, _ = await fn(text, None)
                got = set(it.categories) or {"(none)"}
                err = None
            except ProviderError as exc:
                got, err = set(), str(exc)
            ms = round((time.perf_counter() - t0) * 1000)
            latencies.append(ms)
            rows.append({"text": text, "expected": sorted(expected), "got": sorted(got), "correct": got == expected,
                         "ms": ms, "error": err})
        out["sets"][set_name] = {"correct": sum(r["correct"] for r in rows), "total": len(rows), "rows": rows}
    arows = []
    for a in answers:
        q = MOUSE_Q if a["question"] == "mouse_preference" else CONFIRM_Q
        t0 = time.perf_counter()
        try:
            it, _ = await fn(a["text"], q)
            ok, err = _score_answer(it, a["expected"]), None
            got = {"primary_button": it.primary_button, "answer": "yes" if it.yes else "no" if it.no else "none"}
        except ProviderError as exc:
            ok, err, got = False, str(exc), {}
        ms = round((time.perf_counter() - t0) * 1000)
        latencies.append(ms)
        arows.append({"text": a["text"], "expected": a["expected"], "got": got, "correct": ok, "ms": ms, "error": err})
    out["sets"]["heldout_answers"] = {"correct": sum(r["correct"] for r in arows), "total": len(arows), "rows": arows}
    out["latency_ms"] = {"first": latencies[0] if latencies else None,
                         "median_after_first": median(latencies[1:]) if len(latencies) > 1 else None,
                         "max_after_first": max(latencies[1:]) if len(latencies) > 1 else None}
    out["errors"] = sum(1 for s in out["sets"].values() for r in s["rows"] if r.get("error"))
    return out


async def bench(models: list[str], url: str, timeout_s: float, root: Path) -> dict[str, Any]:
    held = _load_heldout(root)
    sets = {"dev": [(t, e) for t, e in CASES],
            "heldout_symptoms": [(c["text"], set(c["expected"])) for c in held["symptoms"]]}
    res: dict[str, Any] = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": platform.node(),
                           "interpreters": []}

    async def keyword(text: str, _q: str | None) -> tuple[Interpretation, int]:
        return interpret(text), 0

    res["interpreters"].append(await _evaluate("keyword (no LLM)", keyword, sets, held["answers"]))
    for model in models:
        llm = OllamaInterpreter(url, model)

        async def via_llm(text: str, q: str | None, _llm: OllamaInterpreter = llm) -> tuple[Interpretation, int]:
            return await _llm.interpret(text, q, timeout_s=timeout_s)

        res["interpreters"].append(await _evaluate(f"ollama {model} (structured JSON)", via_llm, sets, held["answers"]))
    return res


def run(models: list[str], url: str, timeout_s: float, out_dir: Path) -> Path:
    root = Path(__file__).resolve().parents[2]
    res = anyio.run(bench, models, url, timeout_s, root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"interpreter_bench_{time.strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(res, indent=2), encoding="utf-8")
    for r in res["interpreters"]:
        sets = ", ".join(f"{k} {v['correct']}/{v['total']}" for k, v in r["sets"].items())
        print(f"{r['interpreter']}: {sets}; errors {r['errors']}; latency {r['latency_ms']}")
    print(f"evidence: {path}")
    return path
