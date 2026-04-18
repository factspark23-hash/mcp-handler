"""Tool router - forwards tool calls to correct backend server."""
import asyncio
import logging
import time
import hashlib
import json
from typing import Any
from mcp.types import TextContent
from .connector import ServerConnector
from .registry import Registry
from .quiet import QuietManager
from .db import Database
from .session import SessionTracker

logger = logging.getLogger("mcp_hub.router")


class Router:
    def __init__(self, registry: Registry, quiet: QuietManager,
                 db: Database, session: SessionTracker):
        self.registry = registry
        self.quiet = quiet
        self.db = db
        self.session = session
        self._connectors: dict[str, ServerConnector] = {}
        self._tracking_enabled = True
        self._track_params = False

    def register_connector(self, name: str, connector: ServerConnector):
        self._connectors[name] = connector

    async def route_call(self, tool_name: str, arguments: dict | None = None) -> list:
        """Route a tool call to the correct backend server."""
        result = self.registry.get_tool(tool_name)
        if not result:
            return [TextContent(type="text", text=f"Error: Tool '{tool_name}' not found")]

        server_name, original_name = result

        # Check quiet mode
        if self.quiet.is_quiet(tool_name, server_name):
            return [TextContent(type="text",
                                text=f"Tool '{tool_name}' is currently in quiet mode (disabled). "
                                     f"Use hub_quiet_off to re-enable.")]

        connector = self._connectors.get(server_name)
        if not connector or not connector.is_connected:
            return [TextContent(type="text",
                                text=f"Error: Server '{server_name}' is not connected")]

        # Execute with timing and retry
        start = time.monotonic()
        status = "success"
        error_msg = None
        result_content = None

        try:
            mcp_result = await connector.call_tool(original_name, arguments)
            result_content = mcp_result.content if hasattr(mcp_result, 'content') else [
                TextContent(type="text", text=str(mcp_result))
            ]
        except Exception as e:
            # Retry once after 5s
            logger.warning(f"Tool call '{original_name}' on '{server_name}' failed, retrying: {e}")
            await asyncio.sleep(5)
            try:
                mcp_result = await connector.call_tool(original_name, arguments)
                result_content = mcp_result.content if hasattr(mcp_result, 'content') else [
                    TextContent(type="text", text=str(mcp_result))
                ]
            except Exception as e2:
                status = "error"
                error_msg = str(e2)
                result_content = [TextContent(type="text", text=f"Error calling '{tool_name}': {e2}")]

        duration_ms = (time.monotonic() - start) * 1000

        # Track
        if self._tracking_enabled:
            params_hash = None
            if self._track_params and arguments:
                params_hash = hashlib.md5(json.dumps(arguments, sort_keys=True).encode()).hexdigest()

            response_size = sum(
                len(c.text) if hasattr(c, 'text') else 0
                for c in (result_content or [])
            )

            await self.db.log_call(
                server_name=server_name,
                tool_name=tool_name,
                duration_ms=duration_ms,
                status=status,
                session_id=self.session.session_id,
                original_tool_name=original_name,
                error_message=error_msg,
                params_hash=params_hash,
                response_size=response_size,
            )

            # Store replay entry
            try:
                params_json = json.dumps(arguments) if arguments else "{}"
                result_json = json.dumps([
                    {"type": c.type, "text": c.text} for c in (result_content or [])
                    if hasattr(c, 'text')
                ])
                await self.db.add_replay_entry(server_name, tool_name, params_json, result_json)
            except Exception:
                pass

            self.session.record_call(status, duration_ms)

            # Prune old records periodically
            await self.db.prune_old_records(100000)

        return result_content or [TextContent(type="text", text="(no response)")]

    def set_tracking(self, enabled: bool, track_params: bool = False):
        self._tracking_enabled = enabled
        self._track_params = track_params
