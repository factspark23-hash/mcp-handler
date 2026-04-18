"""MCP connector - manages connections to backend MCP servers."""
import asyncio
import logging
from typing import Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger("mcp_hub.connector")


class ServerConnector:
    """Manages a connection to one backend MCP server."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.transport = config.get("transport", "stdio")
        self.session: ClientSession | None = None
        self._client_ctx = None
        self._read = None
        self._write = None
        self._tools: list = []
        self._connected = False
        self._restart_count = 0
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        async with self._lock:
            if self._connected:
                return True
            try:
                if self.transport == "stdio":
                    return await self._connect_stdio()
                elif self.transport in ("sse", "http"):
                    return await self._connect_http()
                else:
                    logger.error(f"[{self.name}] Unknown transport: {self.transport}")
                    return False
            except Exception as e:
                logger.error(f"[{self.name}] Connection failed: {e}")
                self._connected = False
                return False

    async def _connect_stdio(self) -> bool:
        command = self.config["command"]
        args = self.config.get("args", [])
        env = self.config.get("env", None)

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
        )

        try:
            self._client_ctx = stdio_client(server_params)
            self._read, self._write = await self._client_ctx.__aenter__()
            self.session = ClientSession(self._read, self._write)
            await self.session.__aenter__()
            await self.session.initialize()
            self._connected = True
            logger.info(f"[{self.name}] Connected via stdio")
            return True
        except Exception as e:
            logger.error(f"[{self.name}] stdio connection failed: {e}")
            await self._cleanup()
            return False

    async def _connect_http(self) -> bool:
        url = self.config["url"]
        try:
            self._client_ctx = streamablehttp_client(url)
            self._read, self._write, _ = await self._client_ctx.__aenter__()
            self.session = ClientSession(self._read, self._write)
            await self.session.__aenter__()
            await self.session.initialize()
            self._connected = True
            logger.info(f"[{self.name}] Connected via HTTP to {url}")
            return True
        except Exception as e:
            logger.error(f"[{self.name}] HTTP connection failed: {e}")
            await self._cleanup()
            return False

    async def discover_tools(self) -> list:
        if not self._connected or not self.session:
            return []
        try:
            result = await self.session.list_tools()
            self._tools = result.tools
            logger.info(f"[{self.name}] Discovered {len(self._tools)} tools")
            return self._tools
        except Exception as e:
            logger.error(f"[{self.name}] Tool discovery failed: {e}")
            self._connected = False
            return []

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> Any:
        if not self._connected or not self.session:
            raise RuntimeError(f"Server '{self.name}' is not connected")
        try:
            result = await self.session.call_tool(tool_name, arguments or {})
            return result
        except Exception as e:
            logger.error(f"[{self.name}] Tool call '{tool_name}' failed: {e}")
            raise

    async def disconnect(self):
        async with self._lock:
            await self._cleanup()

    async def _cleanup(self):
        self._connected = False
        try:
            if self.session:
                await self.session.__aexit__(None, None, None)
                self.session = None
        except Exception:
            pass
        try:
            if self._client_ctx:
                await self._client_ctx.__aexit__(None, None, None)
                self._client_ctx = None
        except Exception:
            pass

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list:
        return self._tools

    @property
    def restart_count(self) -> int:
        return self._restart_count

    def increment_restart(self):
        self._restart_count += 1

    def reset_restart(self):
        self._restart_count = 0

    async def ping(self) -> float | None:
        """Ping the server, return latency in ms or None if failed."""
        if not self._connected or not self.session:
            return None
        try:
            import time
            start = time.monotonic()
            await self.session.list_tools()
            return (time.monotonic() - start) * 1000
        except Exception:
            self._connected = False
            return None
