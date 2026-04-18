"""Tool registry - discovers tools from all servers, manages namespacing and aliases."""
import logging
from mcp.types import Tool
from .namespacing import NamespaceManager
from .aliases import AliasManager
from .connector import ServerConnector

logger = logging.getLogger("mcp_hub.registry")


class Registry:
    def __init__(self, namespace_manager: NamespaceManager, alias_manager: AliasManager):
        self.ns = namespace_manager
        self.aliases = alias_manager
        # server_name -> ServerConnector
        self._connectors: dict[str, ServerConnector] = {}
        # final_tool_name -> Tool object
        self._tools: dict[str, Tool] = {}
        # final_tool_name -> (server_name, original_tool_name)
        self._tool_map: dict[str, tuple[str, str]] = {}

    def register_connector(self, name: str, connector: ServerConnector):
        self._connectors[name] = connector

    async def discover_all(self) -> dict[str, Tool]:
        """Discover tools from all connected servers."""
        server_tools = {}
        server_tool_objects: dict[str, dict[str, Tool]] = {}

        for name, connector in self._connectors.items():
            if not connector.is_connected:
                continue
            tools = await connector.discover_tools()
            tool_names = [t.name for t in tools]
            server_tools[name] = tool_names
            server_tool_objects[name] = {t.name: t for t in tools}

        # Build namespaced names
        self._tool_map = self.ns.build_names(server_tools)

        # Apply aliases: for each server's aliases, add alias entries
        for server_name, connector in self._connectors.items():
            for final_name, (sname, original_name) in list(self._tool_map.items()):
                if sname == server_name:
                    alias = self.aliases.get_alias(server_name, original_name)
                    if alias and alias not in self._tool_map:
                        self._tool_map[alias] = (server_name, original_name)

        # Build tool objects with final names
        self._tools.clear()
        for final_name, (server_name, original_name) in self._tool_map.items():
            tool_obj = server_tool_objects.get(server_name, {}).get(original_name)
            if tool_obj:
                # Create a copy with the final name
                self._tools[final_name] = Tool(
                    name=final_name,
                    description=tool_obj.description or "",
                    inputSchema=tool_obj.inputSchema or {"type": "object", "properties": {}},
                )

        logger.info(f"Registry: {len(self._tools)} tools from {len(server_tools)} servers")
        return dict(self._tools)

    def get_tool(self, name: str) -> tuple[str, str] | None:
        """Get (server_name, original_tool_name) for a tool name."""
        return self._tool_map.get(name)

    def get_all_tools(self) -> dict[str, Tool]:
        return dict(self._tools)

    def has_tool(self, name: str) -> bool:
        return name in self._tool_map

    def get_server_tool_count(self, server_name: str) -> int:
        return sum(1 for sname, _ in self._tool_map.values() if sname == server_name)
