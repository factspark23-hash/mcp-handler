"""Auto-restart - restart crashed servers automatically."""
import asyncio
import logging
from .connector import ServerConnector
from .registry import Registry
from .db import Database

logger = logging.getLogger("mcp_hub.autorun")


class AutoRunner:
    def __init__(self, db: Database, max_attempts: int = 3, restart_delay: int = 5):
        self.db = db
        self.max_attempts = max_attempts
        self.restart_delay = restart_delay
        self._connectors: dict[str, ServerConnector] = {}
        self._server_configs: dict[str, dict] = {}
        self._enabled = True
        self._dependencies: dict[str, list[str]] = {}

    def register_server(self, name: str, connector: ServerConnector, config: dict):
        self._connectors[name] = connector
        self._server_configs[name] = config
        self._dependencies[name] = config.get("depends_on", [])

    async def restart_server(self, name: str) -> bool:
        if not self._enabled:
            return False

        connector = self._connectors.get(name)
        if not connector:
            return False

        if connector.restart_count >= self.max_attempts:
            logger.warning(f"[{name}] Max restart attempts ({self.max_attempts}) reached")
            return False

        logger.info(f"[{name}] Restarting (attempt {connector.restart_count + 1})...")

        # Disconnect first
        await connector.disconnect()
        await asyncio.sleep(self.restart_delay)

        # Reconnect
        connector.increment_restart()
        success = await connector.connect()

        if success:
            connector.reset_restart()
            logger.info(f"[{name}] Restart successful")
            # Re-discover tools
            await connector.discover_tools()
        else:
            logger.error(f"[{name}] Restart failed")

        return success

    async def handle_dependency_failure(self, failed_server: str):
        """When a server fails, pause its dependents."""
        for name, deps in self._dependencies.items():
            if failed_server in deps:
                connector = self._connectors.get(name)
                if connector and connector.is_connected:
                    logger.info(f"[{name}] Pausing (dependency '{failed_server}' is down)")
                    await connector.disconnect()

    async def handle_dependency_recovery(self, recovered_server: str):
        """When a server recovers, resume its dependents."""
        for name, deps in self._dependencies.items():
            if recovered_server in deps:
                connector = self._connectors.get(name)
                if connector and not connector.is_connected:
                    # Check if all dependencies are up
                    all_deps_up = all(
                        self._connectors.get(dep, ServerConnector(dep, {})).is_connected
                        for dep in deps
                    )
                    if all_deps_up:
                        logger.info(f"[{name}] Resuming (all dependencies up)")
                        await connector.connect()
                        await connector.discover_tools()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    async def check_and_restart(self):
        """Check all servers and restart any that are down."""
        for name, connector in self._connectors.items():
            if not connector.is_connected:
                success = await self.restart_server(name)
                if success:
                    await self.handle_dependency_recovery(name)
