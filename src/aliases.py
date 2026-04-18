"""Tool aliasing - user-defined short names for tools."""


class AliasManager:
    def __init__(self):
        # alias -> (server_name, original_tool_name)
        self._alias_to_tool: dict[str, tuple[str, str]] = {}
        # (server_name, original_tool_name) -> alias
        self._tool_to_alias: dict[tuple[str, str], str] = {}

    def load_from_config(self, servers_config: dict):
        for server_name, server_cfg in servers_config.items():
            aliases = server_cfg.get("aliases", {})
            for original, alias in aliases.items():
                self.set_alias(server_name, original, alias)

    def set_alias(self, server_name: str, original_tool: str, alias: str):
        key = (server_name, original_tool)
        # Remove old alias if exists
        old_alias = self._tool_to_alias.pop(key, None)
        if old_alias:
            self._alias_to_tool.pop(old_alias, None)
        self._alias_to_tool[alias] = (server_name, original_tool)
        self._tool_to_alias[key] = alias

    def remove_alias(self, alias: str) -> bool:
        if alias not in self._alias_to_tool:
            return False
        key = self._alias_to_tool.pop(alias)
        self._tool_to_alias.pop(key, None)
        return True

    def resolve(self, name: str) -> tuple[str, str] | None:
        """Resolve an alias to (server_name, original_tool_name). Returns None if not an alias."""
        return self._alias_to_tool.get(name)

    def get_alias(self, server_name: str, original_tool: str) -> str | None:
        return self._tool_to_alias.get((server_name, original_tool))

    def list_aliases(self) -> dict[str, tuple[str, str]]:
        return dict(self._alias_to_tool)

    def has_alias(self, alias: str) -> bool:
        return alias in self._alias_to_tool
