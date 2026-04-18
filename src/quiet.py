"""Quiet mode - temporarily disable tools/servers without config change."""
import time
import asyncio


class QuietManager:
    def __init__(self):
        # target -> expiry_time (None = permanent until manually re-enabled)
        self._quiet_tools: dict[str, float | None] = {}
        self._quiet_servers: dict[str, float | None] = {}

    def quiet_tool(self, tool_name: str, duration: float | None = None):
        expiry = time.time() + duration if duration else None
        self._quiet_tools[tool_name] = expiry

    def quiet_server(self, server_name: str, duration: float | None = None):
        expiry = time.time() + duration if duration else None
        self._quiet_servers[server_name] = expiry

    def unquiet_tool(self, tool_name: str) -> bool:
        return self._quiet_tools.pop(tool_name, None) is not None

    def unquiet_server(self, server_name: str) -> bool:
        return self._quiet_servers.pop(server_name, None) is not None

    def unquiet_all(self):
        self._quiet_tools.clear()
        self._quiet_servers.clear()

    def is_quiet(self, tool_name: str, server_name: str = None) -> bool:
        now = time.time()
        # Check server first
        if server_name and server_name in self._quiet_servers:
            expiry = self._quiet_servers[server_name]
            if expiry is None or expiry > now:
                return True
            del self._quiet_servers[server_name]

        # Check tool
        if tool_name in self._quiet_tools:
            expiry = self._quiet_tools[tool_name]
            if expiry is None or expiry > now:
                return True
            del self._quiet_tools[tool_name]

        return False

    def get_status(self) -> dict:
        now = time.time()
        status = {"tools": {}, "servers": {}}
        for name, expiry in self._quiet_tools.items():
            if expiry is None or expiry > now:
                remaining = int(expiry - now) if expiry else "indefinite"
                status["tools"][name] = remaining
        for name, expiry in self._quiet_servers.items():
            if expiry is None or expiry > now:
                remaining = int(expiry - now) if expiry else "indefinite"
                status["servers"][name] = remaining
        return status

    def cleanup_expired(self):
        now = time.time()
        self._quiet_tools = {k: v for k, v in self._quiet_tools.items() if v is None or v > now}
        self._quiet_servers = {k: v for k, v in self._quiet_servers.items() if v is None or v > now}
