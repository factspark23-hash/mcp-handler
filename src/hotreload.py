"""Config hot-reload - watches for config file changes."""
import asyncio
import logging
from .config import Config

logger = logging.getLogger("mcp_hub.hotreload")


class HotReload:
    def __init__(self, config: Config, interval: int = 5):
        self.config = config
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._running = False
        self._callback = None

    def on_reload(self, callback):
        """Register a callback to be called when config changes."""
        self._callback = callback

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Hot-reload watching {self.config.config_path} (interval: {self.interval}s)")

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
                if self.config.has_changed():
                    logger.info("Config file changed, reloading...")
                    try:
                        self.config.load()
                        if self._callback:
                            await self._callback()
                        logger.info("Config reloaded successfully")
                    except Exception as e:
                        logger.error(f"Config reload failed: {e}")
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Hot-reload error: {e}")
                await asyncio.sleep(self.interval)
