"""Main MCP Server - entry point, registers 28 hub_* tools + all backend tools."""
import asyncio
import logging
import sys
import json
from contextlib import asynccontextmanager
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .config import Config
from .db import Database
from .connector import ServerConnector
from .registry import Registry
from .router import Router
from .aliases import AliasManager
from .namespacing import NamespaceManager
from .quiet import QuietManager
from .session import SessionTracker
from .health import HealthMonitor
from .autorun import AutoRunner
from .replay import ReplayManager
from .hotreload import HotReload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_hub")


class MCPHub:
    def __init__(self, config_path: str = "mcp_hub.yaml"):
        self.config = Config(config_path)
        self.config.load()

        # Core components
        self.db = Database(self.config.db_path)
        self.alias_manager = AliasManager()
        self.ns_manager = NamespaceManager(self.config.namespacing_mode)
        self.registry = Registry(self.ns_manager, self.alias_manager)
        self.quiet = QuietManager()
        self.session = SessionTracker()
        self.router = Router(self.registry, self.quiet, self.db, self.session)

        # Features
        hub_cfg = self.config.hub
        self.health = HealthMonitor(self.db, hub_cfg.get("health_check_interval", 30))
        self.autorun = AutoRunner(
            self.db,
            hub_cfg.get("max_restart_attempts", 3),
            hub_cfg.get("restart_delay", 5),
        )
        self.replay = ReplayManager(self.db, self.router)
        self.hotreload = HotReload(self.config, self.config.hotreload.get("watch_interval", 5))

        # Connectors
        self._connectors: dict[str, ServerConnector] = {}

        # MCP Server
        self.server = Server(hub_cfg.get("name", "MCP Hub"))
        self._register_hub_tools()

    def _register_hub_tools(self):
        """Register the 28 hub_* management tools."""

        @self.server.list_tools()
        async def list_tools():
            hub_tools = self._get_hub_tool_defs()
            backend_tools = list(self.registry.get_all_tools().values())
            return hub_tools + backend_tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict | None = None):
            # Hub tools
            handler = self._hub_tool_handlers.get(name)
            if handler:
                return await handler(arguments or {})

            # Backend tools - route to correct server
            if self.registry.has_tool(name):
                return await self.router.route_call(name, arguments)

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    def _get_hub_tool_defs(self) -> list[Tool]:
        return [
            # Status & Discovery (5)
            Tool("hub_status", "Get hub and all servers status", {"type": "object", "properties": {}}),
            Tool("hub_tools", "List all available tools", {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "Filter by server name"},
                    "search": {"type": "string", "description": "Search tool names/descriptions"},
                },
            }),
            Tool("hub_tool_info", "Get detailed info about a specific tool", {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Tool name"}},
                "required": ["name"],
            }),
            Tool("hub_search_tools", "Search tools by name or description", {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            }),
            Tool("hub_refresh", "Re-discover tools from all servers", {"type": "object", "properties": {}}),

            # Usage Analytics (6)
            Tool("hub_stats", "Get aggregated usage statistics", {
                "type": "object",
                "properties": {"since_hours": {"type": "number", "description": "Stats since N hours ago"}},
            }),
            Tool("hub_stats_detailed", "Get filtered call history", {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max records (default 50)"},
                    "since_hours": {"type": "number", "description": "Since N hours ago"},
                    "server": {"type": "string", "description": "Filter by server"},
                    "status": {"type": "string", "description": "Filter by status (success/error)"},
                },
            }),
            Tool("hub_top_tools", "Get most used tools", {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Top N (default 10)"}},
            }),
            Tool("hub_error_summary", "Get recent error summary", {
                "type": "object",
                "properties": {"since_hours": {"type": "number", "description": "Since N hours (default 24)"}},
            }),
            Tool("hub_session_stats", "Get current session statistics", {"type": "object", "properties": {}}),
            Tool("hub_slow_tools", "Get slowest tools by average duration", {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "Top N (default 10)"}},
            }),

            # Server Management (5)
            Tool("hub_server_info", "Get server details", {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Server name"}},
                "required": ["name"],
            }),
            Tool("hub_enable_server", "Enable a server", {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Server name"}},
                "required": ["name"],
            }),
            Tool("hub_disable_server", "Disable a server", {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Server name"}},
                "required": ["name"],
            }),
            Tool("hub_restart_server", "Restart a server", {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Server name"}},
                "required": ["name"],
            }),
            Tool("hub_server_logs", "Get server health logs", {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Server name"},
                    "limit": {"type": "integer", "description": "Max records (default 50)"},
                },
            }),

            # Tool Control (6)
            Tool("hub_quiet_on", "Temporarily disable tools/servers", {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Tool or server name"},
                    "duration": {"type": "integer", "description": "Seconds (omit for indefinite)"},
                    "scope": {"type": "string", "enum": ["tool", "server"], "description": "Target type"},
                },
                "required": ["target"],
            }),
            Tool("hub_quiet_off", "Re-enable quieted tools/servers", {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Tool/server name, or 'all'"},
                },
            }),
            Tool("hub_quiet_status", "Show currently quieted items", {"type": "object", "properties": {}}),
            Tool("hub_alias_set", "Set a tool alias", {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "description": "Full tool name (server__tool)"},
                    "alias": {"type": "string", "description": "Short alias name"},
                },
                "required": ["tool", "alias"],
            }),
            Tool("hub_alias_remove", "Remove a tool alias", {
                "type": "object",
                "properties": {"alias": {"type": "string", "description": "Alias to remove"}},
                "required": ["alias"],
            }),
            Tool("hub_alias_list", "List all aliases", {"type": "object", "properties": {}}),

            # Advanced (6)
            Tool("hub_replay", "Replay last N tool calls", {
                "type": "object",
                "properties": {"count": {"type": "integer", "description": "Number of calls (default 5)"}},
            }),
            Tool("hub_replay_one", "Replay a specific call by ID", {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "Replay entry ID"}},
                "required": ["id"],
            }),
            Tool("hub_config_reload", "Manually reload config", {"type": "object", "properties": {}}),
            Tool("hub_config_show", "Show current config", {"type": "object", "properties": {}}),
            Tool("hub_health_history", "Get server health history", {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "Filter by server"},
                    "limit": {"type": "integer", "description": "Max records (default 50)"},
                },
            }),
            Tool("hub_export_stats", "Export all stats as JSON", {"type": "object", "properties": {}}),
        ]

    async def _setup_hub_handlers(self):
        """Setup the 28 hub_* tool handlers."""

        async def _hub_status(args):
            status = self.health.get_overall_status()
            servers_info = []
            for name, info in status["servers"].items():
                state = "UP" if info["connected"] else "DOWN"
                servers_info.append(f"  {name}: {state} ({info['tool_count']} tools)")
            text = (
                f"Hub: {self.config.hub.get('name', 'MCP Hub')}\n"
                f"Servers: {status['servers_up']}/{status['servers_total']} up\n"
                f"Total tools: {status['total_tools']}\n"
                f"Session: {self.session.session_id} ({self.session.get_stats()['total_calls']} calls)\n"
                + "\n".join(servers_info)
            )
            return [TextContent(type="text", text=text)]

        async def _hub_tools(args):
            tools = self.registry.get_all_tools()
            filtered = {}
            for name, tool in tools.items():
                if args.get("server"):
                    result = self.registry.get_tool(name)
                    if result and result[0] != args["server"]:
                        continue
                if args.get("search"):
                    q = args["search"].lower()
                    if q not in name.lower() and q not in (tool.description or "").lower():
                        continue
                filtered[name] = tool.description or "(no description)"

            if not filtered:
                return [TextContent(type="text", text="No tools found matching criteria")]

            lines = [f"  {name}: {desc[:80]}" for name, desc in sorted(filtered.items())]
            return [TextContent(type="text", text=f"Tools ({len(filtered)}):\n" + "\n".join(lines))]

        async def _hub_tool_info(args):
            name = args["name"]
            result = self.registry.get_tool(name)
            if not result:
                return [TextContent(type="text", text=f"Tool '{name}' not found")]
            server_name, original_name = result
            tools = self.registry.get_all_tools()
            tool = tools.get(name)
            alias = self.alias_manager.get_alias(server_name, original_name)
            info = (
                f"Name: {name}\n"
                f"Server: {server_name}\n"
                f"Original: {original_name}\n"
                f"Alias: {alias or 'none'}\n"
                f"Description: {tool.description if tool else 'N/A'}\n"
                f"Schema: {json.dumps(tool.inputSchema, indent=2) if tool and tool.inputSchema else 'N/A'}"
            )
            return [TextContent(type="text", text=info)]

        async def _hub_search_tools(args):
            query = args["query"].lower()
            tools = self.registry.get_all_tools()
            matches = []
            for name, tool in tools.items():
                if query in name.lower() or query in (tool.description or "").lower():
                    matches.append(f"  {name}")
            if not matches:
                return [TextContent(type="text", text=f"No tools matching '{args['query']}'")]
            return [TextContent(type="text", text=f"Found {len(matches)}:\n" + "\n".join(matches))]

        async def _hub_refresh(args):
            count = 0
            for name, connector in self._connectors.items():
                if connector.is_connected:
                    tools = await connector.discover_tools()
                    count += len(tools)
            await self.registry.discover_all()
            return [TextContent(type="text", text=f"Refreshed. {len(self.registry.get_all_tools())} tools available.")]

        async def _hub_stats(args):
            since = args.get("since_hours")
            stats = await self.db.get_stats(since)
            total = await self.db.get_total_calls(since)
            if not stats:
                return [TextContent(type="text", text="No usage data yet")]
            lines = [f"Total calls: {total}\n"]
            for s in stats[:20]:
                lines.append(
                    f"  {s['server_name']}/{s['tool_name']}: "
                    f"{s['total_calls']} calls, avg {s['avg_duration_ms']:.0f}ms"
                )
            return [TextContent(type="text", text="\n".join(lines))]

        async def _hub_stats_detailed(args):
            calls = await self.db.get_call_history(
                limit=args.get("limit", 50),
                since_hours=args.get("since_hours"),
                server_name=args.get("server"),
                status=args.get("status"),
            )
            if not calls:
                return [TextContent(type="text", text="No calls found")]
            lines = []
            for c in calls:
                lines.append(
                    f"  #{c['id']} [{c['status']}] {c['server_name']}/{c['tool_name']} "
                    f"{c['duration_ms']:.0f}ms"
                )
            return [TextContent(type="text", text=f"Call history ({len(calls)}):\n" + "\n".join(lines))]

        async def _hub_top_tools(args):
            stats = await self.db.get_stats()
            limit = args.get("limit", 10)
            if not stats:
                return [TextContent(type="text", text="No usage data yet")]
            lines = []
            for s in stats[:limit]:
                lines.append(f"  {s['server_name']}/{s['tool_name']}: {s['total_calls']} calls")
            return [TextContent(type="text", text=f"Top {limit} tools:\n" + "\n".join(lines))]

        async def _hub_error_summary(args):
            errors = await self.db.get_error_summary(args.get("since_hours", 24))
            if not errors:
                return [TextContent(type="text", text="No errors in the last 24h")]
            total = sum(e["count"] for e in errors)
            lines = [f"{total} errors total:"]
            for e in errors[:10]:
                msg = (e["error_message"] or "unknown")[:60]
                lines.append(f"  {e['count']}x: {msg}")
            return [TextContent(type="text", text="\n".join(lines))]

        async def _hub_session_stats(args):
            stats = self.session.get_stats()
            return [TextContent(type="text", text=json.dumps(stats, indent=2))]

        async def _hub_slow_tools(args):
            slow = await self.db.get_slow_tools(args.get("limit", 10))
            if not slow:
                return [TextContent(type="text", text="No usage data yet")]
            lines = []
            for s in slow:
                if s["avg_duration_ms"] and s["avg_duration_ms"] > 0:
                    lines.append(
                        f"  {s['server_name']}/{s['tool_name']}: "
                        f"avg {s['avg_duration_ms']:.0f}ms ({s['total_calls']} calls)"
                    )
            return [TextContent(type="text", text="Slowest tools:\n" + "\n".join(lines) if lines else "No data")]

        async def _hub_server_info(args):
            name = args["name"]
            connector = self._connectors.get(name)
            if not connector:
                return [TextContent(type="text", text=f"Server '{name}' not found")]
            status = self.health.get_status().get(name, {})
            info = (
                f"Server: {name}\n"
                f"Connected: {connector.is_connected}\n"
                f"Transport: {connector.transport}\n"
                f"Tools: {len(connector.tools)}\n"
                f"Restarts: {connector.restart_count}\n"
                f"Status: {status.get('status', 'unknown')}"
            )
            return [TextContent(type="text", text=info)]

        async def _hub_enable_server(args):
            name = args["name"]
            connector = self._connectors.get(name)
            if not connector:
                return [TextContent(type="text", text=f"Server '{name}' not found")]
            if connector.is_connected:
                return [TextContent(type="text", text=f"Server '{name}' is already connected")]
            success = await connector.connect()
            if success:
                await connector.discover_tools()
                await self.registry.discover_all()
                return [TextContent(type="text", text=f"Server '{name}' enabled")]
            return [TextContent(type="text", text=f"Failed to enable '{name}'")]

        async def _hub_disable_server(args):
            name = args["name"]
            connector = self._connectors.get(name)
            if not connector:
                return [TextContent(type="text", text=f"Server '{name}' not found")]
            await connector.disconnect()
            await self.registry.discover_all()
            return [TextContent(type="text", text=f"Server '{name}' disabled")]

        async def _hub_restart_server(args):
            name = args["name"]
            success = await self.autorun.restart_server(name)
            if success:
                await self.registry.discover_all()
                return [TextContent(type="text", text=f"Server '{name}' restarted")]
            return [TextContent(type="text", text=f"Failed to restart '{name}'")]

        async def _hub_server_logs(args):
            name = args["name"]
            logs = await self.db.get_health_history(name, args.get("limit", 50))
            if not logs:
                return [TextContent(type="text", text=f"No logs for '{name}'")]
            lines = []
            for l in logs[:20]:
                from datetime import datetime
                ts = datetime.fromtimestamp(l["timestamp"]).strftime("%H:%M:%S")
                lines.append(f"  {ts}: {l['status']} (latency: {l.get('latency_ms', '?')}ms)")
            return [TextContent(type="text", text=f"Logs for {name}:\n" + "\n".join(lines))]

        async def _hub_quiet_on(args):
            target = args["target"]
            duration = args.get("duration")
            scope = args.get("scope", "tool")
            if scope == "server":
                self.quiet.quiet_server(target, duration)
            else:
                self.quiet.quiet_tool(target, duration)
            dur_text = f" for {duration}s" if duration else " indefinitely"
            return [TextContent(type="text", text=f"'{target}' quieted{dur_text}")]

        async def _hub_quiet_off(args):
            target = args.get("target", "all")
            if target == "all":
                self.quiet.unquiet_all()
                return [TextContent(type="text", text="All tools/servers re-enabled")]
            if self.quiet.unquiet_tool(target) or self.quiet.unquiet_server(target):
                return [TextContent(type="text", text=f"'{target}' re-enabled")]
            return [TextContent(type="text", text=f"'{target}' was not quieted")]

        async def _hub_quiet_status(args):
            status = self.quiet.get_status()
            if not status["tools"] and not status["servers"]:
                return [TextContent(type="text", text="Nothing is currently quieted")]
            lines = []
            for name, remaining in status["tools"].items():
                lines.append(f"  tool: {name} ({remaining}s remaining)")
            for name, remaining in status["servers"].items():
                lines.append(f"  server: {name} ({remaining}s remaining)")
            return [TextContent(type="text", text="Quieted:\n" + "\n".join(lines))]

        async def _hub_alias_set(args):
            tool_name = args["tool"]
            alias = args["alias"]
            result = self.registry.get_tool(tool_name)
            if not result:
                return [TextContent(type="text", text=f"Tool '{tool_name}' not found")]
            server_name, original = result
            self.alias_manager.set_alias(server_name, original, alias)
            await self.registry.discover_all()
            return [TextContent(type="text", text=f"Alias set: {alias} -> {tool_name}")]

        async def _hub_alias_remove(args):
            alias = args["alias"]
            if self.alias_manager.remove_alias(alias):
                await self.registry.discover_all()
                return [TextContent(type="text", text=f"Alias '{alias}' removed")]
            return [TextContent(type="text", text=f"Alias '{alias}' not found")]

        async def _hub_alias_list(args):
            aliases = self.alias_manager.list_aliases()
            if not aliases:
                return [TextContent(type="text", text="No aliases configured")]
            lines = [f"  {alias} -> {server}/{tool}" for alias, (server, tool) in aliases.items()]
            return [TextContent(type="text", text="Aliases:\n" + "\n".join(lines))]

        async def _hub_replay(args):
            return await self.replay.replay_last(args.get("count", 5))

        async def _hub_replay_one(args):
            return await self.replay.replay_one(args["id"])

        async def _hub_config_reload(args):
            try:
                self.config.load()
                return [TextContent(type="text", text="Config reloaded (restart needed for server changes)")]
            except Exception as e:
                return [TextContent(type="text", text=f"Config reload failed: {e}")]

        async def _hub_config_show(args):
            return [TextContent(type="text", text=json.dumps(self.config.data, indent=2, default=str))]

        async def _hub_health_history(args):
            logs = await self.db.get_health_history(
                args.get("server"), args.get("limit", 50)
            )
            if not logs:
                return [TextContent(type="text", text="No health data")]
            lines = []
            from datetime import datetime
            for l in logs[:20]:
                ts = datetime.fromtimestamp(l["timestamp"]).strftime("%H:%M:%S")
                lines.append(f"  {ts} {l['server_name']}: {l['status']}")
            return [TextContent(type="text", text="\n".join(lines))]

        async def _hub_export_stats(args):
            data = await self.db.export_stats()
            return [TextContent(type="text", text=data)]

        self._hub_tool_handlers = {
            "hub_status": _hub_status,
            "hub_tools": _hub_tools,
            "hub_tool_info": _hub_tool_info,
            "hub_search_tools": _hub_search_tools,
            "hub_refresh": _hub_refresh,
            "hub_stats": _hub_stats,
            "hub_stats_detailed": _hub_stats_detailed,
            "hub_top_tools": _hub_top_tools,
            "hub_error_summary": _hub_error_summary,
            "hub_session_stats": _hub_session_stats,
            "hub_slow_tools": _hub_slow_tools,
            "hub_server_info": _hub_server_info,
            "hub_enable_server": _hub_enable_server,
            "hub_disable_server": _hub_disable_server,
            "hub_restart_server": _hub_restart_server,
            "hub_server_logs": _hub_server_logs,
            "hub_quiet_on": _hub_quiet_on,
            "hub_quiet_off": _hub_quiet_off,
            "hub_quiet_status": _hub_quiet_status,
            "hub_alias_set": _hub_alias_set,
            "hub_alias_remove": _hub_alias_remove,
            "hub_alias_list": _hub_alias_list,
            "hub_replay": _hub_replay,
            "hub_replay_one": _hub_replay_one,
            "hub_config_reload": _hub_config_reload,
            "hub_config_show": _hub_config_show,
            "hub_health_history": _hub_health_history,
            "hub_export_stats": _hub_export_stats,
        }

    async def initialize(self):
        """Initialize all components."""
        logger.info(f"Initializing MCP Hub: {self.config.hub.get('name')}")

        # Init DB
        await self.db.init()
        tracking = self.config.tracking
        self.router.set_tracking(tracking.get("enabled", True), tracking.get("track_params", False))

        # Load aliases from config
        self.alias_manager.load_from_config(self.config.servers)

        # Setup hub tool handlers
        await self._setup_hub_handlers()

        # Create connectors for each server
        for name, server_cfg in self.config.servers.items():
            if not server_cfg.get("enabled", True):
                logger.info(f"[{name}] Skipping (disabled)")
                continue

            connector = ServerConnector(name, server_cfg)
            self._connectors[name] = connector
            self.registry.register_connector(name, connector)
            self.router.register_connector(name, connector)
            self.health.register_connector(name, connector)
            self.autorun.register_server(name, connector, server_cfg)

            # Connect
            success = await connector.connect()
            if success:
                await connector.discover_tools()
                logger.info(f"[{name}] Ready ({len(connector.tools)} tools)")
            else:
                logger.warning(f"[{name}] Failed to connect")

        # Discover all tools
        await self.registry.discover_all()
        logger.info(f"Hub ready: {len(self.registry.get_all_tools())} tools available")

        # Start background tasks
        await self.health.start()
        if self.config.hotreload.get("enabled", True):
            self.hotreload.on_reload(self._on_config_reload)
            await self.hotreload.start()

    async def _on_config_reload(self):
        """Handle config hot-reload."""
        self.alias_manager.load_from_config(self.config.servers)
        await self.registry.discover_all()

    async def shutdown(self):
        """Cleanup."""
        await self.health.stop()
        await self.hotreload.stop()
        for connector in self._connectors.values():
            await connector.disconnect()
        await self.db.close()
        logger.info("MCP Hub shut down")


async def run(config_path: str = "mcp_hub.yaml"):
    hub = MCPHub(config_path)
    await hub.initialize()

    async with stdio_server() as (read_stream, write_stream):
        await hub.server.run(read_stream, write_stream, hub.server.create_initialization_options())

    await hub.shutdown()


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "mcp_hub.yaml"
    asyncio.run(run(config_path))


if __name__ == "__main__":
    main()
