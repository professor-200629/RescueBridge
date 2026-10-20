"""RescueBridge MCP server (Streamable HTTP, loopback only, bearer-token bound to a paired device).

Tools are goal-oriented and map 1:1 onto RecoveryService methods. Arguments are validated with strict
pydantic models: unknown tools, unknown properties, malformed identifiers, out-of-range or non-finite
numbers are rejected. There is no approve tool: approval exists only on the paired device's UI.

The MCP transport session ID is transport state only. Every request is authorized by its own bearer token,
which maps to (device, browser session); tools never accept a device or mission identifier as input.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import mcp.types as types
from mcp.server import Server
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

from rescuebridge.auth import AuthService
from rescuebridge.domain.enums import UserResultSource
from rescuebridge.domain.service import DomainError, Principal, RecoveryService

log = logging.getLogger("rescuebridge.mcp")

SERVER_INSTRUCTIONS = """RescueBridge recovers access to an existing Windows session through a second channel.
Supported: (A) mouse button mapping vs the person's preference, (B) muted/silent default playback device,
(C) an app window that is off-screen. Everything else is unsupported: say so, change nothing.
Rules: cite only server-returned observations; never claim something is fixed unless an issue's state is
RESOLVED (that requires the person's own confirmation); you cannot approve anything - the person approves
the exact proposal on their paired phone; ask one focused question at a time."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


IssueId = Annotated[str, Field(pattern=r"^iss_[A-Za-z0-9]{6,20}$")]
ProposalId = Annotated[str, Field(pattern=r"^prop_[A-Za-z0-9]{6,20}$")]
OperationId = Annotated[str, Field(pattern=r"^op_[A-Za-z0-9]{6,20}$")]
ObservationId = Annotated[str, Field(pattern=r"^obs_[A-Za-z0-9]{6,20}$")]
MessageId = Annotated[str, Field(pattern=r"^msg_[A-Za-z0-9]{6,20}$")]


class Symptom(_Strict):
    category: Literal["mouse_buttons_wrong", "no_sound", "window_missing", "mouse_not_moving", "other"]
    user_words: Annotated[str, Field(max_length=200)] = ""
    app_hint: Annotated[str, Field(max_length=40)] | None = None


class StartArgs(_Strict):
    goal: Annotated[str, Field(max_length=300)] = ""
    symptoms: Annotated[list[Symptom], Field(min_length=1, max_length=5)]


class IssueArgs(_Strict):
    issue_id: IssueId


class ProposeArgs(_Strict):
    issue_id: IssueId
    primary_button: Literal["left", "right"] | None = None
    target_ref: Annotated[str, Field(pattern=r"^wt_[0-9a-f]{16}$")] | None = None
    volume_percent: Annotated[int, Field(ge=5, le=50)] | None = None
    basis_observation_ids: Annotated[list[ObservationId], Field(max_length=8)] | None = None


class ProposalArgs(_Strict):
    proposal_id: ProposalId


class UserResultArgs(_Strict):
    issue_id: IssueId
    result: Literal["works", "still_broken", "unsure"]
    utterance_id: MessageId


class StopArgs(_Strict):
    reason: Annotated[str, Field(max_length=200)] = ""


class UndoArgs(_Strict):
    operation_id: OperationId


class NoArgs(_Strict):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    model: type[_Strict]
    handler: Callable[[RecoveryService, Principal, Any], Awaitable[dict[str, Any]]]
    read_only: bool = False
    destructive: bool = False


async def _start(svc: RecoveryService, p: Principal, a: StartArgs) -> dict[str, Any]:
    return svc.start_recovery(p, a.goal, [s.model_dump() for s in a.symptoms])


async def _inspect(svc: RecoveryService, p: Principal, a: IssueArgs) -> dict[str, Any]:
    return await svc.inspect(p, a.issue_id)


async def _propose(svc: RecoveryService, p: Principal, a: ProposeArgs) -> dict[str, Any]:
    return await svc.propose(p, a.issue_id, primary_button=a.primary_button, target_ref=a.target_ref,
                             volume_percent=a.volume_percent, basis_observation_ids=a.basis_observation_ids)


async def _apply(svc: RecoveryService, p: Principal, a: ProposalArgs) -> dict[str, Any]:
    return await svc.apply(p, a.proposal_id)


async def _verify(svc: RecoveryService, p: Principal, a: IssueArgs) -> dict[str, Any]:
    return await svc.verify(p, a.issue_id)


async def _user_result(svc: RecoveryService, p: Principal, a: UserResultArgs) -> dict[str, Any]:
    return svc.record_user_result(p, a.issue_id, a.result, source=UserResultSource.MODEL_INTERPRETED_UTTERANCE,
                                  utterance_id=a.utterance_id)


async def _status(svc: RecoveryService, p: Principal, a: NoArgs) -> dict[str, Any]:
    return svc.status(p, for_model=True)


async def _stop(svc: RecoveryService, p: Principal, a: StopArgs) -> dict[str, Any]:
    return await svc.stop(p, a.reason or "stop requested through the assistant")


async def _undo(svc: RecoveryService, p: Principal, a: UndoArgs) -> dict[str, Any]:
    return await svc.request_undo(p, a.operation_id)


TOOLS: dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec("start_recovery", "Start or resume recovery",
             "Create or resume the person's recovery session and record each reported symptom as a separate issue. "
             "Map their words to categories: mouse_buttons_wrong (clicks do the wrong thing), no_sound, "
             "window_missing (an app/notes window disappeared; put the app name in app_hint), mouse_not_moving "
             "(pointer frozen: unsupported hardware), other (anything else: unsupported).",
             StartArgs, _start),
    ToolSpec("inspect_recovery", "Inspect an issue",
             "Take fresh diagnostic observations for one issue. Returns observed facts, a supported explanation if "
             "any, one focused question if needed, or a proposal that the person must approve on their phone.",
             IssueArgs, _inspect, read_only=True),
    ToolSpec("propose_recovery", "Answer a question / revise proposal",
             "Give the person's answer to the focused question and get a fresh exact proposal. primary_button: the "
             "physical button the person wants for normal clicks (left = usual right-handed). target_ref: which "
             "window (from the options). volume_percent: test volume 5-50.",
             ProposeArgs, _propose),
    ToolSpec("apply_recovery", "Apply an approved proposal",
             "Execute a proposal ONLY after the person approved it on the paired phone. Fails if not approved, "
             "expired, revoked or if the observed state changed. Never executes twice.",
             ProposalArgs, _apply, destructive=True),
    ToolSpec("verify_recovery", "Verify an issue",
             "Take fresh observations after a change and set up the person's functional check (test tone, test "
             "click, or 'can you see the window').",
             IssueArgs, _verify, read_only=True),
    ToolSpec("record_user_result", "Record the person's confirmation",
             "Record whether the person says the symptom is fixed, citing the id of their own message. Only valid "
             "while the issue awaits confirmation; contradictory wording is rejected.",
             UserResultArgs, _user_result),
    ToolSpec("get_recovery_status", "Get recovery status",
             "Current server-side status of every issue, open proposals, operations and the person's results.",
             NoArgs, _status, read_only=True),
    ToolSpec("stop_recovery", "Stop",
             "Revoke all pending permission and stop further changes immediately.",
             StopArgs, _stop),
    ToolSpec("undo_recovery", "Request a guarded undo",
             "Prepare a guarded undo of an applied repair (needs approval). Blocked if the setting changed since.",
             UndoArgs, _undo),
]}


