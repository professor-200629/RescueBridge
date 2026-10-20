"""Local-LLM interpretation with a JSON-schema-constrained output (Ollama structured outputs).

The model performs ONE bounded task per utterance: map the person's words (and, if a question is pending,
their answer) onto closed fields. Deterministic code then decides which MCP tools to call. If the model output
is missing, late, or invalid, the request fails visibly; there is no silent fallback to another interpreter.
"""

from __future__ import annotations

import json
import time
from typing import Literal

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rescuebridge.agent.interpret import Interpretation
from rescuebridge.agent.providers import ProviderError

CATEGORY = Literal["mouse_buttons_wrong", "no_sound", "window_missing", "mouse_not_moving", "other"]

SYSTEM = """You turn what a person says about their Windows laptop into JSON. Output only the JSON.
symptoms: every problem they mention, using only these values:
- mouse_buttons_wrong: clicks do the wrong thing (a normal click opens a menu, buttons feel reversed or swapped)
- no_sound: they cannot hear anything, no audio, muted or silent speakers
- window_missing: an app, document or notes window disappeared, is off-screen or cannot be found
- mouse_not_moving: the mouse pointer or cursor does not move or is frozen
- other: any other problem (wifi, printer, crashes, keyboard, black screen, ...)
Use [] when they are only answering a question.
answer: "yes" or "no" if they answer a yes/no question (for example whether they heard a tone or can see a window); otherwise "none".
primary_button: only when they say which mouse button they want for normal clicks or which hand they use:
left-handed -> "right"; right-handed, normal, usual or default -> "left"; otherwise null.
app_name: the app they say is missing (one or two words), otherwise null.
stop: true only if they ask to stop or cancel. undo: true only if they ask to undo or revert a change.
volume_percent: a number only if they ask for a specific volume, otherwise null."""


class LlmFields(BaseModel):
    model_config = ConfigDict(extra="ignore")
    symptoms: list[CATEGORY] = Field(default_factory=list, max_length=5)
    answer: Literal["yes", "no", "none"] = "none"
    primary_button: Literal["left", "right"] | None = None
    app_name: str | None = Field(default=None, max_length=40)
    stop: bool = False
    undo: bool = False
    volume_percent: int | None = Field(default=None, ge=0, le=100)


SCHEMA = {
    "type": "object",
    "properties": {
        "symptoms": {"type": "array", "items": {"type": "string", "enum": list(CATEGORY.__args__)}},  # type: ignore[attr-defined]
        "answer": {"type": "string", "enum": ["yes", "no", "none"]},
        "primary_button": {"type": ["string", "null"], "enum": ["left", "right", None]},
        "app_name": {"type": ["string", "null"]},
        "stop": {"type": "boolean"},
        "undo": {"type": "boolean"},
        "volume_percent": {"type": ["integer", "null"]},
    },
    "required": ["symptoms", "answer", "primary_button", "app_name", "stop", "undo", "volume_percent"],
}


class OllamaInterpreter:
    kind = "ollama"

    def __init__(self, url: str, model: str) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.data_destination = f"local Ollama at {self.url} (this laptop)"

    async def interpret(self, text: str, pending_question: str | None, timeout_s: float) -> tuple[Interpretation, int]:
        user = f"Pending question: {pending_question}\nPerson said: {text}" if pending_question else f"Person said: {text}"
        body = {"model": self.model, "stream": False, "keep_alive": "15m", "format": SCHEMA,
                "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 160},
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
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
        content = r.json().get("message", {}).get("content", "")
        try:
            fields = LlmFields.model_validate(json.loads(content))
        except (ValueError, ValidationError) as exc:
            raise ProviderError(f"model returned invalid JSON for the interpretation schema: {content[:120]!r}") from exc
        it = Interpretation(categories=list(dict.fromkeys(fields.symptoms)), app_hint=(fields.app_name or None),
                            stop=fields.stop, undo=fields.undo, yes=fields.answer == "yes", no=fields.answer == "no",
                            primary_button=fields.primary_button, volume_percent=fields.volume_percent)
        if it.app_hint:
            it.app_hint = it.app_hint.strip()[:40] or None
        return it, ms
