"""`rescuebridge` command line."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from rescuebridge.config import load_settings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rescuebridge", description="RescueBridge second-channel recovery prototype")
    p.add_argument("--data-dir", help="data directory (default %%LOCALAPPDATA%%\\RescueBridge or RB_DATA_DIR)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="run the backend (browser app + MCP server)")
    sp.add_argument("--lan", action="store_true", help="also serve HTTPS on this laptop's LAN address for the phone")
    sp.add_argument("--fixture", action="store_true", help="use the in-process fixture adapter (no Windows changes)")
    sp.add_argument("--fixture-scenario", default="healthy",
                    help="fixture preset: healthy, muted, silent, swapped, left-handed, offscreen, two-offscreen, "
                         "elevated-offscreen, interview")
    sp.add_argument("--provider", choices=["rules", "ollama", "ollama-tools"],
                    help="rules = keyword interpreter (no LLM); ollama = local LLM interpretation; "
                         "ollama-tools = experimental free tool calling (default from RB_MODEL_PROVIDER)")
    sp.add_argument("--model", help="Ollama model name")

    hp = sub.add_parser("helper", help="run the Windows helper (current user, named pipe)")
    hp.add_argument("--fixture", action="store_true", help="helper process backed by fixture state (no Windows changes)")

    sub.add_parser("host-link", help="create a fresh one-time host-console link")
    sub.add_parser("doctor", help="read-only setup checks")
    tp = sub.add_parser("mcp-token", help="print a 1-hour MCP bearer token for a paired device (external MCP host)")
    tp.add_argument("--device", required=True)
    sub.add_parser("workpad", help="open the RescueBridge WorkPad demo app")
    bp = sub.add_parser("bench-model", help="local latency/correctness check of installed Ollama models (no downloads)")
    bp.add_argument("--models", default="qwen2.5:3b-instruct,llama3.2:3b")
    bp.add_argument("--timeout", type=float, default=120.0)
    bp.add_argument("--out", default="evidence")
    ev = sub.add_parser("eval", help="fixture evaluation: recorded scenarios through the full stack (no Windows changes)")
    ev.add_argument("--sets", default="fixture,heldout")
    ev.add_argument("--provider", choices=["rules", "ollama"], default="rules")
    ev.add_argument("--model", default="qwen2.5:3b-instruct")
    ev.add_argument("--out", default="evidence")
    bi = sub.add_parser("bench-interpret", help="keyword vs local-LLM interpretation on dev + held-out phrasings")
    bi.add_argument("--models", default="qwen2.5:3b-instruct,llama3.2:3b")
    bi.add_argument("--timeout", type=float, default=120.0)
    bi.add_argument("--out", default="evidence")

    lp = sub.add_parser("lab", help="controlled live lab (opt-in, real Windows changes)")
    lsub = lp.add_subparsers(dest="lab_cmd", required=True)
    la = lsub.add_parser("arm", help="arm the live lab for a named session")
    la.add_argument("--session", required=True)
    la.add_argument("--minutes", type=int, default=10)
    la.add_argument("--allow", required=True, help="comma list from: mouse,audio,workpad")
    li = lsub.add_parser("inject", help="inject one allowed fault")
    li.add_argument("fault", choices=["mouse-swap", "audio-mute", "audio-mute-silent", "workpad-offscreen"])
    lsub.add_parser("restore", help="restore the recorded clean state now")
    lsub.add_parser("status", help="show arming status")
    lsub.add_parser("disarm", help="restore and disarm")
    lw = lsub.add_parser("watchdog", help="restore automatically when the arming expires")
    lw.add_argument("--poll", type=float, default=2.0)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.data_dir:
        import os

        os.environ["RB_DATA_DIR"] = args.data_dir

    if args.cmd == "serve":
        overrides: dict[str, object] = {}
        if args.fixture:
            import os

            overrides["host_adapter"] = "fixture"
            os.environ["RB_FIXTURE_SCENARIO"] = args.fixture_scenario
        if args.provider:
            overrides["model_provider"] = args.provider
        if args.model:
            overrides["ollama_model"] = args.model
        if args.lan:
            overrides["lan_enabled"] = True
        from rescuebridge.runtime import serve_backend

        asyncio.run(serve_backend(load_settings(**overrides)))
        return 0
    if args.cmd == "helper":
        from rescuebridge.runtime import run_helper

        run_helper(load_settings(), fixture=args.fixture)
        return 0
    if args.cmd == "host-link":
        from rescuebridge.auth import AuthService
        from rescuebridge.domain.store import Store
        from rescuebridge.runtime import write_host_link

        s = load_settings()
        path = write_host_link(s, AuthService(Store(s.db_path), s).create_host_bootstrap())
        print(f"New one-time host-console link written to {path}")
        return 0
    if args.cmd == "doctor":
        from rescuebridge.doctor import run_doctor

        return asyncio.run(run_doctor(load_settings()))
    if args.cmd == "mcp-token":
        from rescuebridge.auth import AuthService
        from rescuebridge.domain.store import Store

        s = load_settings()
        print(AuthService(Store(s.db_path), s).mint_mcp_token_for_device(args.device))
        return 0
    if args.cmd == "bench-model":
        from pathlib import Path

        from rescuebridge.bench_model import run as bench_run

        s = load_settings()
        bench_run([m.strip() for m in args.models.split(",") if m.strip()], s.ollama_url, args.timeout, Path(args.out))
        return 0
    if args.cmd == "eval":
        from pathlib import Path

        from rescuebridge.lab.evaluate import run as eval_run

        logging.getLogger("httpx2").setLevel(logging.WARNING)
        logging.getLogger("mcp").setLevel(logging.WARNING)
        eval_run([x.strip() for x in args.sets.split(",") if x.strip()], args.provider, args.model, Path(args.out))
        return 0
    if args.cmd == "bench-interpret":
        from pathlib import Path

        from rescuebridge.bench_interpret import run as bench_i

        s = load_settings()
        bench_i([m.strip() for m in args.models.split(",") if m.strip()], s.ollama_url, args.timeout, Path(args.out))
        return 0
    if args.cmd == "workpad":
        from rescuebridge.workpad.app import run_workpad

        run_workpad(load_settings())
        return 0
    if args.cmd == "lab":
        from rescuebridge.lab import cli as lab_cli

        return lab_cli.run(load_settings(), args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
