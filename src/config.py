"""Config loader - loads and validates mcp_hub.yaml."""
import yaml
import os
import re
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "hub": {
        "name": "MCP Hub",
        "log_level": "info",
        "database": "data/hub.db",
        "health_check_interval": 30,
        "auto_restart": True,
        "max_restart_attempts": 3,
        "restart_delay": 5,
    },
    "servers": {},
    "namespacing": {"mode": "auto"},
    "tracking": {
        "enabled": True,
        "max_records": 100000,
        "track_params": False,
        "session_tracking": True,
    },
    "hotreload": {
        "enabled": True,
        "watch_interval": 5,
    },
}


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ${VAR} and $VAR in strings."""
    if isinstance(value, str):
        def replacer(match):
            var = match.group(1) or match.group(2)
            return os.environ.get(var, match.group(0))
        return re.sub(r'\$\{(\w+)\}|\$(\w+)', replacer, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    def __init__(self, config_path: str = "mcp_hub.yaml"):
        self.config_path = config_path
        self._data: dict = {}
        self._mtime: float = 0

    def load(self) -> dict:
        path = Path(self.config_path)
        if not path.exists():
            # Try config.example.yaml
            example = Path("config.example.yaml")
            if example.exists():
                path = example
            else:
                raise FileNotFoundError(
                    f"Config file not found: {self.config_path}. "
                    "Copy config.example.yaml to mcp_hub.yaml and edit it."
                )

        self._mtime = path.stat().st_mtime
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        raw = _expand_env_vars(raw)
        self._data = _deep_merge(DEFAULT_CONFIG, raw)
        self._validate()
        return self._data

    def _validate(self):
        servers = self._data.get("servers", {})
        for name, server in servers.items():
            if "transport" not in server:
                raise ValueError(f"Server '{name}': missing 'transport'")
            if server["transport"] == "stdio" and "command" not in server:
                raise ValueError(f"Server '{name}': stdio transport requires 'command'")
            if server["transport"] in ("sse", "http") and "url" not in server:
                raise ValueError(f"Server '{name}': {server['transport']} transport requires 'url'")

    def has_changed(self) -> bool:
        path = Path(self.config_path)
        if not path.exists():
            return False
        current_mtime = path.stat().st_mtime
        if current_mtime != self._mtime:
            return True
        return False

    @property
    def data(self) -> dict:
        return self._data

    @property
    def hub(self) -> dict:
        return self._data.get("hub", {})

    @property
    def servers(self) -> dict:
        return self._data.get("servers", {})

    @property
    def tracking(self) -> dict:
        return self._data.get("tracking", {})

    @property
    def namespacing_mode(self) -> str:
        return self._data.get("namespacing", {}).get("mode", "auto")

    @property
    def hotreload(self) -> dict:
        return self._data.get("hotreload", {})

    @property
    def db_path(self) -> str:
        return self.hub.get("database", "data/hub.db")
