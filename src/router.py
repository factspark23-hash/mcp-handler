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
        self.cost_registry: dict[str, dict] = {}  # tool_name -> {cost_type, cost_value, description}
        self._call_count = 0
        self._hub_handler = None  # Set by server: async (name, args) -> list[TextContent]

    def register_connector(self, name: str, connector: ServerConnector):
        self._connectors[name] = connector

    def register_hub_handler(self, handler):
        """Register a callback for hub tool dispatch. Used by compose/session."""
        self._hub_handler = handler

    async def route_call(self, tool_name: str, arguments: dict | None = None) -> list:
        """Route a tool call to the correct backend server or hub handler."""
        # Check hub tools first
        if tool_name.startswith("hub_") and self._hub_handler:
            return await self._hub_handler(tool_name, arguments or {})

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
            # Only retry on transient errors (connection/timeout), not permanent ones
            err_str = str(e).lower()
            is_transient = any(kw in err_str for kw in (
                "timeout", "connection", "reset", "broken pipe", "eof", "disconnected"
            ))
            if is_transient:
                logger.warning(f"Tool call '{original_name}' on '{server_name}' failed (transient), retrying: {e}")
                await asyncio.sleep(3)
                try:
                    mcp_result = await connector.call_tool(original_name, arguments)
                    result_content = mcp_result.content if hasattr(mcp_result, 'content') else [
                        TextContent(type="text", text=str(mcp_result))
                    ]
                except Exception as e2:
                    status = "error"
                    error_msg = str(e2)
                    result_content = [TextContent(type="text", text=f"Error calling '{tool_name}': {e2}")]
            else:
                status = "error"
                error_msg = str(e)
                result_content = [TextContent(type="text", text=f"Error calling '{tool_name}': {e}")]

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
                params_json = json.dumps(arguments or {})
                result_parts = []
                for c in (result_content or []):
                    if hasattr(c, 'text'):
                        result_parts.append({"type": c.type, "text": c.text})
                    elif hasattr(c, 'data'):
                        result_parts.append({"type": c.type, "data": f"<{len(c.data)} bytes>"})
                    else:
                        result_parts.append({"type": str(type(c).__name__)})
                result_json = json.dumps(result_parts)
                await self.db.add_replay_entry(server_name, tool_name, params_json, result_json)
            except Exception:
                pass

            self.session.record_call(status, duration_ms)

            # Prune old records every 100 calls (not every call)
            self._call_count += 1
            if self._call_count % 100 == 0:
                await self.db.prune_old_records(100000)

        return result_content or [TextContent(type="text", text="(no response)")]

    def set_tracking(self, enabled: bool, track_params: bool = False):
        self._tracking_enabled = enabled
        self._track_params = track_params
