"""MCP Apps: the read-only recovery card that get_recovery_status declares, served over MCP and hosted by the
simulator in a sandboxed frame. Fixture adapter only."""

from __future__ import annotations

import re

import pytest

from rescuebridge.agent.mcp_client import McpToolClient
from rescuebridge.mcp_server.server import APP_MIME, CARD_HTML, CARD_URI
from tests.harness import pair_device, running_backend

pytestmark = pytest.mark.anyio


async def test_tool_declares_the_card_and_the_resource_is_served_over_mcp(tmp_path):
    async with running_backend(tmp_path) as be:
        phone, _ = await pair_device(be)
        dev = be.ctx.store.one("SELECT id FROM devices WHERE revoked_at IS NULL")
        async with McpToolClient(be.mcp_url, be.auth.mint_mcp_token_for_device(dev["id"])) as mcp:
            assert await mcp.tool_ui_resource("get_recovery_status") == CARD_URI
            assert await mcp.tool_ui_resource("apply_recovery") is None  # only the read-only status has a view
            assert mcp._client is not None
            listed = (await mcp._client.list_resources()).resources
            assert [(str(r.uri), r.mime_type) for r in listed] == [(CARD_URI, APP_MIME)]
            html, mime = await mcp.read_text_resource(CARD_URI)
            assert mime == APP_MIME and html == CARD_HTML
            with pytest.raises(Exception, match="unknown resource"):
                await mcp.read_text_resource("ui://rescuebridge/something-else")
            result = await mcp.call_result("get_recovery_status", {})
            assert result["structuredContent"]["issues"] == [] and result["content"][0]["type"] == "text"
        await phone.aclose()


def test_card_is_self_contained_read_only_and_speaks_the_ui_protocol():
    assert re.findall(r"\b(?:src|href|action)\s*=", CARD_HTML) == []  # loads nothing, links nowhere
    assert set(re.findall(r"https?://[^\s\"'<>]+", CARD_HTML)) == {"http://www.w3.org/2000/svg"}  # SVG namespace only
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function", "fetch(", "XMLHttpRequest",
                   "WebSocket", "apply_recovery", "stop_recovery", "record_user_result", "undo_recovery"):
        assert banned not in CARD_HTML, banned
    # the only tool the view can ask the host to call is the read-only status tool
    assert re.findall(r'request\("tools/call", \{ name: "(\w+)"', CARD_HTML) == ["get_recovery_status"]
    for needed in ('"2026-01-26"', '"ui/initialize"', "appInfo", '"ui/notifications/initialized"',
                   '"ui/notifications/tool-result"', '"ui/notifications/size-changed"', "ev.source !== window.parent"):
        assert needed in CARD_HTML, needed


async def test_simulator_hosts_the_card_sandboxed_and_limits_what_it_may_call(tmp_path):
    async with running_backend(tmp_path) as be:
        anon = be.browser()
        assert (await anon.get("/mcp-app/recovery-card")).status_code == 401
        phone, _ = await pair_device(be)
        r = await phone.get("/mcp-app/recovery-card")
        assert r.status_code == 200 and r.text == CARD_HTML  # served exactly as the MCP server provided it
        csp = r.headers.get_list("content-security-policy")
        assert len(csp) == 1, csp  # no second (page) policy stacked on top
        for part in ("sandbox allow-scripts", "frame-ancestors 'self'", "connect-src 'none'", "default-src 'none'"):
            assert part in csp[0], part
        assert "allow-same-origin" not in csp[0] and r.headers["x-frame-options"] == "SAMEORIGIN"
        page = await phone.get("/")
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]  # other pages unchanged
        assert (await phone.post("/api/mcp-app/tools-call", json={"name": "apply_recovery"})).status_code == 403
        assert (await phone.post("/api/mcp-app/tools-call", json={"name": "get_recovery_status"},
                                 headers={"X-RB-CSRF": "wrong"})).status_code == 403
        r = await phone.post("/api/mcp-app/tools-call", json={"name": "get_recovery_status"})
        assert r.status_code == 200 and r.json()["structuredContent"]["mission"] is None
        assert be.ops.calls == []
        await phone.aclose()
        await anon.aclose()
