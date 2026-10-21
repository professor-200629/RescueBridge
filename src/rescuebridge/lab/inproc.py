"""Run the real backend (BFF + MCP server over real loopback sockets) inside the current event loop.

Used by integration tests and the fixture evaluation harness. The host adapter is the fixture, so no real
Windows state is read or changed.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2

from rescuebridge.auth import AuthService
from rescuebridge.bff.app import build_bff_app
from rescuebridge.config import load_settings
from rescuebridge.context import AppContext, build_context
from rescuebridge.host.fixture_ops import FixtureOps
from rescuebridge.mcp_server.server import build_mcp_app
from rescuebridge.runtime import _QuietSignalServer


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class Backend:
    ctx: AppContext
    auth: AuthService
    ops: FixtureOps
    bff_url: str
    mcp_url: str

    def browser(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(base_url=self.bff_url, headers={"Origin": self.bff_url}, timeout=180)


@contextlib.asynccontextmanager
async def running_backend(data_dir: Path, ops: FixtureOps | None = None, **overrides: Any) -> AsyncIterator[Backend]:
    import uvicorn

    bff_port, mcp_port = free_port(), free_port()
    usb = overrides.pop("usb", None)
    settings = load_settings(data_dir=data_dir, host_adapter="fixture",
                             model_provider=overrides.pop("model_provider", "rules"),
                             bff_port=bff_port, mcp_port=mcp_port, **overrides)
    ops = ops or FixtureOps()
    ctx = build_context(settings, fixture_ops=ops, lab_armed=lambda: False)
    auth = AuthService(ctx.store, settings)
    bff = build_bff_app(ctx, auth, usb=usb)
    mcp_app, _ = build_mcp_app(ctx.service, auth, mcp_port)
    servers = [
        _QuietSignalServer(uvicorn.Config(bff, host="127.0.0.1", port=bff_port, lifespan="off", log_level="warning")),
        _QuietSignalServer(uvicorn.Config(mcp_app, host="127.0.0.1", port=mcp_port, lifespan="on", log_level="warning")),
    ]
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    for _ in range(250):
        if all(s.started for s in servers):
            break
        await asyncio.sleep(0.02)
    try:
        yield Backend(ctx=ctx, auth=auth, ops=ops, bff_url=f"http://127.0.0.1:{bff_port}",
                      mcp_url=f"http://127.0.0.1:{mcp_port}/mcp")
    finally:
        for s in servers:
            s.should_exit = True
        await asyncio.wait(tasks, timeout=10)
        ctx.store.close()


async def pair_device(be: Backend, name: str = "Test phone") -> tuple[httpx2.AsyncClient, str]:
    """Full pairing flow: host console bootstrap -> code -> phone request -> host accept -> phone claim."""
    host = be.browser()
    r = await host.post("/api/host/bootstrap", json={"code": be.auth.create_host_bootstrap()})
    assert r.status_code == 200, r.text
    hs = (await host.get("/api/session")).json()
    r = await host.post("/api/host/pairing-code", headers={"X-RB-CSRF": hs["csrf_token"]})
    pairing = r.json()["pairing"]
    phone = be.browser()
    r = await phone.post("/api/pair/request", json={"code": pairing["code"], "device_name": name})
    assert r.status_code == 200, r.text
    assert (await phone.post("/api/pair/claim")).json()["status"] == "PENDING"
    pending = (await host.get("/api/host/state")).json()["pending_requests"]
    r = await host.post(f"/api/host/requests/{pending[-1]['id']}/accept", headers={"X-RB-CSRF": hs["csrf_token"]})
    assert r.json()["accepted"] is True
    r = await phone.post("/api/pair/claim")
    assert r.json()["status"] == "PAIRED", r.text
    sess = (await phone.get("/api/session")).json()
    phone.headers["X-RB-CSRF"] = sess["csrf_token"]
    await host.aclose()
    return phone, sess["csrf_token"]
