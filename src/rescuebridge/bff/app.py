"""Backend-for-frontend (BFF): authenticates browser sessions and acts as a real MCP client.

Routes that reach recovery tools go through `McpToolClient` (Streamable HTTP to the MCP server). Approve,
Decline, Stop, Continue and the person's Yes/No results are direct authenticated UI paths, but they call the
SAME RecoveryService methods the MCP tools call. Nothing here re-implements authority logic.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import segno
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from rescuebridge.agent.loop import Agent, AgentResult, describe_issue_result
from rescuebridge.agent.mcp_client import McpToolClient
from rescuebridge.agent.providers import OllamaProvider
from rescuebridge.auth import AuthError, AuthService, SessionInfo
from rescuebridge.config import Settings, host_name
from rescuebridge.context import AppContext
from rescuebridge.domain.enums import UserResultSource
from rescuebridge.domain.service import DomainError, Principal
from rescuebridge.ids import new_id, now_ms
from rescuebridge.lab.arming import read_arming

log = logging.getLogger("rescuebridge.bff")

SESSION_COOKIE = "rb_session"
PAIR_COOKIE = "rb_pair"
WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"

SECURITY_HEADERS = [
    (b"content-security-policy", b"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                                 b"connect-src 'self'; media-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                                 b"form-action 'self'"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"permissions-policy", b"microphone=(self), camera=(), geolocation=()"),
    (b"cache-control", b"no-store"),
]


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + SECURITY_HEADERS
            await send(message)

        await self.app(scope, receive, send_wrapper)


@dataclass
class BffState:
    ctx: AppContext
    auth: AuthService
    agent: Agent
    mcp_url: str
    allowed_origins: set[str]
    allowed_hosts: set[str]
    lan_url: str | None = None
    device_locks: dict[str, anyio.Lock] = field(default_factory=dict)
    busy_since: dict[str, int] = field(default_factory=dict)
    pairing_code: dict[str, Any] | None = None


def _err(code: str, message: str, status: int = 400, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, **extra}}, status_code=status)


def _set_cookie(resp: Response, request: Request, name: str, value: str, *, max_age: int, path: str = "/") -> None:
    resp.set_cookie(name, value, max_age=max_age, path=path, httponly=True, samesite="strict",
                    secure=request.url.scheme == "https")


def build_bff_app(ctx: AppContext, auth: AuthService, *, lan_url: str | None = None) -> Starlette:
    s: Settings = ctx.settings
    from rescuebridge.agent.llm_interpret import OllamaInterpreter

    ollama = OllamaProvider(s.ollama_url, s.ollama_model) if s.model_provider == "ollama-tools" else None
    interpreter = OllamaInterpreter(s.ollama_url, s.ollama_model) if s.model_provider == "ollama" else None
    llm = ollama or interpreter
    agent = Agent(provider_kind=s.model_provider, ollama=ollama, interpreter=interpreter,
                  max_turns=s.agent_max_model_turns, max_tool_calls=s.agent_max_tool_calls, timeout_s=s.agent_timeout_s)
    origins = {f"http://127.0.0.1:{s.bff_port}", f"http://localhost:{s.bff_port}"}
    hosts = {f"127.0.0.1:{s.bff_port}", f"localhost:{s.bff_port}"}
    if lan_url:
        origins.add(lan_url.rstrip("/"))
        hosts.add(lan_url.split("://", 1)[1].rstrip("/"))
    st = BffState(ctx=ctx, auth=auth, agent=agent, mcp_url=f"http://127.0.0.1:{s.mcp_port}/mcp",
                  allowed_origins=origins, allowed_hosts=hosts, lan_url=lan_url)

    # ------------------------------------------------------------------ request guards
    def check_host(request: Request) -> JSONResponse | None:
        if request.headers.get("host", "") not in st.allowed_hosts:
            return _err("BAD_HOST", "Host not allowed", 421)
        return None

    def check_origin(request: Request) -> JSONResponse | None:
        if request.method in ("GET", "HEAD"):
            return None
        origin = request.headers.get("origin")
        if origin not in st.allowed_origins:
            return _err("BAD_ORIGIN", "Cross-origin request rejected", 403)
        return None

    def session_of(request: Request) -> SessionInfo | None:
        return auth.session(request.cookies.get(SESSION_COOKIE))

    def require(request: Request, role: str) -> tuple[SessionInfo | None, JSONResponse | None]:
        if (bad := check_host(request)) or (bad := check_origin(request)):
            return None, bad
        sess = session_of(request)
        if sess is None:
            return None, _err("UNAUTHENTICATED", "Not paired or session expired", 401)
        if sess.role != role:
            return None, _err("FORBIDDEN", "Wrong session type", 403)
        if request.method not in ("GET", "HEAD") and request.headers.get("x-rb-csrf") != sess.csrf_token:
            return None, _err("CSRF", "Missing or wrong CSRF token", 403)
        return sess, None

    def ui_principal(sess: SessionInfo) -> Principal:
        assert sess.device_id
        return Principal(sess.device_id, sess.session_id, "ui")

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def store_message(device_id: str, role: str, text: str, input_mode: str | None = None,
                      meta: dict[str, Any] | None = None) -> dict[str, Any]:
        m = ctx.service._mission(Principal(device_id, None, "ui"))
        row = {"id": new_id("msg"), "mission_id": m["id"] if m else None, "device_id": device_id, "role": role,
               "text": text[:2000], "input_mode": input_mode, "created_at": now_ms(), "meta": meta}
        ctx.store.insert("messages", row)
        return row

    def lock_for(device_id: str) -> anyio.Lock:
        return st.device_locks.setdefault(device_id, anyio.Lock())

    async def with_mcp(sess: SessionInfo) -> McpToolClient:
        token = auth.mint_mcp_token(sess)
        return McpToolClient(st.mcp_url, token)

    def state_payload(sess: SessionInfo) -> dict[str, Any]:
        principal = ui_principal(sess)
        status = ctx.service.status(principal)
        msgs = ctx.store.all("SELECT id, role, text, input_mode, created_at, meta FROM messages WHERE device_id = ? "
                             "ORDER BY created_at DESC LIMIT 30", (sess.device_id,))
        return {"status": status, "messages": list(reversed(msgs)), "busy_since": st.busy_since.get(sess.device_id or ""),
                "helper": ctx.service.last_helper_health, "server_time": now_ms()}

    # ------------------------------------------------------------------ public
    async def index(request: Request) -> Response:
        if bad := check_host(request):
            return bad
        f = WEB_DIST / "index.html"
        if not f.exists():
            return Response("Web app not built. Run scripts\\setup.ps1 (npm run build in web/).", media_type="text/plain",
                            status_code=503)
        return FileResponse(f)

    async def health(request: Request) -> Response:
        if bad := check_host(request):
            return bad
        return JSONResponse({"ok": True, "host_name": host_name(), "time": now_ms()})

    async def pair_request(request: Request) -> Response:
        if (bad := check_host(request)) or (bad := check_origin(request)):
            return bad
        b = await body(request)
        try:
            out = auth.request_pairing(str(b.get("code", ""))[:20], str(b.get("device_name", "Phone"))[:60],
                                       request.headers.get("user-agent"))
        except AuthError as exc:
            return _err(exc.code, exc.message, exc.status)
        resp = JSONResponse({"status": "PENDING", "expires_at": out["expires_at"],
                             "message": "Now accept this phone on the laptop's RescueBridge host console."})
        _set_cookie(resp, request, PAIR_COOKIE, out["request_secret"], max_age=300, path="/api/pair")
        return resp

    async def pair_claim(request: Request) -> Response:
        if (bad := check_host(request)) or (bad := check_origin(request)):
            return bad
        try:
            out, token = auth.claim(request.cookies.get(PAIR_COOKIE, ""))
        except AuthError as exc:
            resp = _err(exc.code, exc.message, exc.status)
            resp.delete_cookie(PAIR_COOKIE, path="/api/pair")
            return resp
        resp = JSONResponse(out)
        if token:
            _set_cookie(resp, request, SESSION_COOKIE, token, max_age=s.session_ttl_s)
            resp.delete_cookie(PAIR_COOKIE, path="/api/pair")
        return resp

    async def host_bootstrap(request: Request) -> Response:
        if (bad := check_host(request)) or (bad := check_origin(request)):
            return bad
        if request.url.scheme == "https" or (request.client and request.client.host not in ("127.0.0.1", "::1")):
            return _err("LOCAL_ONLY", "The host console is only available on the laptop itself", 403)
        b = await body(request)
        try:
            token = auth.consume_host_bootstrap(str(b.get("code", ""))[:100])
        except AuthError as exc:
            return _err(exc.code, exc.message, exc.status)
        resp = JSONResponse({"ok": True})
        _set_cookie(resp, request, SESSION_COOKIE, token, max_age=s.session_ttl_s)
        return resp

    # ------------------------------------------------------------------ device session
    async def session_info(request: Request) -> Response:
        if (bad := check_host(request)):
            return bad
        sess = session_of(request)
        if sess is None:
            return JSONResponse({"paired": False, "host_name": host_name()})
        return JSONResponse({
            "paired": True, "role": sess.role, "device_name": sess.device_name, "csrf_token": sess.csrf_token,
            "host_name": host_name(), "model_provider": s.model_provider,
            "model": s.ollama_model if llm else "keyword interpreter (no language model)",
            "model_data_destination": llm.data_destination if llm else "none (runs inside the RescueBridge backend)",
            "host_adapter": s.host_adapter, "agent_limits": {"model_turns": s.agent_max_model_turns,
                                                             "tool_calls": s.agent_max_tool_calls,
                                                             "timeout_s": s.agent_timeout_s},
            "lan_url": st.lan_url, "secure_context_hint": request.url.scheme == "https" or request.url.hostname in ("127.0.0.1", "localhost"),
        })

    async def refresh_helper_health() -> None:
        """Cheap liveness probe (at most every 10 s) so connection status is observed, not assumed."""
        last = ctx.service.last_helper_health.get("checked_at") or 0
        if now_ms() - last < 10_000:
            return
        try:
            h = await ctx.host_client.health(timeout_s=1.5)
            ctx.service.last_helper_health = {"reachable": bool(h.get("ok")), "checked_at": now_ms(),
                                              "mode": h.get("mode")}
        except Exception as exc:  # noqa: BLE001 - unreachable is a reportable state
            ctx.service.last_helper_health = {"reachable": False, "checked_at": now_ms(), "error": str(exc)[:200]}

    async def state(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess
        await refresh_helper_health()
        return JSONResponse(state_payload(sess))

    async def utterance(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess and sess.device_id
        b = await body(request)
        text = str(b.get("text", "")).strip()[:500]
        mode = b.get("input_mode") if b.get("input_mode") in ("voice", "text") else "text"
        if not text:
            return _err("EMPTY", "Say or type what is happening.")
        lock = lock_for(sess.device_id)
        if lock.locked():
            return _err("BUSY", "Still working on the previous request.", 409)
        async with lock:
            st.busy_since[sess.device_id] = now_ms()
            msg = store_message(sess.device_id, "user", text, mode)
            run_id = new_id("run")
            t0 = time.perf_counter()
            result: AgentResult
            try:
                async with await with_mcp(sess) as mcp:
                    history = [{"role": m["role"], "content": m["text"]} for m in ctx.store.all(
                        "SELECT role, text FROM messages WHERE device_id = ? AND id != ? AND role IN ('user','assistant') "
                        "ORDER BY created_at DESC LIMIT 6", (sess.device_id, msg["id"]))][::-1]
                    result = await st.agent.run(mcp, msg["id"], text, history)
            except Exception as exc:  # noqa: BLE001 - surfaced to the person, never hidden
                log.exception("agent run failed")
                result = AgentResult(text="Something went wrong talking to the recovery tools. Nothing new was changed. "
                                     "You can try again or use Stop.", provider=s.model_provider, model=None,
                                     stop_reason="error", error=f"{type(exc).__name__}: {str(exc)[:200]}")
            finally:
                st.busy_since.pop(sess.device_id, None)
            total_ms = round((time.perf_counter() - t0) * 1000)
            ctx.store.insert("agent_runs", {"id": run_id, "device_id": sess.device_id, "mission_id": msg["mission_id"],
                                            "utterance_id": msg["id"], "provider": result.provider, "model": result.model,
                                            "started_at": msg["created_at"], "finished_at": now_ms(),
                                            "model_turns": result.model_turns, "tool_calls": result.tool_calls,
                                            "timed_out": int(result.timed_out), "blocked_claims": len(result.blocked_claims),
                                            "latency": {"total_ms": total_ms, "model_ms": result.model_latency_ms,
                                                        "trace": result.trace, "stop_reason": result.stop_reason,
                                                        "protocol_version": result.protocol_version,
                                                        "blocked": result.blocked_claims},
                                            "error": result.error})
            reply = store_message(sess.device_id, "assistant", result.text or "(no reply)", None,
                                  {"run_id": run_id, "stop_reason": result.stop_reason, "total_ms": total_ms})
        return JSONResponse({"reply": reply, "run": {"id": run_id, "total_ms": total_ms, "stop_reason": result.stop_reason,
                                                     "timed_out": result.timed_out, "tool_calls": result.tool_calls,
                                                     "model_turns": result.model_turns,
                                                     "blocked_claims": len(result.blocked_claims)},
                             **state_payload(sess)})

    async def approve(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess and sess.device_id
        pid = request.path_params["proposal_id"]
        b = await body(request)
        principal = ui_principal(sess)
        try:
            ctx.service.approve(principal, pid, str(b.get("digest", "")))
        except DomainError as exc:
            return _err(exc.code, exc.message, 409)
        proposal = ctx.store.get("proposals", pid)
        assert proposal
        store_message(sess.device_id, "system", f"You approved: {proposal['description']}", "button")
        # Execute through the real MCP path (same authority checks as a model-initiated call).
        lines: list[str] = []
        async with lock_for(sess.device_id), await with_mcp(sess) as mcp:
            applied, is_err = await mcp.call("apply_recovery", {"proposal_id": pid})
            if is_err:
                lines.append(describe_issue_result(applied))
            else:
                op = applied.get("operation", {})
                outcome = op.get("outcome")
                if proposal["kind"] == "TEST" and outcome == "APPLIED_STATE_NOT_VERIFIED":
                    lines.append("The test tone was played (the playback call returned). Only you can tell whether "
                                 "it was audible.")
                    outcome = "_handled"
                lines.append({
                    "APPLIED_STATE_VERIFIED": f"Done, and observed: {op.get('observed_after')}.",
                    "APPLIED_STATE_NOT_VERIFIED": "The change was sent but " + (applied.get("note") or "could not be confirmed."),
                    "NO_CHANGE_NEEDED": "No change was needed: the requested state was already present.",
                    "REJECTED_OR_EXPIRED": "Nothing was changed: " + str(applied.get("rejected_because") or op.get("error") or ""),
                    "FAILED": "Windows reported a failure; nothing is confirmed changed.",
                    "OUTCOME_UNKNOWN": str(applied.get("note") or "The outcome is unknown."),
                    "NOT_ATTEMPTED": "The change was not attempted: " + str(applied.get("note") or ""),
                    "_handled": "",
                }.get(str(outcome), f"Outcome: {outcome}"))
                if proposal["kind"] == "TEST":
                    lines.append("Did you hear the tone?")
                elif applied.get("revised"):
                    lines.append(describe_issue_result(applied["revised"]))
                if proposal["kind"] == "REPAIR" and outcome in ("APPLIED_STATE_VERIFIED", "APPLIED_STATE_NOT_VERIFIED",
                                                               "NO_CHANGE_NEEDED", "OUTCOME_UNKNOWN"):
                    issue = ctx.store.get("issues", proposal["issue_id"])
                    if issue and issue["state"] == "VERIFYING":
                        verified, _ = await mcp.call("verify_recovery", {"issue_id": proposal["issue_id"]})
                        lines.append(describe_issue_result(verified))
        reply = store_message(sess.device_id, "assistant", " ".join(x for x in lines if x), None, {"after_approval": pid})
        return JSONResponse({"reply": reply, **state_payload(sess)})

    async def answer(request: Request) -> Response:
        """A tapped clarification option. Routed through MCP propose_recovery like a spoken answer."""
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess and sess.device_id
        b = await body(request)
        field_name, value = b.get("field"), b.get("value")
        if field_name not in ("primary_button", "target_ref", "volume_percent"):
            return _err("BAD_FIELD", "unknown answer field")
        args: dict[str, Any] = {"issue_id": request.path_params["issue_id"], field_name: value}
        store_message(sess.device_id, "user", f"(tapped) {b.get('label') or value}"[:200], "button")
        async with lock_for(sess.device_id), await with_mcp(sess) as mcp:
            r, _ = await mcp.call("propose_recovery", args)
        reply = store_message(sess.device_id, "assistant", describe_issue_result(r))
        return JSONResponse({"reply": reply, **state_payload(sess)})

    async def decline(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess and sess.device_id
        try:
            ctx.service.decline(ui_principal(sess), request.path_params["proposal_id"])
        except DomainError as exc:
            return _err(exc.code, exc.message, 409)
        reply = store_message(sess.device_id, "assistant", "Okay, I won't make that change. Nothing was modified.")
        return JSONResponse({"reply": reply, **state_payload(sess)})

    async def user_result(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess and sess.device_id
        b = await body(request)
        try:
            r = ctx.service.record_user_result(ui_principal(sess), request.path_params["issue_id"], str(b.get("result", "")),
                                               source=UserResultSource.UI_BUTTON)
        except DomainError as exc:
            return _err(exc.code, exc.message, 409)
        reply = store_message(sess.device_id, "assistant", describe_issue_result(r))
        return JSONResponse({"reply": reply, **state_payload(sess)})

    async def stop(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess and sess.device_id
        # Direct path: never waits for a model turn or for a running agent request.
        res = await ctx.service.stop(ui_principal(sess), "person pressed Stop")
        text = ("Stopped. The laptop helper confirmed it will reject any further changes." if res["stop_state"] == "CONFIRMED"
                else "Stop recorded here, but the laptop helper could not be reached, so whether it has stopped is unknown.")
        if res["already_completed_operations"]:
            text += " Changes that already finished stay in place; you can Undo them separately where offered."
        reply = store_message(sess.device_id, "system", text, "button", {"stop": res})
        return JSONResponse({"stop": res, "reply": reply, **state_payload(sess)})

    async def cont(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess and sess.device_id
        try:
            ctx.service.continue_mission(ui_principal(sess))
        except DomainError as exc:
            return _err(exc.code, exc.message, 409)
        reply = store_message(sess.device_id, "assistant", "Continuing. Everything will be inspected again before any change.")
        return JSONResponse({"reply": reply, **state_payload(sess)})

    async def undo(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess and sess.device_id
        async with lock_for(sess.device_id), await with_mcp(sess) as mcp:
            r, is_err = await mcp.call("undo_recovery", {"operation_id": request.path_params["operation_id"]})
        if is_err:
            text = describe_issue_result(r)
        elif r.get("blocked"):
            text = r["reason"]
        else:
            text = "Undo prepared: " + r["proposal"]["description"] + " Tap Approve to run it."
        reply = store_message(sess.device_id, "assistant", text)
        return JSONResponse({"reply": reply, **state_payload(sess)})

    async def diagnostics(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess
        runs = ctx.store.all("SELECT * FROM agent_runs WHERE device_id = ? ORDER BY started_at DESC LIMIT 10", (sess.device_id,))
        m = ctx.service._mission(ui_principal(sess), active_only=False)
        obs = ctx.store.all("SELECT id, kind, adapter_mode, status, observed_at, expires_at, model_facts, error FROM observations "
                            "WHERE mission_id = ? ORDER BY observed_at DESC LIMIT 20", (m["id"] if m else "",))
        return JSONResponse({"agent_runs": runs, "observations": obs, "settings": {
            "model_provider": s.model_provider, "ollama_model": s.ollama_model if llm else None,
            "host_adapter": s.host_adapter, "mcp_url": st.mcp_url}})

    async def handoff(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess
        status = ctx.service.status(ui_principal(sess))
        lines = ["RescueBridge recovery summary (for a helper)", f"Laptop: {host_name()}  Adapter: {status['adapter']}"]
        if status.get("mission"):
            lines.append(f"Server summary: {status['mission']['server_summary']}")
        for i in status["issues"]:
            lines.append(f"- {i['category']}: {i['state']}")
            lines += [f"    observed: {f}" for f in i["observed_facts"][:3]]
            lines += [f"    operation: {o['action']} -> {o['outcome']} (before: {o['observed_before']}; after: "
                      f"{o['observed_after']})" for o in i["operations"]]
            lines += [f"    person said: {r['result']} ({r['source']})" for r in i["person_results"]]
            if i.get("next_manual_step"):
                lines.append(f"    next manual step: {i['next_manual_step']}")
        return JSONResponse({"text": "\n".join(lines)})

    async def logout(request: Request) -> Response:
        sess, bad = require(request, "device")
        if bad:
            return bad
        assert sess
        auth.logout(sess.session_id)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # ------------------------------------------------------------------ host console
    async def host_state(request: Request) -> Response:
        sess, bad = require(request, "host_console")
        if bad:
            return bad
        try:
            h = await ctx.host_client.health(timeout_s=2.0)
            helper = {"reachable": True, **h.get("result", {})}
        except Exception as exc:  # noqa: BLE001
            helper = {"reachable": False, "error": str(exc)[:200]}
        code = st.pairing_code if st.pairing_code and st.pairing_code["expires_at"] > now_ms() else None
        if code:
            row = ctx.store.get("pairing_codes", code["code_id"])
            if not row or row["used_at"]:
                code = None  # one-use: never show a code that has been consumed or burned
        if code:
            code = {k: v for k, v in code.items() if k != "code_id"}
        arming = read_arming(s)
        missions = ctx.store.all("SELECT m.id, m.state, m.stop_state, m.created_at, d.name AS device_name FROM missions m "
                                 "LEFT JOIN devices d ON d.id = m.device_id ORDER BY m.created_at DESC LIMIT 5")
        return JSONResponse({"host_name": host_name(), "helper": helper, "pairing": code, "lan_url": st.lan_url,
                             "pending_requests": auth.pending_requests(), "devices": auth.devices(),
                             "lab": arming, "missions": missions, "revision": ctx.service.revision(),
                             "model_provider": s.model_provider, "host_adapter": s.host_adapter})

    async def host_new_code(request: Request) -> Response:
        sess, bad = require(request, "host_console")
        if bad:
            return bad
        code = auth.create_pairing_code()
        base = st.lan_url or f"http://127.0.0.1:{s.bff_port}"
        pair_url = f"{base}/#pair={code['code']}"  # fragment: never sent to the server or logged
        qr = segno.make(pair_url, error="m").svg_data_uri(scale=5, dark="#000", light="#fff")
        st.pairing_code = {"code": code["code"], "expires_at": code["expires_at"], "qr_data_uri": qr, "url": base,
                           "code_id": code["code_id"]}
        return JSONResponse({"pairing": {k: v for k, v in st.pairing_code.items() if k != "code_id"}})

    async def host_decide(request: Request) -> Response:
        sess, bad = require(request, "host_console")
        if bad:
            return bad
        decision = request.path_params["decision"]
        if decision not in ("accept", "reject"):
            return _err("BAD_DECISION", "decision must be accept or reject", 404)
        try:
            out = auth.decide(request.path_params["request_id"], decision == "accept")
        except AuthError as exc:
            return _err(exc.code, exc.message, exc.status)
        if out.get("accepted"):
            st.pairing_code = None
        return JSONResponse(out)

    async def host_revoke(request: Request) -> Response:
        sess, bad = require(request, "host_console")
        if bad:
            return bad
        try:
            auth.revoke_device(request.path_params["device_id"])
        except AuthError as exc:
            return _err(exc.code, exc.message, exc.status)
        fence = await ctx.service.bump_revision("paired device revoked")
        return JSONResponse({"revoked": True, **fence})

    async def host_stop(request: Request) -> Response:
        sess, bad = require(request, "host_console")
        if bad:
            return bad
        res = await ctx.service.stop(Principal("host-console", sess.session_id if sess else None, "host_console"),
                                     "Stop pressed on the laptop host console")
        return JSONResponse({"stop": res})

    routes = [
        Route("/", index), Route("/host", index),
        Route("/api/health", health),
        Route("/api/session", session_info),
        Route("/api/pair/request", pair_request, methods=["POST"]),
        Route("/api/pair/claim", pair_claim, methods=["POST"]),
        Route("/api/host/bootstrap", host_bootstrap, methods=["POST"]),
        Route("/api/state", state),
        Route("/api/utterance", utterance, methods=["POST"]),
        Route("/api/proposals/{proposal_id}/approve", approve, methods=["POST"]),
        Route("/api/proposals/{proposal_id}/decline", decline, methods=["POST"]),
        Route("/api/issues/{issue_id}/answer", answer, methods=["POST"]),
        Route("/api/issues/{issue_id}/result", user_result, methods=["POST"]),
        Route("/api/stop", stop, methods=["POST"]),
        Route("/api/continue", cont, methods=["POST"]),
        Route("/api/operations/{operation_id}/undo", undo, methods=["POST"]),
        Route("/api/diagnostics", diagnostics),
        Route("/api/handoff", handoff),
        Route("/api/logout", logout, methods=["POST"]),
        Route("/api/host/state", host_state),
        Route("/api/host/pairing-code", host_new_code, methods=["POST"]),
        Route("/api/host/requests/{request_id}/{decision:str}", host_decide, methods=["POST"]),
        Route("/api/host/devices/{device_id}/revoke", host_revoke, methods=["POST"]),
        Route("/api/host/stop", host_stop, methods=["POST"]),
    ]
    if (WEB_DIST / "assets").exists():
        routes.append(Mount("/assets", app=StaticFiles(directory=WEB_DIST / "assets"), name="assets"))
    app = Starlette(routes=routes, middleware=[Middleware(SecurityHeaders)])
    app.state.bff = st
    return app