def _tool_defs() -> list[types.Tool]:
    out = []
    for t in TOOLS.values():
        schema = t.model.model_json_schema()
        schema.setdefault("properties", {})
        schema["additionalProperties"] = False
        out.append(types.Tool(name=t.name, title=t.title, description=t.description, input_schema=schema,
                              annotations=types.ToolAnnotations(read_only_hint=t.read_only, destructive_hint=t.destructive,
                                                                idempotent_hint=t.name == "apply_recovery",
                                                                open_world_hint=False)))
    return out


def _result(payload: dict[str, Any], is_error: bool = False) -> types.CallToolResult:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], structured_content=payload,
                                is_error=is_error)


def build_mcp_server(service: RecoveryService) -> Server[Any]:
    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=_tool_defs())

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        request = getattr(ctx, "request", None)
        principal = request.scope.get("rb_principal") if request is not None else None
        if not isinstance(principal, Principal):
            return _result({"error": {"code": "UNAUTHENTICATED", "message": "no authenticated device"}}, True)
        spec = TOOLS.get(params.name)
        if spec is None:
            return _result({"error": {"code": "UNKNOWN_TOOL", "message": f"unknown tool {params.name[:60]!r}"}}, True)
        try:
            args = spec.model.model_validate(params.arguments or {})
        except ValidationError as exc:
            fields = sorted({".".join(str(x) for x in e["loc"]) or "(root)" for e in exc.errors()})
            return _result({"error": {"code": "INVALID_ARGUMENTS", "message": "arguments rejected by schema",
                                      "fields": fields}}, True)
        try:
            return _result(await spec.handler(service, principal, args))
        except DomainError as exc:
            return _result({"error": exc.as_dict()}, True)

    return Server("rescuebridge", version="0.1.0", title="RescueBridge recovery tools", instructions=SERVER_INSTRUCTIONS,
                  on_list_tools=list_tools, on_call_tool=call_tool)


class McpBearerAuth:
    """Pure-ASGI middleware: every MCP HTTP request must carry a valid device-bound bearer token."""

    def __init__(self, app: ASGIApp, auth: AuthService) -> None:
        self.app = app
        self.auth = auth

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        authz = ""
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                authz = v.decode("latin-1")
                break
        verified = self.auth.verify_mcp_token(authz[7:].strip()) if authz[:7].lower() == "bearer " else None
        if verified is None:
            body = b'{"error":"unauthorized"}'
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": body})
            return
        scope["rb_principal"] = Principal(device_id=verified[0], session_id=verified[1], via="mcp")
        await self.app(scope, receive, send)


def build_mcp_app(service: RecoveryService, auth: AuthService, port: int) -> tuple[ASGIApp, Starlette]:
    server = build_mcp_server(service)
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                         allowed_hosts=[f"127.0.0.1:{port}", f"localhost:{port}"],
                                         allowed_origins=[])  # no browser origin may call MCP directly
    starlette_app = server.streamable_http_app(streamable_http_path="/mcp", transport_security=security,
                                               host="127.0.0.1")
    return McpBearerAuth(starlette_app, auth), starlette_app
