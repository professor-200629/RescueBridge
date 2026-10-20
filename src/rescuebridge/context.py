"""Composition root: builds the store, host client, services from Settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rescuebridge.config import Settings, host_name
from rescuebridge.domain.service import RecoveryService
from rescuebridge.domain.store import Store
from rescuebridge.host.client import HostClient, InProcessTransport, PipeTransport, Transport
from rescuebridge.host.engine import HelperEngine
from rescuebridge.ids import new_id, now_ms


@dataclass
class AppContext:
    settings: Settings
    store: Store
    host_client: HostClient
    transport: Transport
    service: RecoveryService
    host_id: str
    fixture_ops: Any = None  # set in fixture mode (tests and fixture evaluation only)


def ensure_host(store: Store) -> str:
    row = store.one("SELECT v FROM meta_kv WHERE k = 'host_id'")
    if row:
        return str(row["v"])
    host_id = new_id("host")
    with store.tx():
        store.insert("hosts", {"id": host_id, "name": host_name(), "permission_revision": 1, "created_at": now_ms()})
        store.execute("INSERT INTO meta_kv(k, v) VALUES('host_id', ?)", (host_id,))
    return host_id


def build_context(settings: Settings, *, fixture_ops: Any = None, lab_armed: Any = None) -> AppContext:
    store = Store(settings.db_path)
    host_id = ensure_host(store)
    transport: Transport
    if settings.host_adapter == "fixture":
        import os

        from rescuebridge.host.fixture_ops import make_fixture

        fixture_ops = fixture_ops or make_fixture(os.environ.get("RB_FIXTURE_SCENARIO", "healthy"))
        transport = InProcessTransport(HelperEngine(fixture_ops))
    else:
        transport = PipeTransport(settings.helper_pipe_name, settings.helper_key_path)
    host_client = HostClient(transport)
    if lab_armed is None:
        from rescuebridge.lab.arming import is_armed

        def lab_armed() -> bool:
            return is_armed(settings)

    service = RecoveryService(store, host_client, settings, host_id=host_id, lab_armed=lab_armed)
    return AppContext(settings=settings, store=store, host_client=host_client, transport=transport, service=service,
                      host_id=host_id, fixture_ops=fixture_ops)
