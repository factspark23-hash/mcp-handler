"""Main MCP Server - entry point, registers 28 hub_* tools + all backend tools."""
import asyncio
import logging
import sys
import json
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

        # Workflow templates and stateful sessions (in-memory)
        self._workflow_templates: dict[str, list] = {}
        self._stateful_sessions: dict[str, dict] = {}

        # MCP Server
        self.server = Server(hub_cfg.get("name", "MCP Hub"))
        self._initialized = False
        self._register_handlers()

    def _register_handlers(self):
        """Register MCP protocol handlers. Decorators capture `self` — all state accessed lazily."""

        HUB_TOOLS = [
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
                "properties": {"target": {"type": "string", "description": "Tool/server name, or 'all'"}},
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
            # Composition (2)
            Tool("hub_compose", "Chain multiple tool calls into one workflow", {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "description": "Array of {tool, arguments} steps. Use {{step_N.output}} to reference previous results.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {"type": "string"},
                                "arguments": {"type": "object"},
                            },
                            "required": ["tool"],
                        },
                    },
                },
                "required": ["steps"],
            }),
            Tool("hub_compose_template", "Save/load workflow templates", {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["save", "load", "list", "delete"]},
                    "name": {"type": "string"},
                    "steps": {"type": "array"},
                },
                "required": ["action"],
            }),
            # Sessions (2)
            Tool("hub_session_begin", "Start a stateful multi-step session", {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Session name"},
                    "context": {"type": "object", "description": "Initial context data"},
                },
                "required": ["name"],
            }),
            Tool("hub_session_step", "Execute a step in an active session", {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "tool": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["session_id", "tool"],
            }),
            # Cost (2)
            Tool("hub_cost_estimate", "Estimate cost before calling a tool", {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "description": "Tool name"},
                    "arguments": {"type": "object"},
                },
                "required": ["tool"],
            }),
            Tool("hub_cost_register", "Register cost metadata for a tool", {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "cost_type": {"type": "string", "enum": ["free", "flat", "per_call", "per_token", "per_byte"]},
                    "cost_value": {"type": "number", "description": "Cost in USD (0 for free)"},
                    "description": {"type": "string"},
                },
                "required": ["tool", "cost_type"],
            }),
        ]

        @self.server.list_tools()
        async def list_tools():
            if not self._initialized:
                return HUB_TOOLS
            backend_tools = list(self.registry.get_all_tools().values())
            return HUB_TOOLS + backend_tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict | None = None):
            args = arguments or {}

            # Dispatch hub tools
            if name == "hub_status":
                return await self._hub_status(args)
            elif name == "hub_tools":
                return await self._hub_tools(args)
            elif name == "hub_tool_info":
                return await self._hub_tool_info(args)
            elif name == "hub_search_tools":
                return await self._hub_search_tools(args)
            elif name == "hub_refresh":
                return await self._hub_refresh(args)
            elif name == "hub_stats":
                return await self._hub_stats(args)
            elif name == "hub_stats_detailed":
                return await self._hub_stats_detailed(args)
            elif name == "hub_top_tools":
                return await self._hub_top_tools(args)
            elif name == "hub_error_summary":
                return await self._hub_error_summary(args)
            elif name == "hub_session_stats":
                return await self._hub_session_stats(args)
            elif name == "hub_slow_tools":
                return await self._hub_slow_tools(args)
            elif name == "hub_server_info":
                return await self._hub_server_info(args)
            elif name == "hub_enable_server":
                return await self._hub_enable_server(args)
            elif name == "hub_disable_server":
                return await self._hub_disable_server(args)
            elif name == "hub_restart_server":
                return await self._hub_restart_server(args)
            elif name == "hub_server_logs":
                return await self._hub_server_logs(args)
            elif name == "hub_quiet_on":
                return await self._hub_quiet_on(args)
            elif name == "hub_quiet_off":
                return await self._hub_quiet_off(args)
            elif name == "hub_quiet_status":
                return await self._hub_quiet_status(args)
            elif name == "hub_alias_set":
                return await self._hub_alias_set(args)
            elif name == "hub_alias_remove":
                return await self._hub_alias_remove(args)
            elif name == "hub_alias_list":
                return await self._hub_alias_list(args)
            elif name == "hub_replay":
                return await self._hub_replay(args)
            elif name == "hub_replay_one":
                return await self._hub_replay_one(args)
            elif name == "hub_config_reload":
                return await self._hub_config_reload(args)
            elif name == "hub_config_show":
                return await self._hub_config_show(args)
            elif name == "hub_health_history":
                return await self._hub_health_history(args)
            elif name == "hub_export_stats":
                return await self._hub_export_stats(args)
            elif name == "hub_compose":
                return await self._hub_compose(args)
            elif name == "hub_compose_template":
                return await self._hub_compose_template(args)
            elif name == "hub_session_begin":
                return await self._hub_session_begin(args)
            elif name == "hub_session_step":
                return await self._hub_session_step(args)
            elif name == "hub_cost_estimate":
                return await self._hub_cost_estimate(args)
            elif name == "hub_cost_register":
                return await self._hub_cost_register(args)

            # Backend tools
            if self.registry.has_tool(name):
                return await self.router.route_call(name, args)

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    # ── Hub tool handlers ─────────────────────────────────────────────

    async def _hub_status(self, args):
        status = self.health.get_overall_status()
        lines = [
            f"Hub: {self.config.hub.get('name', 'MCP Hub')}",
            f"Servers: {status['servers_up']}/{status['servers_total']} up",
            f"Total tools: {status['total_tools']}",
            f"Session: {self.session.session_id} ({self.session.get_stats()['total_calls']} calls)",
        ]
        for name, info in status["servers"].items():
            state = "UP" if info["connected"] else "DOWN"
            lines.append(f"  {name}: {state} ({info['tool_count']} tools)")
        return [TextContent(type="text", text="\n".join(lines))]

    async def _hub_tools(self, args):
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

    async def _hub_tool_info(self, args):
        name = args["name"]
        result = self.registry.get_tool(name)
        if not result:
            return [TextContent(type="text", text=f"Tool '{name}' not found")]
        server_name, original_name = result
        tools = self.registry.get_all_tools()
        tool = tools.get(name)
        alias = self.alias_manager.get_alias(server_name, original_name)
        cost = self.router.cost_registry.get(name)
        info_lines = [
            f"Name: {name}",
            f"Server: {server_name}",
            f"Original: {original_name}",
            f"Alias: {alias or 'none'}",
            f"Description: {tool.description if tool else 'N/A'}",
        ]
        if cost:
            info_lines.append(f"Cost: {cost['cost_type']} (${cost['cost_value']:.4f}) - {cost.get('description', '')}")
        if tool and tool.inputSchema:
            info_lines.append(f"Schema: {json.dumps(tool.inputSchema, indent=2)}")
        return [TextContent(type="text", text="\n".join(info_lines))]

    async def _hub_search_tools(self, args):
        query = args["query"].lower()
        tools = self.registry.get_all_tools()
        matches = [f"  {name}" for name, tool in tools.items()
                   if query in name.lower() or query in (tool.description or "").lower()]
        if not matches:
            return [TextContent(type="text", text=f"No tools matching '{args['query']}'")]
        return [TextContent(type="text", text=f"Found {len(matches)}:\n" + "\n".join(matches))]

    async def _hub_refresh(self, args):
        for name, connector in self._connectors.items():
            if connector.is_connected:
                await connector.discover_tools()
        await self.registry.discover_all()
        return [TextContent(type="text", text=f"Refreshed. {len(self.registry.get_all_tools())} tools available.")]

    async def _hub_stats(self, args):
        since = args.get("since_hours")
        stats = await self.db.get_stats(since)
        total = await self.db.get_total_calls(since)
        if not stats:
            return [TextContent(type="text", text="No usage data yet")]
        lines = [f"Total calls: {total}\n"]
        for s in stats[:20]:
            lines.append(f"  {s['server_name']}/{s['tool_name']}: {s['total_calls']} calls, avg {s['avg_duration_ms']:.0f}ms")
        return [TextContent(type="text", text="\n".join(lines))]

    async def _hub_stats_detailed(self, args):
        calls = await self.db.get_call_history(
            limit=args.get("limit", 50), since_hours=args.get("since_hours"),
            server_name=args.get("server"), status=args.get("status"),
        )
        if not calls:
            return [TextContent(type="text", text="No calls found")]
        lines = [f"  #{c['id']} [{c['status']}] {c['server_name']}/{c['tool_name']} {c['duration_ms']:.0f}ms" for c in calls]
        return [TextContent(type="text", text=f"Call history ({len(calls)}):\n" + "\n".join(lines))]

    async def _hub_top_tools(self, args):
        stats = await self.db.get_stats()
        limit = args.get("limit", 10)
        if not stats:
            return [TextContent(type="text", text="No usage data yet")]
        lines = [f"  {s['server_name']}/{s['tool_name']}: {s['total_calls']} calls" for s in stats[:limit]]
        return [TextContent(type="text", text=f"Top {limit} tools:\n" + "\n".join(lines))]

    async def _hub_error_summary(self, args):
        errors = await self.db.get_error_summary(args.get("since_hours", 24))
        if not errors:
            return [TextContent(type="text", text="No errors in the last 24h")]
        total = sum(e["count"] for e in errors)
        lines = [f"{total} errors total:"]
        for e in errors[:10]:
            msg = (e["error_message"] or "unknown")[:60]
            lines.append(f"  {e['count']}x: {msg}")
        return [TextContent(type="text", text="\n".join(lines))]

    async def _hub_session_stats(self, args):
        return [TextContent(type="text", text=json.dumps(self.session.get_stats(), indent=2))]

    async def _hub_slow_tools(self, args):
        slow = await self.db.get_slow_tools(args.get("limit", 10))
        if not slow:
            return [TextContent(type="text", text="No usage data yet")]
        lines = [f"  {s['server_name']}/{s['tool_name']}: avg {s['avg_duration_ms']:.0f}ms ({s['total_calls']} calls)"
                 for s in slow if s.get("avg_duration_ms")]
        return [TextContent(type="text", text="Slowest tools:\n" + "\n".join(lines) if lines else "No data")]

    async def _hub_server_info(self, args):
        name = args["name"]
        connector = self._connectors.get(name)
        if not connector:
            return [TextContent(type="text", text=f"Server '{name}' not found")]
        status = self.health.get_status().get(name, {})
        info = (
            f"Server: {name}\nConnected: {connector.is_connected}\n"
            f"Transport: {connector.transport}\nTools: {len(connector.tools)}\n"
            f"Restarts: {connector.restart_count}\nStatus: {status.get('status', 'unknown')}"
        )
        return [TextContent(type="text", text=info)]

    async def _hub_enable_server(self, args):
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

    async def _hub_disable_server(self, args):
        name = args["name"]
        connector = self._connectors.get(name)
        if not connector:
            return [TextContent(type="text", text=f"Server '{name}' not found")]
        await connector.disconnect()
        await self.registry.discover_all()
        return [TextContent(type="text", text=f"Server '{name}' disabled")]

    async def _hub_restart_server(self, args):
        name = args["name"]
        success = await self.autorun.restart_server(name)
        if success:
            await self.registry.discover_all()
            return [TextContent(type="text", text=f"Server '{name}' restarted")]
        return [TextContent(type="text", text=f"Failed to restart '{name}'")]

    async def _hub_server_logs(self, args):
        name = args["name"]
        logs = await self.db.get_health_history(name, args.get("limit", 50))
        if not logs:
            return [TextContent(type="text", text=f"No logs for '{name}'")]
        from datetime import datetime
        lines = [f"  {datetime.fromtimestamp(l['timestamp']).strftime('%H:%M:%S')}: {l['status']} (latency: {l.get('latency_ms', '?')}ms)"
                 for l in logs[:20]]
        return [TextContent(type="text", text=f"Logs for {name}:\n" + "\n".join(lines))]

    async def _hub_quiet_on(self, args):
        target = args["target"]
        duration = args.get("duration")
        scope = args.get("scope", "tool")
        if scope == "server":
            self.quiet.quiet_server(target, duration)
        else:
            self.quiet.quiet_tool(target, duration)
        dur_text = f" for {duration}s" if duration else " indefinitely"
        return [TextContent(type="text", text=f"'{target}' quieted{dur_text}")]

    async def _hub_quiet_off(self, args):
        target = args.get("target", "all")
        if target == "all":
            self.quiet.unquiet_all()
            return [TextContent(type="text", text="All tools/servers re-enabled")]
        if self.quiet.unquiet_tool(target) or self.quiet.unquiet_server(target):
            return [TextContent(type="text", text=f"'{target}' re-enabled")]
        return [TextContent(type="text", text=f"'{target}' was not quieted")]

    async def _hub_quiet_status(self, args):
        status = self.quiet.get_status()
        if not status["tools"] and not status["servers"]:
            return [TextContent(type="text", text="Nothing is currently quieted")]
        lines = [f"  tool: {name} ({remaining}s remaining)" for name, remaining in status["tools"].items()]
        lines += [f"  server: {name} ({remaining}s remaining)" for name, remaining in status["servers"].items()]
        return [TextContent(type="text", text="Quieted:\n" + "\n".join(lines))]

    async def _hub_alias_set(self, args):
        tool_name = args["tool"]
        alias = args["alias"]
        result = self.registry.get_tool(tool_name)
        if not result:
            return [TextContent(type="text", text=f"Tool '{tool_name}' not found")]
        server_name, original = result
        self.alias_manager.set_alias(server_name, original, alias)
        await self.registry.discover_all()
        return [TextContent(type="text", text=f"Alias set: {alias} -> {tool_name}")]

    async def _hub_alias_remove(self, args):
        alias = args["alias"]
        if self.alias_manager.remove_alias(alias):
            await self.registry.discover_all()
            return [TextContent(type="text", text=f"Alias '{alias}' removed")]
        return [TextContent(type="text", text=f"Alias '{alias}' not found")]

    async def _hub_alias_list(self, args):
        aliases = self.alias_manager.list_aliases()
        if not aliases:
            return [TextContent(type="text", text="No aliases configured")]
        lines = [f"  {alias} -> {server}/{tool}" for alias, (server, tool) in aliases.items()]
        return [TextContent(type="text", text="Aliases:\n" + "\n".join(lines))]

    async def _hub_replay(self, args):
        return await self.replay.replay_last(args.get("count", 5))

    async def _hub_replay_one(self, args):
        return await self.replay.replay_one(args["id"])

    async def _hub_config_reload(self, args):
        try:
            self.config.load()
            self.alias_manager.load_from_config(self.config.servers)
            await self.registry.discover_all()
            return [TextContent(type="text", text="Config reloaded successfully")]
        except Exception as e:
            return [TextContent(type="text", text=f"Config reload failed: {e}")]

    async def _hub_config_show(self, args):
        return [TextContent(type="text", text=json.dumps(self.config.data, indent=2, default=str))]

    async def _hub_health_history(self, args):
        logs = await self.db.get_health_history(args.get("server"), args.get("limit", 50))
        if not logs:
            return [TextContent(type="text", text="No health data")]
        from datetime import datetime
        lines = [f"  {datetime.fromtimestamp(l['timestamp']).strftime('%H:%M:%S')} {l['server_name']}: {l['status']}" for l in logs[:20]]
        return [TextContent(type="text", text="\n".join(lines))]

    async def _hub_export_stats(self, args):
        data = await self.db.export_stats()
        return [TextContent(type="text", text=data)]

    # ── Cross-server composition ───────────────────────────────────────

    async def _hub_compose(self, args):
        """Chain multiple tool calls. Supports {{step_N.output}} references."""
        import re
        steps = args.get("steps", [])
        if not steps:
            return [TextContent(type="text", text="No steps provided")]

        results = []
        for i, step in enumerate(steps):
            tool_name = step["tool"]
            step_args = step.get("arguments", {})

            # Resolve references to previous step outputs in string values
            def resolve_refs(obj):
                if isinstance(obj, str):
                    def replacer(match):
                        ref_idx = int(match.group(1)) - 1
                        if 0 <= ref_idx < len(results):
                            return results[ref_idx]
                        return match.group(0)
                    return re.sub(r'\{\{step_(\d+)\.output\}\}', replacer, obj)
                elif isinstance(obj, dict):
                    return {k: resolve_refs(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [resolve_refs(v) for v in obj]
                return obj

            step_args = resolve_refs(step_args)

            try:
                result = await self.router.route_call(tool_name, step_args)
                output = "\n".join(c.text for c in result if hasattr(c, "text"))
                results.append(output)
            except Exception as e:
                return [TextContent(type="text",
                    text=f"Step {i+1} ({tool_name}) failed: {e}\nCompleted {i}/{len(steps)} steps")]

        summary = "\n---\n".join(f"Step {i+1} ({steps[i]['tool']}):\n{r}" for i, r in enumerate(results))
        return [TextContent(type="text", text=f"Workflow completed ({len(steps)} steps):\n\n{summary}")]

    async def _hub_compose_template(self, args):
        action = args["action"]
        templates = self._workflow_templates
        if action == "save":
            name = args["name"]
            templates[name] = args.get("steps", [])
            self._workflow_templates = templates
            return [TextContent(type="text", text=f"Template '{name}' saved ({len(templates[name])} steps)")]
        elif action == "load":
            name = args["name"]
            steps = templates.get(name)
            if not steps:
                return [TextContent(type="text", text=f"Template '{name}' not found")]
            return await self._hub_compose({"steps": steps})
        elif action == "list":
            if not templates:
                return [TextContent(type="text", text="No templates saved")]
            lines = [f"  {name}: {len(steps)} steps" for name, steps in templates.items()]
            return [TextContent(type="text", text="Templates:\n" + "\n".join(lines))]
        elif action == "delete":
            name = args["name"]
            if templates.pop(name, None) is not None:
                self._workflow_templates = templates
                return [TextContent(type="text", text=f"Template '{name}' deleted")]
            return [TextContent(type="text", text=f"Template '{name}' not found")]
        return [TextContent(type="text", text=f"Unknown action: {action}")]

    # ── Stateful sessions ──────────────────────────────────────────────

    async def _hub_session_begin(self, args):
        import uuid
        sid = str(uuid.uuid4())[:12]
        sessions = self._stateful_sessions
        sessions[sid] = {
            "name": args["name"],
            "context": args.get("context", {}),
            "history": [],
            "created": __import__("time").time(),
        }
        self._stateful_sessions = sessions
        return [TextContent(type="text", text=json.dumps({"session_id": sid, "name": args["name"]}, indent=2))]

    async def _hub_session_step(self, args):
        sid = args["session_id"]
        sessions = self._stateful_sessions
        session = sessions.get(sid)
        if not session:
            return [TextContent(type="text", text=f"Session '{sid}' not found. Use hub_session_begin first.")]
        tool_name = args["tool"]
        step_args = args.get("arguments", {})

        # Inject session context into arguments
        if "__context__" not in step_args:
            step_args["__context__"] = session["context"]

        try:
            result = await self.router.route_call(tool_name, step_args)
            output = "\n".join(c.text for c in result if hasattr(c, "text"))
            session["history"].append({"tool": tool_name, "arguments": step_args, "output": output})
            return [TextContent(type="text",
                text=f"Session '{session['name']}' step {len(session['history'])} ({tool_name}):\n{output}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Session step failed: {e}")]

    # ── Cost estimation ────────────────────────────────────────────────

    async def _hub_cost_estimate(self, args):
        tool_name = args["tool"]
        cost = self.router.cost_registry.get(tool_name)
        if not cost:
            return [TextContent(type="text", text=f"No cost data for '{tool_name}'. Use hub_cost_register to set it.")]
        lines = [
            f"Tool: {tool_name}",
            f"Type: {cost['cost_type']}",
            f"Value: ${cost['cost_value']:.4f}",
            f"Description: {cost.get('description', 'N/A')}",
        ]
        if cost["cost_type"] == "free":
            lines.append("Estimate: $0.00 (free)")
        elif cost["cost_type"] == "flat" or cost["cost_type"] == "per_call":
            lines.append(f"Estimate: ${cost['cost_value']:.4f} per call")
        return [TextContent(type="text", text="\n".join(lines))]

    async def _hub_cost_register(self, args):
        tool_name = args["tool"]
        self.router.cost_registry[tool_name] = {
            "cost_type": args["cost_type"],
            "cost_value": args.get("cost_value", 0.0),
            "description": args.get("description", ""),
        }
        return [TextContent(type="text", text=f"Cost registered for '{tool_name}': {args['cost_type']} ${args.get('cost_value', 0):.4f}")]

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def initialize(self):
        """Initialize all components."""
        logger.info(f"Initializing MCP Hub: {self.config.hub.get('name')}")

        # Init DB
        await self.db.init()
        tracking = self.config.tracking
        self.router.set_tracking(tracking.get("enabled", True), tracking.get("track_params", False))

        # Load aliases from config
        self.alias_manager.load_from_config(self.config.servers)

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

            success = await connector.connect()
            if success:
                await connector.discover_tools()
                logger.info(f"[{name}] Ready ({len(connector.tools)} tools)")
            else:
                logger.warning(f"[{name}] Failed to connect")

        # Discover all tools
        await self.registry.discover_all()
        self._initialized = True
        logger.info(f"Hub ready: {len(self.registry.get_all_tools())} tools available")

        # Start background tasks
        await self.health.start()
        if self.config.hotreload.get("enabled", True):
            self.hotreload.on_reload(self._on_config_reload)
            await self.hotreload.start()

    async def _on_config_reload(self):
        """Handle config hot-reload — detect added/removed servers."""
        old_servers = set(self._connectors.keys())
        new_servers = set(self.config.servers.keys())

        # Remove servers no longer in config
        for name in old_servers - new_servers:
            logger.info(f"[{name}] Removing (no longer in config)")
            await self._connectors[name].disconnect()
            del self._connectors[name]
            self.registry._connectors.pop(name, None)
            self.router._connectors.pop(name, None)
            self.health._connectors.pop(name, None)
            self.health._server_status.pop(name, None)
            self.autorun._connectors.pop(name, None)
            self.autorun._server_configs.pop(name, None)
            self.autorun._dependencies.pop(name, None)

        # Add new servers
        for name in new_servers - old_servers:
            server_cfg = self.config.servers[name]
            if not server_cfg.get("enabled", True):
                continue
            logger.info(f"[{name}] Adding new server")
            connector = ServerConnector(name, server_cfg)
            self._connectors[name] = connector
            self.registry.register_connector(name, connector)
            self.router.register_connector(name, connector)
            self.health.register_connector(name, connector)
            self.autorun.register_server(name, connector, server_cfg)
            if await connector.connect():
                await connector.discover_tools()

        # Re-register existing connectors (config may have changed)
        for name in old_servers & new_servers:
            server_cfg = self.config.servers[name]
            self.autorun.register_server(name, self._connectors[name], server_cfg)

        # Update aliases and re-discover
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

    try:
        async with stdio_server() as (read_stream, write_stream):
            await hub.server.run(read_stream, write_stream, hub.server.create_initialization_options())
    finally:
        await hub.shutdown()


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "mcp_hub.yaml"
    asyncio.run(run(config_path))


if __name__ == "__main__":
    main()
