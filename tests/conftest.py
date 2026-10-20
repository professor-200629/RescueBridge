"""Shared fixtures. Default tests use the in-memory fixture adapter and never touch real Windows settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from rescuebridge.config import load_settings
from rescuebridge.context import AppContext, build_context
from rescuebridge.domain.service import Principal
from rescuebridge.host.fixture_ops import FixtureOps
from rescuebridge.ids import now_ms


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class Env:
    ctx: AppContext
    ops: FixtureOps
    phone: Principal  # model/MCP path for the phone device
    phone_ui: Principal  # authenticated UI path for the same device
    other_ui: Principal  # a second paired device
    tmp: Path

    @property
    def svc(self):  # noqa: ANN201
        return self.ctx.service


def make_env(tmp_path: Path, ops: FixtureOps | None = None) -> Env:
    settings = load_settings(data_dir=tmp_path, host_adapter="fixture", model_provider="rules")
    ops = ops or FixtureOps()
    ctx = build_context(settings, fixture_ops=ops, lab_armed=lambda: False)
    t = now_ms()
    for dev in ("dev_phone", "dev_other"):
        ctx.store.insert("devices", {"id": dev, "name": dev, "kind": "phone", "user_agent": "test", "created_at": t,
                                     "revoked_at": None})
    return Env(ctx=ctx, ops=ops, phone=Principal("dev_phone", "ses_phone", "mcp"),
               phone_ui=Principal("dev_phone", "ses_phone", "ui"), other_ui=Principal("dev_other", "ses_other", "ui"),
               tmp=tmp_path)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return make_env(tmp_path)
