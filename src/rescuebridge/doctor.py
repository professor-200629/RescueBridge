"""Read-only setup doctor. Changes nothing; reports what works, what is missing, and what to do.

Checks: OS/runtime, dependencies, web build, data dir, helper reachability and mode, backend and MCP
endpoints, local model availability (no downloads), voice prerequisites, LAN reachability prerequisites,
and privilege context (administrator is NOT required and not recommended).
"""

from __future__ import annotations

import ctypes
import importlib.metadata as md
import json
import platform
import shutil
import sys
import time
from pathlib import Path

import httpx2

from rescuebridge.config import Settings

Row = tuple[str, str, str]  # status, check, detail
WEB_INDEX = Path(__file__).resolve().parents[2] / "web" / "dist" / "index.html"


async def run_doctor(settings: Settings) -> int:
    rows: list[Row] = []
    t0 = time.perf_counter()

    def add(status: str, check: str, detail: str) -> None:
        rows.append((status, check, detail))

    # --- OS / runtime ----------------------------------------------------------------------
    if sys.platform == "win32":
        add("OK", "Windows", f"{platform.platform()} ({platform.machine()})")
    else:
        add("FAIL", "Windows", "RescueBridge's helper requires Windows 10/11 (fixture mode works elsewhere)")
    add("OK" if sys.version_info[:2] == (3, 13) else "WARN", "Python", sys.version.split()[0] + " (tested: 3.13)")
    for pkg in ("mcp", "pycaw", "pywin32", "uvicorn", "starlette", "cryptography", "segno"):
        try:
            add("OK", f"package {pkg}", md.version(pkg))
        except md.PackageNotFoundError:
            add("FAIL", f"package {pkg}", "missing: run scripts\\setup.ps1")
    built = WEB_INDEX.exists()  # noqa: ASYNC240 - one stat() in a CLI command
    add("OK" if built else "FAIL", "web app build", str(WEB_INDEX.parent) if built else "not built: run scripts\\setup.ps1")
    node = shutil.which("node")
    add("OK" if node else "WARN", "Node.js (build only)", node or "not found (only needed to rebuild the web app)")
    add("OK" if settings.data_dir.exists() else "INFO", "data directory",
        f"{settings.data_dir}" + ("" if settings.data_dir.exists() else " (created on first start)"))

    # --- privilege ---------------------------------------------------------------------------
    if sys.platform == "win32":
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        add("WARN" if admin else "OK", "privilege",
            "running ELEVATED: not needed; elevated windows/settings are out of scope. Prefer a normal prompt."
            if admin else "standard (non-elevated) user context — as designed")

    # --- helper ------------------------------------------------------------------------------
    if settings.host_adapter == "fixture":
        add("WARN", "host adapter", "fixture mode: no real Windows state is read or changed")
    else:
        from rescuebridge.host.client import HelperUnavailableError, HostClient, PipeTransport

        try:
            h = await HostClient(PipeTransport(settings.helper_pipe_name, settings.helper_key_path)).health(timeout_s=3)
            r = h.get("result", {})
            add("OK", "Windows helper", f"reachable, mode={r.get('mode')}, pid={r.get('pid')}, fence={r.get('fence')}")
        except HelperUnavailableError as exc:
            add("FAIL", "Windows helper", f"{exc} — start it with scripts\\start.ps1")

    # --- backend / MCP -------------------------------------------------------------------------
    async with httpx2.AsyncClient(timeout=3.0) as c:
        try:
            r = await c.get(f"http://127.0.0.1:{settings.bff_port}/api/health")
            info = r.json() if r.status_code == 200 else {}
            add("OK" if r.status_code == 200 else "FAIL", "backend (browser app)",
                f"http://127.0.0.1:{settings.bff_port}/ -> {r.status_code}; adapter={info.get('host_adapter')}, "
                f"language={info.get('model_provider')}")
        except httpx2.HTTPError as exc:
            add("WARN", "backend (browser app)", f"not running ({type(exc).__name__}); start with scripts\\start.ps1")
        try:
            r = await c.post(f"http://127.0.0.1:{settings.mcp_port}/mcp", json={})
            add("OK" if r.status_code == 401 else "WARN", "MCP endpoint",
                f"loopback only; unauthenticated request -> {r.status_code} (401 expected)")
        except httpx2.HTTPError as exc:
            add("WARN", "MCP endpoint", f"not running ({type(exc).__name__})")
        # --- model ---------------------------------------------------------------------------
        try:
            r = await c.get(f"{settings.ollama_url}/api/tags")
            names = [m.get("name") for m in r.json().get("models", [])]
            have = settings.ollama_model in names
            status = "OK" if have else ("WARN" if settings.model_provider == "rules" else "FAIL")
            add(status, "local model (Ollama)", f"{settings.ollama_model} {'installed' if have else 'NOT installed'}; "
                f"configured provider={settings.model_provider}. RescueBridge never downloads models.")
        except (httpx2.HTTPError, ValueError) as exc:
            add("FAIL" if settings.model_provider == "ollama" else "WARN", "local model (Ollama)",
                f"not reachable at {settings.ollama_url} ({type(exc).__name__}); provider={settings.model_provider}")

    # --- voice / LAN --------------------------------------------------------------------------
    add("INFO", "voice", "Browser speech recognition (Chrome/Edge) may send audio to an online service; "
        "microphone needs https (LAN mode) or localhost. Typing always works.")
    from rescuebridge.runtime import lan_ip

    ip = lan_ip()
    add("OK" if ip else "WARN", "LAN address", ip or "none found (not on Wi-Fi?) — phone mode unavailable")
    if ip:
        add("INFO", "phone connectivity", "Phone must be on the same Wi-Fi without client isolation (guest Wi-Fi "
            "often blocks device-to-device traffic). Windows may ask to allow Python on private networks when LAN "
            "mode starts; RescueBridge never changes firewall rules itself.")
    elapsed = round((time.perf_counter() - t0) * 1000)
    width = max(len(c) for _, c, _ in rows)
    for status, check, detail in rows:
        print(f"[{status:4}] {check:<{width}}  {detail}")
    print(f"doctor finished in {elapsed} ms (read-only)")
    if "--json" in sys.argv:
        print(json.dumps({"elapsed_ms": elapsed, "rows": [{"status": s, "check": c, "detail": d} for s, c, d in rows]}))
    return 1 if any(s == "FAIL" for s, _, _ in rows) else 0
