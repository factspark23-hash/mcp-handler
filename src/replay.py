"""Call replay - replay previous tool calls for debugging."""
import json
import logging
from mcp.types import TextContent
from .db import Database
from .router import Router

logger = logging.getLogger("mcp_hub.replay")


class ReplayManager:
    def __init__(self, db: Database, router: Router):
        self.db = db
        self.router = router

    async def replay_last(self, count: int = 5) -> list:
        entries = await self.db.get_replay_entries(count)
        if not entries:
            return [TextContent(type="text", text="No calls to replay")]

        results = []
        for entry in entries:
            try:
                params = json.loads(entry["params_json"]) if entry["params_json"] else {}
                tool_name = entry["tool_name"]
                result = await self.router.route_call(tool_name, params)
                status = "OK" if not any(
                    hasattr(r, 'text') and r.text.startswith("Error") for r in result
                ) else "ERROR"
                results.append(f"{tool_name} ({status})")
            except Exception as e:
                results.append(f"{entry['tool_name']} (ERROR: {e})")

        return [TextContent(type="text", text=f"Replayed {len(results)} calls: {', '.join(results)}")]

    async def replay_one(self, entry_id: int) -> list:
        entry = await self.db.get_replay_entry(entry_id)
        if not entry:
            return [TextContent(type="text", text=f"Replay entry #{entry_id} not found")]

        try:
            params = json.loads(entry["params_json"]) if entry["params_json"] else {}
            tool_name = entry["tool_name"]
            result = await self.router.route_call(tool_name, params)
            return [TextContent(type="text", text=f"Replayed #{entry_id}: {tool_name}")] + result
        except Exception as e:
            return [TextContent(type="text", text=f"Replay failed: {e}")]
