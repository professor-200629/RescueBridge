"""Runtime configuration. Everything comes from explicit environment variables or defaults.

No provider, port, or mode is switched silently: the effective configuration is reported by
`rescuebridge doctor` and shown in the diagnostics view.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "RescueBridge"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    # Browser-facing backend-for-frontend (loopback HTTP for desktop development).
    bff_host: str = "127.0.0.1"
    bff_port: int = 8740
    # Optional LAN HTTPS listener for the paired phone (off unless --lan is given).
    lan_enabled: bool = False
    lan_port: int = 8743
    # MCP server: loopback only, bearer-token protected.
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8765
    # Host adapter: "helper" (named-pipe helper process) or "fixture" (in-process simulation).
    host_adapter: str = "helper"
    helper_pipe_name: str = r"\\.\pipe\RescueBridgeHelper"
    # Language model provider: "ollama" or "rules" (keyword interpreter, no LLM). Never switched silently.
    model_provider: str = "rules"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b-instruct"
    agent_max_model_turns: int = 4
    agent_max_tool_calls: int = 8
    agent_timeout_s: float = 60.0
    proposal_ttl_s: int = 300
    observation_ttl_s: int = 90
    pairing_code_ttl_s: int = 300
    session_ttl_s: int = 12 * 3600

    @property
    def db_path(self) -> Path:
        return self.data_dir / "rescuebridge.sqlite3"

    @property
    def helper_key_path(self) -> Path:
        return self.data_dir / "helper.key"

    @property
    def lab_dir(self) -> Path:
        return self.data_dir / "lab"

    @property
    def workpad_dir(self) -> Path:
        return self.data_dir / "workpad"

    @property
    def cert_dir(self) -> Path:
        return self.data_dir / "certs"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(**overrides: object) -> Settings:
    env: dict[str, object] = {}
    if v := os.environ.get("RB_DATA_DIR"):
        env["data_dir"] = Path(v)
    if v := os.environ.get("RB_BFF_PORT"):
        env["bff_port"] = int(v)
    if v := os.environ.get("RB_LAN_PORT"):
        env["lan_port"] = int(v)
    if v := os.environ.get("RB_MCP_PORT"):
        env["mcp_port"] = int(v)
    if v := os.environ.get("RB_HOST_ADAPTER"):
        env["host_adapter"] = v
    if v := os.environ.get("RB_HELPER_PIPE"):
        env["helper_pipe_name"] = v
    if v := os.environ.get("RB_MODEL_PROVIDER"):
        env["model_provider"] = v
    if v := os.environ.get("RB_OLLAMA_URL"):
        env["ollama_url"] = v
    if v := os.environ.get("RB_OLLAMA_MODEL"):
        env["ollama_model"] = v
    if v := os.environ.get("RB_AGENT_TIMEOUT_S"):
        env["agent_timeout_s"] = float(v)
    env["lan_enabled"] = _env_bool("RB_LAN", False)
    env.update(overrides)
    settings = Settings(**env)  # type: ignore[arg-type]
    if settings.host_adapter not in {"helper", "fixture"}:
        raise ValueError(f"RB_HOST_ADAPTER must be 'helper' or 'fixture', got {settings.host_adapter!r}")
    if settings.model_provider not in {"ollama", "rules", "ollama-tools"}:
        raise ValueError(f"RB_MODEL_PROVIDER must be 'rules', 'ollama' or 'ollama-tools', got {settings.model_provider!r}")
    return settings


def host_name() -> str:
    return platform.node() or "this-pc"
