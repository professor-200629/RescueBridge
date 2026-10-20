"""Async client for the helper protocol, used by the backend.

Transports:
- `InProcessTransport`: drives a HelperEngine directly (fixture mode and unit tests). Still goes through
  the fixed-schema `HelperEngine.handle`, fencing and serialization.
- `PipeTransport`: authenticated named-pipe IPC to the separate helper process.

`HelperUnavailable` means the helper could not be reached: callers must record that as UNAVAILABLE /
unknown, never as a negative observation such as "not muted".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import anyio

from rescuebridge.host.engine import HelperEngine


class HelperUnavailableError(Exception):
    pass


class HelperTimeoutError(HelperUnavailableError):
    """Request sent, no reply in time. For writes the outcome is UNKNOWN."""


class Transport(Protocol):
    description: str

    async def call(self, request: dict[str, Any], timeout_s: float) -> dict[str, Any]: ...


class InProcessTransport:
    def __init__(self, engine: HelperEngine) -> None:
        self.engine = engine
        self.description = f"in-process helper engine ({engine.mode})"
        self.available = True  # tests flip this to simulate an unreachable helper

    async def call(self, request: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        if not self.available:
            raise HelperUnavailableError("helper unavailable (simulated)")
        try:
            with anyio.fail_after(timeout_s):
                return await anyio.to_thread.run_sync(self.engine.handle, request, abandon_on_cancel=True)
        except TimeoutError as exc:
            raise HelperTimeoutError("helper did not respond in time") from exc


class PipeTransport:
    def __init__(self, pipe_name: str, key_path: Path) -> None:
        self.pipe_name = pipe_name
        self.key_path = key_path
        self.description = f"named pipe {pipe_name}"

    async def call(self, request: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        from rescuebridge.host import pipe

        def run() -> dict[str, Any]:
            return pipe.pipe_call(self.pipe_name, self.key_path, request, timeout_s)

        try:
            return await anyio.to_thread.run_sync(run, abandon_on_cancel=True)
        except pipe.HelperTimeout as exc:
            raise HelperTimeoutError(str(exc)) from exc
        except pipe.HelperUnavailable as exc:
            raise HelperUnavailableError(str(exc)) from exc


class HostClient:
    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    async def health(self, timeout_s: float = 3.0) -> dict[str, Any]:
        return await self.transport.call({"op": "health"}, timeout_s)

    async def observe(self, kind: str, test_id: str | None = None, timeout_s: float = 10.0) -> dict[str, Any]:
        req: dict[str, Any] = {"op": "observe", "kind": kind}
        if test_id:
            req["test_id"] = test_id
        return await self.transport.call(req, timeout_s)

    async def fence(self, revision: int, timeout_s: float = 3.0) -> dict[str, Any]:
        return await self.transport.call({"op": "fence", "revision": revision}, timeout_s)

    async def execute(self, *, action: str, params: dict[str, Any], revision: int, operation_id: str,
                      timeout_s: float = 10.0) -> dict[str, Any]:
        return await self.transport.call(
            {"op": "execute", "action": action, "params": params, "revision": revision, "operation_id": operation_id},
            timeout_s,
        )
