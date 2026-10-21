"""Record the simulated-preview conversation from the real fixture engine (no Windows access).

Runs one complete recovery ("I can't hear anything" -> exact proposal -> approve -> verified -> test tone ->
"yes, it works") through the in-process backend (BFF + MCP server + fixture adapter) and writes the responses to
web/src/preview-data.json. The browser preview replays exactly these snapshots and makes no requests.

    .venv\\Scripts\\python.exe scripts\\make_preview_data.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import anyio

from rescuebridge.host.fixture_ops import make_fixture
from rescuebridge.lab.inproc import pair_device, running_backend

OUT = Path(__file__).resolve().parents[1] / "web" / "src" / "preview-data.json"
UTTERANCE = "I can't hear anything"


def sanitize(payload: dict[str, Any], device_id: str) -> dict[str, Any]:
    text = json.dumps(payload).replace(device_id, "preview-device")
    out = json.loads(text)
    out["helper"] = {"reachable": True, "mode": "fixture_simulation"}  # no process ids from the recording machine
    out.pop("run", None)
    return out


async def record() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        async with running_backend(Path(d), make_fixture("muted")) as be:
            phone, _ = await pair_device(be, name="Preview")
            dev = be.ctx.store.one("SELECT id FROM devices")["id"]
            steps: list[dict[str, Any]] = []

            async def step(path: str, body: dict[str, Any]) -> dict[str, Any]:
                r = await phone.post(path, json=body)
                assert r.status_code == 200, (path, r.text)
                data = r.json()
                steps.append({"path": path, "response": sanitize(data, dev)})
                return data

            initial = sanitize((await phone.get("/api/state")).json(), dev)
            r = await step("/api/utterance", {"text": UTTERANCE, "input_mode": "text"})
            issue = r["status"]["issues"][0]
            fix = issue["open_proposals"][0]
            r = await step(f"/api/proposals/{fix['proposal_id']}/approve", {"digest": fix["digest"]})
            tone = next(p for p in r["status"]["issues"][0]["open_proposals"] if p["kind"] == "TEST")
            await step(f"/api/proposals/{tone['proposal_id']}/approve", {"digest": tone["digest"]})
            r = await step(f"/api/issues/{issue['issue_id']}/result", {"result": "works"})
            assert r["status"]["issues"][0]["state"] == "RESOLVED"
            await phone.aclose()
            return {"_note": "Recorded by scripts/make_preview_data.py from the fixture engine (Fixture Simulation). "
                             "Replayed by the simulated preview; it never reaches a laptop.",
                    "fixture": "muted", "utterance": UTTERANCE, "recorded_at": initial["server_time"],
                    "initial": initial, "steps": steps}


def main() -> None:
    data = anyio.run(record)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(data['steps'])} steps)")


if __name__ == "__main__":
    main()
