"""Backend side of the review fixes: snapshot versions, Stop authority, pairing-code validation, host-console
bootstrap errors and launcher, authentication of protected endpoints, and the preview recording. Fixture only."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from rescuebridge.auth import AuthError, normalize_code
from rescuebridge.host.fixture_ops import make_fixture
from rescuebridge.ids import now_ms
from tests.harness import pair_device, running_backend

pytestmark = pytest.mark.anyio
ROOT = Path(__file__).resolve().parents[1]


async def test_snapshot_version_is_monotonic_bound_to_device_and_advanced_by_stop(tmp_path):
    async with running_backend(tmp_path, make_fixture("muted")) as be:
        phone, _ = await pair_device(be, "Phone A")
        other, _ = await pair_device(be, "Phone B")
        s0 = (await phone.get("/api/state")).json()["snapshot"]
        dev_a = be.ctx.store.one("SELECT id FROM devices WHERE name = 'Phone A'")["id"]
        assert s0["device_id"] == dev_a and s0["mission_id"] is None
        assert (await other.get("/api/state")).json()["snapshot"]["device_id"] != dev_a
        s1 = (await phone.post("/api/utterance", json={"text": "I can't hear anything"})).json()["snapshot"]
        assert s1["seq"] > s0["seq"] and s1["mission_id"]
        assert (await phone.get("/api/state")).json()["snapshot"]["seq"] == s1["seq"]  # nothing changed: same version
        stop = (await phone.post("/api/stop")).json()
        assert stop["stop"]["stop_state"] == "CONFIRMED"  # the helper's fence acknowledged it
        assert stop["snapshot"]["seq"] > s1["seq"] and stop["status"]["mission"]["state"] == "STOPPED"
        # any snapshot taken before the Stop has a smaller version and is rejected by the client
        await phone.aclose()
        await other.aclose()


async def test_stop_without_a_reachable_helper_is_reported_unknown_not_confirmed(tmp_path):
    async with running_backend(tmp_path, make_fixture("muted")) as be:
        phone, _ = await pair_device(be)
        await phone.post("/api/utterance", json={"text": "I can't hear anything"})
        be.ctx.transport.available = False  # type: ignore[attr-defined]
        stop = (await phone.post("/api/stop")).json()
        assert stop["stop"]["stop_state"] == "HELPER_UNREACHABLE" and "unknown" in stop["stop"]["detail"]
        assert stop["status"]["mission"]["state"] == "STOPPED"  # recorded and revoked locally even so
        await phone.aclose()


def test_pairing_code_format_is_exactly_eight_digits():
    assert normalize_code("1234 5678") == "12345678" and normalize_code("1234-5678") == "12345678"
    for bad in ("", "1234567", "123456789", "12ab5678", "１２３４５６７８", "1234 567x"):
        assert normalize_code(bad) is None, bad


async def test_pairing_errors_are_distinct_and_malformed_codes_are_not_counted_as_guesses(tmp_path):
    async with running_backend(tmp_path) as be:
        anon = be.browser()

        async def code_of(body: dict) -> str:  # noqa: ANN001
            r = await anon.post("/api/pair/request", json=body)
            return r.json()["error"]["code"]

        assert await code_of({"code": ""}) == "MALFORMED_CODE"
        assert await code_of({"code": "123456789"}) == "MALFORMED_CODE"
        assert be.ctx.store.one("SELECT COUNT(*) AS n FROM pairing_failures")["n"] == 0
        assert await code_of({"code": "1234 5678"}) == "NO_ACTIVE_CODE"
        be.auth.create_pairing_code()
        be.ctx.store.execute("UPDATE pairing_codes SET expires_at = ?", (now_ms() - 1,))
        assert await code_of({"code": "1234 5678"}) == "CODE_EXPIRED"
        real = be.auth.create_pairing_code()["code"]
        wrong = "00000000" if real.replace("-", "") != "00000000" else "11111111"
        assert await code_of({"code": wrong}) == "WRONG_CODE"
        assert (await anon.post("/api/pair/request", json={"code": real.replace("-", " ")})).status_code == 200
        await anon.aclose()


async def test_host_bootstrap_errors_say_expired_used_or_invalid(tmp_path):
    async with running_backend(tmp_path) as be:
        code = be.auth.create_host_bootstrap()
        be.auth.consume_host_bootstrap(code)
        with pytest.raises(AuthError) as used:
            be.auth.consume_host_bootstrap(code)
        assert used.value.code == "BOOTSTRAP_USED"
        old = be.auth.create_host_bootstrap()
        be.ctx.store.execute("UPDATE host_bootstrap SET expires_at = ? WHERE used_at IS NULL", (now_ms() - 1,))
        with pytest.raises(AuthError) as expired:
            be.auth.consume_host_bootstrap(old)
        assert expired.value.code == "BOOTSTRAP_EXPIRED"
        with pytest.raises(AuthError) as bad:
            be.auth.consume_host_bootstrap("not-a-real-link")
        assert bad.value.code == "BAD_BOOTSTRAP" and "host-console.ps1" in bad.value.message


async def test_protected_endpoints_refuse_unauthenticated_requests(tmp_path):
    async with running_backend(tmp_path, make_fixture("muted")) as be:
        anon = be.browser()
        gets = ["/api/state", "/api/diagnostics", "/api/handoff", "/api/host/state", "/mcp-app/recovery-card"]
        posts = ["/api/utterance", "/api/proposals/prop_abcdefgh/approve", "/api/proposals/prop_abcdefgh/decline",
                 "/api/issues/iss_abcdefgh/answer", "/api/issues/iss_abcdefgh/inspect", "/api/issues/iss_abcdefgh/result",
                 "/api/stop", "/api/continue", "/api/operations/op_abcdefgh/undo", "/api/logout",
                 "/api/host/pairing-code", "/api/host/stop", "/api/host/requests/prq_x/accept",
                 "/api/host/devices/dev_x/revoke", "/api/mcp-app/tools-call"]
        for path in gets:
            assert (await anon.get(path)).status_code in (401, 403), path
        for path in posts:
            assert (await anon.post(path, json={"text": "I can't hear anything"})).status_code in (401, 403), path
        assert (await anon.get("/api/session")).json()["paired"] is False
        assert be.ops.calls == []
        await anon.aclose()


async def test_host_console_launcher_needs_a_running_backend_and_never_prints_the_secret(tmp_path, capsys):
    import os

    import anyio

    from rescuebridge.config import load_settings
    from rescuebridge.runtime import open_host_console

    opened: list[str] = []
    down = load_settings(data_dir=tmp_path / "down", bff_port=1)  # nothing listens on port 1
    assert open_host_console(down, opener=opened.append) == 1 and opened == []
    assert "not running" in capsys.readouterr().out
    assert not (tmp_path / "down").exists()  # no database is created for a folder nobody runs
    async with running_backend(tmp_path) as be:
        settings = be.ctx.settings
        before = be.ctx.store.one("SELECT COUNT(*) AS n FROM host_bootstrap")["n"]
        # Found on the owner's laptop: another instance answering on the port must not be mistaken for this folder's.
        assert await anyio.to_thread.run_sync(lambda: open_host_console(settings, opener=opened.append)) == 1
        assert opened == [] and be.ctx.store.one("SELECT COUNT(*) AS n FROM host_bootstrap")["n"] == before
        (settings.data_dir / "backend.pid").write_text(str(os.getpid()))  # this process hosts the backend
        assert await anyio.to_thread.run_sync(lambda: open_host_console(settings, opener=opened.append)) == 0
        assert len(opened) == 1 and opened[0].startswith(f"http://127.0.0.1:{settings.bff_port}/host#b=")
        assert be.ctx.store.one("SELECT COUNT(*) AS n FROM host_bootstrap")["n"] == before + 1
        secret = opened[0].split("#b=", 1)[1]
        assert secret not in capsys.readouterr().out
        be.auth.consume_host_bootstrap(secret)  # the link is a normal one-time bootstrap
        with pytest.raises(AuthError):
            be.auth.consume_host_bootstrap(secret)


async def test_preview_recording_matches_the_fixture_engine_and_holds_no_machine_data():
    spec = importlib.util.spec_from_file_location("make_preview_data", ROOT / "scripts" / "make_preview_data.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fresh = await mod.record()
    committed = json.loads((ROOT / "web" / "src" / "preview-data.json").read_text(encoding="utf-8"))

    def shape(d: dict) -> list:  # noqa: ANN001
        return [(s["path"].split("/")[2], [i["state"] for i in s["response"]["status"]["issues"]], s["response"]["reply"]["text"])
                for s in d["steps"]]

    assert shape(fresh) == shape(committed)  # regenerate with scripts/make_preview_data.py if this changes
    text = json.dumps(committed)
    assert committed["initial"]["status"]["adapter"] == "Fixture Simulation"
    assert '"pid"' not in text and "dev_" not in text and "Realtek" not in text
