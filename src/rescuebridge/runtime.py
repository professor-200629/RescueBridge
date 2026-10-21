"""Process entry points: the backend (BFF + MCP server) and the Windows helper."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import uvicorn

from rescuebridge.auth import AuthService
from rescuebridge.config import Settings
from rescuebridge.context import build_context

log = logging.getLogger("rescuebridge")


class _QuietSignalServer(uvicorn.Server):
    """Several uvicorn servers share one loop; signals are handled once, by `serve_backend`."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def is_elevated() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def lan_ip() -> str | None:
    """Best-effort primary IPv4 of this laptop (UDP connect sends no packets)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1, never routed to a real host
            ip = sock.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def write_host_link(settings: Settings, code: str) -> Path:
    from rescuebridge.host.pipe import write_private_file

    path = settings.data_dir / "host_link.txt"
    write_private_file(path, f"http://127.0.0.1:{settings.bff_port}/host#b={code}\n".encode())
    return path


async def serve_backend(settings: Settings) -> None:
    from rescuebridge.bff.app import build_bff_app
    from rescuebridge.mcp_server.server import build_mcp_app

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    ctx = build_context(settings)
    auth = AuthService(ctx.store, settings)
    notes = await ctx.service.reconcile_on_startup()
    for n in notes:
        log.warning("startup reconciliation: %s", n)
    lan_url = None
    ssl_kwargs: dict[str, Any] = {}
    ip = None
    if settings.lan_enabled:
        from rescuebridge.certs import ensure_lan_certificate

        ip = lan_ip()
        if ip is None:
            raise SystemExit("LAN mode: no LAN IPv4 address found. Connect to Wi-Fi first.")
        cert, key = ensure_lan_certificate(settings, ip)
        lan_url = f"https://{ip}:{settings.lan_port}"
        ssl_kwargs = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    usb = None
    if settings.usb_enabled:
        from rescuebridge.usb import UsbLink

        usb = UsbLink(settings.bff_port)
        await asyncio.to_thread(usb.ensure)  # a missing phone is reported, not fatal: the laptop app still works
    bff_app = build_bff_app(ctx, auth, lan_url=lan_url, usb=usb)
    mcp_app, _ = build_mcp_app(ctx.service, auth, settings.mcp_port)
    configs = [
        uvicorn.Config(bff_app, host=settings.bff_host, port=settings.bff_port, lifespan="off", log_level="warning"),
        uvicorn.Config(mcp_app, host=settings.mcp_host, port=settings.mcp_port, lifespan="on", log_level="warning"),
    ]
    if lan_url and ip:
        # Bound to the LAN address only (not 0.0.0.0). Windows may ask whether to allow this app on the
        # network: that prompt is the person's decision. RescueBridge never edits firewall rules itself.
        configs.append(uvicorn.Config(bff_app, host=ip, port=settings.lan_port, lifespan="off", log_level="warning",
                                      **ssl_kwargs))
    servers = [_QuietSignalServer(c) for c in configs]

    def _exit(*_: Any) -> None:
        for srv in servers:
            srv.should_exit = True

    signal.signal(signal.SIGINT, _exit)
    with contextlib.suppress(AttributeError, ValueError):
        signal.signal(signal.SIGBREAK, _exit)  # type: ignore[attr-defined]
    link_path = write_host_link(settings, auth.create_host_bootstrap())
    (settings.data_dir / "backend.pid").write_text(str(os.getpid()))
    print(f"RescueBridge backend running. Adapter={settings.host_adapter} model={settings.model_provider}")
    print(f"  Phone/desktop app : http://127.0.0.1:{settings.bff_port}/" + (f"   LAN: {lan_url}/" if lan_url else ""))
    print(f"  Host console link : stored in {link_path} (one-time, 10 minutes)")
    print(f"  MCP endpoint      : http://127.0.0.1:{settings.mcp_port}/mcp (loopback, bearer token required)")
    if usb:
        print(f"  Phone by USB      : {usb.status.state}{f' ({usb.status.model})' if usb.status.model else ''} - "
              f"{usb.status.detail}")
    sys.stdout.flush()
    try:
        await asyncio.gather(*(srv.serve() for srv in servers))
    finally:
        with contextlib.suppress(OSError):
            (settings.data_dir / "backend.pid").unlink()
        if usb and usb.status.state == "linked":
            usb.remove()


def run_helper(settings: Settings, *, fixture: bool = False) -> None:
    from rescuebridge.host.engine import HelperEngine
    from rescuebridge.host.pipe import PipeServer, write_private_file

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if not fixture and is_elevated():
        # Running elevated would make administrator windows look "same integrity" and therefore movable,
        # silently crossing the integrity boundary this prototype promises not to cross.
        raise SystemExit("The RescueBridge helper refuses to run elevated (as administrator). "
                         "Start it from a normal, non-elevated terminal.")
    ops: Any
    if fixture:
        from rescuebridge.host.fixture_ops import FixtureOps

        ops = FixtureOps()
    else:
        from rescuebridge.host.windows_ops import WindowsOps, enable_per_monitor_dpi_awareness

        enable_per_monitor_dpi_awareness()
        ops = WindowsOps(settings.workpad_dir, settings.data_dir / "clicktest")
    key = os.urandom(32)
    write_private_file(settings.helper_key_path, key)
    engine = HelperEngine(ops)
    server = PipeServer(engine, settings.helper_pipe_name, key)
    ready = threading.Event()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            server.serve_forever(ready)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
            ready.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    ready.wait(10)
    if errors:
        raise SystemExit(f"helper could not start: {errors[0]} (is another helper already running?)")
    (settings.data_dir / "helper.pid").write_text(str(os.getpid()))
    print(f"RescueBridge helper running as current user, mode={ops.mode}, pipe={settings.helper_pipe_name}")
    try:
        while t.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        with contextlib.suppress(OSError):
            (settings.data_dir / "helper.pid").unlink()
