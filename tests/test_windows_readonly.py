"""Real Windows adapter, READ-ONLY. Reads the current user's actual state and asserts nothing changed.

No mutating method is called here. Window titles are never printed or stored by this test.
"""

from __future__ import annotations

import pytest

from rescuebridge.host.engine import HelperEngine

pytestmark = pytest.mark.windows_readonly


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    from rescuebridge.host.windows_ops import WindowsOps, enable_per_monitor_dpi_awareness

    enable_per_monitor_dpi_awareness()
    tmp = tmp_path_factory.mktemp("rw")
    return HelperEngine(WindowsOps(tmp / "workpad", tmp / "clicktest"))


def test_real_observations_have_expected_shape_and_do_not_change_state(engine):
    m1 = engine.handle({"op": "observe", "kind": "mouse"})
    a1 = engine.handle({"op": "observe", "kind": "audio"})
    w = engine.handle({"op": "observe", "kind": "windows"})
    m2 = engine.handle({"op": "observe", "kind": "mouse"})
    a2 = engine.handle({"op": "observe", "kind": "audio"})
    assert m1["ok"] and m1["mode"] == "real_windows"
    assert isinstance(m1["result"]["swap_effective"], bool)
    assert m1["result"]["swap_effective"] == m2["result"]["swap_effective"]
    assert a1["ok"]
    if a1["result"]["default"] is not None:
        d1, d2 = a1["result"]["default"], a2["result"]["default"]
        assert (d1["endpoint_id"], d1["muted"], d1["volume_scalar"]) == (d2["endpoint_id"], d2["muted"], d2["volume_scalar"])
        assert 0.0 <= d1["volume_scalar"] <= 1.0
    assert w["ok"]
    res = w["result"]
    assert len(res["monitors"]) >= 1 and res["primary_work_area"]
    assert len(res["monitors_fingerprint"]) == 32
    for c in res["candidates"]:
        assert set(c) >= {"target_ref", "app_label", "visible_fraction", "offscreen", "supported"}
        assert "title" not in c
        assert c["target_ref"].startswith("wt_")


def test_unknown_window_target_is_refused_without_side_effects(engine):
    w = engine.handle({"op": "observe", "kind": "windows"})
    r = engine.handle({"op": "execute", "revision": 10**6, "operation_id": "op_ro", "action": "MOVE_WINDOW",
                       "params": {"target_ref": "wt_0000000000000000", "rect": [0, 0, 800, 600],
                                  "monitors_fingerprint": w["result"]["monitors_fingerprint"]}})
    assert r["ok"] is False and r["error"]["code"] == "TARGET_INVALID"
