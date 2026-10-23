"""Bounded agent loop. Every tool call goes through the real MCP client.

Bounds (configurable): at most N model turns, M tool calls, and a wall-clock limit per user request.
The final spoken text passes a deterministic claim guard: completion claims that the server status does
not support, and any claim that something was approved, are removed and counted.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from rescuebridge.agent.interpret import interpret
from rescuebridge.agent.mcp_client import McpToolClient
from rescuebridge.agent.providers import OllamaProvider, ProviderError

SYSTEM_PROMPT = """You are RescueBridge, a calm recovery assistant reached from the person's phone while their \
Windows laptop is hard to use. You can only act through the provided tools.
Supported: wrong mouse button mapping, muted/silent default playback device, an app window that is off-screen.
Anything else (including a mouse pointer that does not move) is unsupported: say so plainly.
Process: start_recovery with one symptom per problem -> inspect_recovery for each new issue -> if the result has a \
question, ask exactly that ONE question -> when the person answers, call propose_recovery with the answer.
When a proposal exists, tell the person in one sentence what it will do and that they must tap Approve on their phone. \
You can NEVER approve anything yourself and must never say a change was approved or made unless a tool result shows it.
Never say something is fixed or resolved unless the issue state is RESOLVED.
When the person answers a confirmation question (e.g. whether they heard the tone), call record_user_result with \
their utterance_id. If they say stop, call stop_recovery.
Reply in at most 3 short sentences, plain words, no IDs or technical terms."""

CLAIM_RE = re.compile(r"\b(fixed|resolved|solved|repaired|working (again|now|fine)|all set|back to normal|"
                      r"should (now )?work|problem is gone|good to go)\b", re.I)
APPROVAL_RE = re.compile(r"\b(i('ve| have)? approved|approved (it|this|that|the change)|i('ll| will) approve|"
                         r"you('ve| have) (already )?approved|approval (is )?(granted|given))\b", re.I)
NEGATION_RE = re.compile(r"\b(not|n't|no longer|yet to|until|unless|once|after you|if)\b", re.I)
PROBLEM_RE = re.compile(r"\b(not working|isn'?t working|doesn'?t work|won'?t|can'?t|cannot|broken|keeps|crash\w*|"
                        r"error|slow|problem|issue|disconnect\w*|fail\w*|not (printing|loading|opening|starting|"
                        r"connecting|charging|responding))\b", re.I)


@dataclass
class AgentResult:
    text: str
    provider: str
    model: str | None
    model_turns: int = 0
    tool_calls: int = 0
    timed_out: bool = False
    stop_reason: str = "completed"
    blocked_claims: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    model_latency_ms: list[int] = field(default_factory=list)
    protocol_version: str | None = None
    error: str | None = None


def guard_claims(text: str, status: dict[str, Any]) -> tuple[str, list[str]]:
    resolved = any(i.get("state") == "RESOLVED" for i in status.get("issues", []))
    kept, blocked = [], []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not sentence:
            continue
        if APPROVAL_RE.search(sentence) and not NEGATION_RE.search(sentence):
            blocked.append(sentence)
            continue
        if CLAIM_RE.search(sentence) and not resolved and not NEGATION_RE.search(sentence):
            blocked.append(sentence)
            continue
        kept.append(sentence)
    out = " ".join(kept)
    if blocked:
        out = (out + " " if out else "") + "Nothing is confirmed fixed until you check it yourself."
    return out, blocked


def _compact(payload: Any, limit: int = 3500) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


KIND_TITLE = {"MOUSE_BUTTONS": "Mouse buttons", "AUDIO_OUTPUT": "Sound", "OFFSCREEN_WINDOW": "Missing window",
              "UNSUPPORTED": "That problem"}


MOUSE_QUESTION = "which button should do normal clicks: left, the usual one, or right, for left-handed use?"
UNSURE_REPLY = ("I'm not sure that means it's fixed, so I haven't marked it resolved. Is it working now? "
                "Please say yes or no, or tap a button.")


def _proposal_text(r: dict[str, Any]) -> str:
    props = r.get("open_proposals") or ([r["new_proposal"]] if r.get("new_proposal") else [])
    return str(props[-1].get("description") or "") if props else ""


def _first_sentence(text: str) -> str:
    text = text.strip()
    cut = text.find(". ")
    return text if cut < 0 else text[:cut + 1]


def headline(r: dict[str, Any]) -> str:
    """A short spoken cause for one issue, derived only from what the server observed (no new claims)."""
    kind = str(r.get("kind"))
    facts = " ".join(str(f) for f in r.get("observed_facts") or [])
    if kind == "AUDIO_OUTPUT":
        if "MUTED" in facts:
            return "Your speaker is muted."
        if re.search(r"volume [0-4]%", facts):
            return "Your speaker volume is almost zero."
    if kind == "MOUSE_BUTTONS" and "swapped" in facts:
        return "Your mouse buttons are swapped right now."
    if kind == "OFFSCREEN_WINDOW":
        m = re.search(r"'([^']+)'", _proposal_text(r) or str(r.get("supported_explanation") or ""))
        if m and r.get("state") in ("PROPOSED", "NEEDS_CLARIFICATION"):
            return f"'{m.group(1)}' is off-screen."
    return _first_sentence(str(r.get("supported_explanation") or (r.get("observed_facts") or [""])[0]))


def short_issue_line(r: dict[str, Any]) -> str:
    """One short spoken line per issue, used when a reply covers several issues (the cards hold the detail)."""
    if "error" in r:
        return describe_issue_result(r)
    title = KIND_TITLE.get(str(r.get("kind")), "Issue")
    state = r.get("state")
    if state == "PROPOSED":
        head = headline(r)
        return f"{title}: {head[0].lower() + head[1:] if head.startswith('Your') else head}"
    if state == "NEEDS_CLARIFICATION":
        if r.get("kind") == "MOUSE_BUTTONS":
            return f"For the mouse, {MOUSE_QUESTION}"
        return str(r.get("question") or "")
    if state == "UNRESOLVED":
        return f"{title}: I found no supported cause, so I changed nothing."
    if state == "UNSUPPORTED":
        return f"{title} is not something I can repair. The next step is on screen."
    return describe_issue_result(r)


def describe_issue_result(r: dict[str, Any]) -> str:
    """Deterministic plain-language rendering of a server issue result (used by the rules strategy and as the
    fallback when a model produces no usable text). Short and spoken; the cards on screen hold the full text."""
    if "error" in r:
        return f"I couldn't do that: {r['error'].get('message', 'request rejected')}."
    state = r.get("state")
    if state == "PROPOSED":
        change = _first_sentence(_proposal_text(r)) or "a change"
        return f"{headline(r)} I can fix it: {change} Tap Approve if that's right."
    if state == "NEEDS_CLARIFICATION":
        if r.get("kind") == "MOUSE_BUTTONS":
            return f"{headline(r)} {MOUSE_QUESTION[0].upper()}{MOUSE_QUESTION[1:]}"
        facts = r.get("observed_facts") or []
        return f"{facts[0] if facts else ''} {r.get('question') or ''}".strip()
    if state == "UNRESOLVED":
        facts = r.get("observed_facts") or []
        return str(r.get("next_manual_step") or (facts[0] if facts else "Nothing was changed."))
    if state == "UNSUPPORTED":
        return r.get("next_manual_step") or "That isn't something I can repair."
    if state == "RESOLVED":
        return "Thanks, I've marked that as resolved because you confirmed it."
    if state == "AWAITING_USER_CONFIRMATION":
        conf = r.get("confirmation") or {}
        return conf.get("question") or "Please check it and tell me if it works."
    if r.get("note"):
        return r["note"]
    return f"Status: {str(state).replace('_', ' ').lower()}."


def pending_question(status: dict[str, Any]) -> str | None:
    """The one question the person is currently being asked (context for interpreting a short answer)."""
    for i in status.get("issues", []):
        if i.get("state") == "NEEDS_CLARIFICATION" and i.get("question"):
            return str(i["question"])
    for i in status.get("issues", []):
        if i.get("state") == "AWAITING_USER_CONFIRMATION":
            return str((i.get("confirmation") or {}).get("question") or "Does it work now?")
    return None


class Agent:
    """Provider kinds:
    - "rules": keyword interpreter (no language model) + deterministic orchestration over MCP.
    - "ollama": local LLM interprets the utterance into closed fields (one schema-constrained call) +
      the same deterministic orchestration over MCP.
    - "ollama-tools": EXPERIMENTAL free tool-calling loop by the local LLM (measured unreliable on 3B models).
    """

    def __init__(self, *, provider_kind: str, ollama: OllamaProvider | None, max_turns: int, max_tool_calls: int,
                 timeout_s: float, interpreter: Any = None) -> None:
        self.provider_kind = provider_kind
        self.ollama = ollama
        self.interpreter = interpreter
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls
        self.timeout_s = timeout_s

    async def run(self, mcp: McpToolClient, utterance_id: str, text: str,
                  history: list[dict[str, str]]) -> AgentResult:
        if self.provider_kind == "ollama-tools" and self.ollama is not None:
            res = await self._run_llm(mcp, utterance_id, text, history)
        elif self.provider_kind == "ollama":
            if self.interpreter is None:
                raise RuntimeError("ollama provider configured without an interpreter")
            res = await self._run_structured(mcp, utterance_id, text, self.interpreter)
        else:
            res = await self._run_structured(mcp, utterance_id, text, None)
        res.protocol_version = mcp.protocol_version
        status, _ = await mcp.call("get_recovery_status", {})
        res.text, res.blocked_claims = guard_claims(res.text, status)
        res.trace = list(mcp.calls)
        return res

    # ------------------------------------------------------------------------------- LLM strategy
    async def _run_llm(self, mcp: McpToolClient, utterance_id: str, text: str,
                       history: list[dict[str, str]]) -> AgentResult:
        assert self.ollama is not None
        res = AgentResult(text="", provider="ollama-tools", model=self.ollama.model)
        deadline = time.monotonic() + self.timeout_s
        tools = await mcp.list_tools()
        status, _ = await mcp.call("get_recovery_status", {})
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nCurrent server status (authoritative):\n" + _compact(status, 2500)},
            *history[-6:],
            {"role": "user", "content": f"{text}\n\n[utterance_id: {utterance_id}]"},
        ]
        last_results: list[dict[str, Any]] = []
        while res.model_turns < self.max_turns:
            remaining = deadline - time.monotonic()
            if remaining < 2:
                res.timed_out, res.stop_reason = True, "wall_clock_limit"
                break
            try:
                reply = await self.ollama.chat(messages, tools, timeout_s=remaining)
            except ProviderError as exc:
                res.error = str(exc)
                res.timed_out = "timed out" in str(exc)
                res.stop_reason = "model_timeout" if res.timed_out else "model_error"
                break
            res.model_turns += 1
            res.model_latency_ms.append(reply.latency_ms)
            messages.append({"role": "assistant", "content": reply.content,
                             **({"tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}}
                                                for c in reply.tool_calls]} if reply.tool_calls else {})})
            if not reply.tool_calls:
                res.text = reply.content
                break
            for call in reply.tool_calls:
                if res.tool_calls >= self.max_tool_calls:
                    res.stop_reason = "tool_call_limit"
                    break
                payload, is_error = await mcp.call(call.name, call.arguments)
                res.tool_calls += 1
                last_results.append(payload)
                messages.append({"role": "tool", "tool_name": call.name, "content": _compact(payload)})
            if res.stop_reason == "tool_call_limit":
                break
        else:
            res.stop_reason = "model_turn_limit"
        if not res.text:
            # deterministic fallback from server results: never invent progress
            parts = [describe_issue_result(r) for r in last_results if isinstance(r, dict) and ("state" in r or "error" in r)]
            note = {"wall_clock_limit": "I ran out of time for this request; progress so far is saved.",
                    "model_timeout": "The local model took too long; progress so far is saved.",
                    "model_error": f"The local model is unavailable ({res.error}).",
                    "tool_call_limit": "I reached the step limit for one request; say 'continue' to go on.",
                    "model_turn_limit": "I reached the step limit for one request; say 'continue' to go on."}.get(res.stop_reason, "")
            res.text = " ".join(p for p in [*parts[-2:], note] if p)
        return res

    # ------------------------------------------------------------------------------- structured strategy
    async def _run_structured(self, mcp: McpToolClient, utterance_id: str, text: str, interpreter: Any) -> AgentResult:
        res = AgentResult(text="", provider="ollama" if interpreter else "rules",
                          model=interpreter.model if interpreter else None)
        said: list[str] = []
        results: list[dict[str, Any]] = []
        budget = self.max_tool_calls

        async def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
            nonlocal budget
            if budget <= 0:
                res.stop_reason = "tool_call_limit"
                return {"error": {"message": "step limit reached; say 'continue'"}}
            budget -= 1
            res.tool_calls += 1
            payload, _ = await mcp.call(name, args)
            return payload

        status = await call("get_recovery_status", {})
        if interpreter is None:
            it = interpret(text)
            # An unrecognised problem description is recorded as an explicit UNSUPPORTED issue (tracked and
            # explained) rather than ignored, but only when no question is waiting for an answer.
            if (not it.categories and not (it.yes or it.no or it.stop or it.undo or it.primary_button)
                    and pending_question(status) is None and PROBLEM_RE.search(text)):
                it.categories = ["other"]
        else:
            try:
                it, ms = await interpreter.interpret(text, pending_question(status), timeout_s=self.timeout_s)
            except ProviderError as exc:
                res.error = str(exc)
                res.timed_out = "timed out" in str(exc)
                res.stop_reason = "model_timeout" if res.timed_out else "model_error"
                res.text = ("I couldn't interpret that with the local language model (" + str(exc)[:120] + "). "
                            "Nothing was changed. Please rephrase, use the buttons on screen, or press Stop.")
                return res
            res.model_turns = 1
            res.model_latency_ms.append(ms)
        if it.stop:
            r = await call("stop_recovery", {"reason": "person said stop"})
            res.text = ("Stopped. No further changes will be made." if r.get("stop_state") == "CONFIRMED" else
                        "Stop recorded. I could not reach the laptop helper, so whether it has stopped is unknown.")
            return res
        issues = status.get("issues", [])
        mission = status.get("mission")
        active = mission is not None and mission.get("state") == "ACTIVE"
        open_issues = [i for i in issues if i["state"] not in ("RESOLVED", "UNSUPPORTED")] if active else []

        awaiting = [i for i in open_issues if i["state"] == "AWAITING_USER_CONFIRMATION"]
        # Mentioning only the symptom being confirmed ("...but I still can't hear anything") is an answer about
        # it, not a new report.
        about_awaited = not set(it.categories) - {i.get("category") for i in awaiting}
        if awaiting and (it.yes or it.no or it.uncertain) and about_awaited:
            target = awaiting[-1]
            answered: dict[str, Any] = {}
            if it.yes or it.no:
                answered = await call("record_user_result", {"issue_id": target["issue_id"],
                                                             "result": "works" if it.yes else "still_broken",
                                                             "utterance_id": utterance_id})
            if it.uncertain or (answered.get("error") or {}).get("code") == "AMBIGUOUS":
                # Not a clear answer: keep it as evidence ("unsure", citing the utterance), keep waiting, ask again.
                await call("record_user_result", {"issue_id": target["issue_id"], "result": "unsure",
                                                  "utterance_id": utterance_id})
                said.append(UNSURE_REPLY)
            else:
                results.append(answered)

        for issue in [i for i in open_issues if i["state"] == "NEEDS_CLARIFICATION"]:
            args: dict[str, Any] = {"issue_id": issue["issue_id"]}
            if issue["kind"] == "MOUSE_BUTTONS" and it.primary_button:
                args["primary_button"] = it.primary_button
            elif issue["kind"] == "OFFSCREEN_WINDOW":
                low = text.lower()
                match = [o for o in issue.get("options") or [] if any(
                    w in low for w in re.findall(r"[a-z]{3,}", o["label"].lower()) if w not in {"rescuebridge", "demo"})]
                if len(match) == 1:
                    args["target_ref"] = match[0]["value"]
            elif issue["kind"] == "AUDIO_OUTPUT" and it.volume_percent:
                args["volume_percent"] = max(5, min(50, it.volume_percent))
            if len(args) > 1:
                r = await call("propose_recovery", args)
                results.append(r)

        existing = {i["category"] for i in open_issues}
        new_cats = [c for c in it.categories if c not in existing]
        # the person reports an already-known symptom again: take FRESH observations (supported next check)
        for issue in open_issues:
            if issue["category"] in it.categories and issue["state"] in ("REPORTED", "UNRESOLVED", "FAILED"):
                r = await call("inspect_recovery", {"issue_id": issue["issue_id"]})
                results.append(r)
        if new_cats:
            symptoms = [{"category": c, "user_words": text[:200], **({"app_hint": it.app_hint} if c == "window_missing"
                                                                      and it.app_hint else {})} for c in new_cats]
            started = await call("start_recovery", {"goal": text[:300], "symptoms": symptoms})
            for iid in started.get("created_issue_ids", []):
                issue = next((i for i in started.get("issues", []) if i["issue_id"] == iid), None)
                if issue and issue["state"] == "UNSUPPORTED":
                    results.append(issue)
                    continue
                r = await call("inspect_recovery", {"issue_id": iid})
                results.append(r)

        if it.undo:
            ops = [o for i in issues for o in i.get("operations", []) if o.get("undo_available")]
            if ops:
                r = await call("undo_recovery", {"operation_id": ops[-1]["operation_id"]})
                said.append(r["reason"] if r.get("blocked") else
                            ("I've prepared an undo: " + r.get("proposal", {}).get("description", "") +
                             " Tap Approve on your phone to run it.") if "proposal" in r else describe_issue_result(r))
            else:
                said.append("There is no completed repair that can be undone.")

        if it.ambiguous_answer and not results:
            said.append("I wasn't sure what you meant, so I didn't record an answer. Please use the buttons on screen.")
        if len(results) == 1:
            said.append(describe_issue_result(results[0]))
        elif results:
            said.append("I checked your laptop.")
            question = None
            for r in results:
                line = short_issue_line(r)
                if r.get("state") == "NEEDS_CLARIFICATION":
                    question = question or line
                    continue
                said.append(line)
            if any(r.get("state") == "PROPOSED" for r in results):
                said.append("Review each fix below and tap Approve.")
            if question:
                said.append(question)
        if not said:
            if not it.categories and not (it.yes or it.no):
                said.append("I can help with three things: mouse buttons that click wrong, no sound from the default "
                            "speaker, or an app window that went off-screen. Tell me what's happening.")
            elif open_issues:
                said.append(describe_issue_result(open_issues[0]))
        # one focused question at a time: keep at most one question in the reply
        out, asked = [], False
        for s in said:
            if "?" in s:
                if asked:
                    continue
                asked = True
            out.append(s)
        res.text = " ".join(out)
        return res
