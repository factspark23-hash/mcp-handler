"""Health monitoring - periodic ping to each server."""
import asyncio
import logging
import time
from .connector import ServerConnector
from .db import Database

logger = logging.getLogger("mcp_hub.health")


class HealthMonitor:
    def __init__(self, db: Database, interval: int = 30):
        self.db = db
        self.interval = interval
        self._connectors: dict[str, ServerConnector] = {}
        self._task: asyncio.Task | None = None
        self._running = False
        # Track server up/down timestamps for uptime calculation
        self._server_status: dict[str, dict] = {}

    def register_connector(self, name: str, connector: ServerConnector):
        self._connectors[name] = connector
        self._server_status[name] = {
            "status": "unknown",
            "last_check": 0,
            "last_up": 0,
            "total_up_time": 0,
            "total_check_time": 0,
        }

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Health monitor started (interval: {self.interval}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self._running:
            try:
                await self.check_all()
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(self.interval)

    async def check_all(self):
        for name, connector in self._connectors.items():
            await self._check_server(name, connector)

    async def _check_server(self, name: str, connector: ServerConnector):
        stats = self._server_status[name]
        now = time.time()
        stats["last_check"] = now

        latency = await connector.ping()
        tool_count = len(connector.tools)

        if latency is not None:
            status = "up"
            stats["status"] = "up"
            stats["last_up"] = now
        else:
            status = "down"
            stats["status"] = "down"

        stats["total_check_time"] += self.interval

        await self.db.log_health(
            server_name=name,
            status=status,
            latency_ms=latency,
            tool_count=tool_count,
            restart_count=connector.restart_count,
        )

    def get_status(self) -> dict:
        result = {}
        for name, connector in self._connectors.items():
            stats = self._server_status.get(name, {})
            uptime_pct = 0
            if stats.get("total_check_time", 0) > 0:
                uptime_pct = round(
                    (stats.get("total_up_time", 0) / stats["total_check_time"]) * 100, 1
                )

            result[name] = {
                "connected": connector.is_connected,
                "status": stats.get("status", "unknown"),
                "tool_count": len(connector.tools),
                "restart_count": connector.restart_count,
                "uptime_percent": uptime_pct,
            }
        return result

    def get_overall_status(self) -> dict:
        statuses = self.get_status()
        total = len(statuses)
        up = sum(1 for s in statuses.values() if s["connected"])
        total_tools = sum(s["tool_count"] for s in statuses.values())
        return {
            "servers_total": total,
            "servers_up": up,
            "servers_down": total - up,
            "total_tools": total_tools,
            "servers": statuses,
        }
