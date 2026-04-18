"""Smart namespacing - auto-detect conflicts, prefix when needed."""


class NamespaceManager:
    MODES = ("auto", "always", "never")

    def __init__(self, mode: str = "auto"):
        self.mode = mode if mode in self.MODES else "auto"
        # Maps final_name -> (server_name, original_name)
        self._name_map: dict[str, tuple[str, str]] = {}
        # Track which names appear in multiple servers
        self._name_counts: dict[str, int] = {}

    def build_names(self, server_tools: dict[str, list[str]]) -> dict[str, tuple[str, str]]:
        """
        server_tools: {server_name: [tool_name, ...]}
        Returns: {final_name: (server_name, original_name)}
        """
        self._name_map.clear()
        self._name_counts.clear()

        # Count how many servers have each tool name
        for server_name, tools in server_tools.items():
            for tool_name in tools:
                self._name_counts[tool_name] = self._name_counts.get(tool_name, 0) + 1

        # Build final names
        for server_name, tools in server_tools.items():
            for tool_name in tools:
                final_name = self._get_final_name(server_name, tool_name)
                self._name_map[final_name] = (server_name, tool_name)

        return dict(self._name_map)

    def _get_final_name(self, server_name: str, tool_name: str) -> str:
        if self.mode == "always":
            return f"{server_name}__{tool_name}"
        elif self.mode == "never":
            return tool_name
        else:  # auto
            if self._name_counts.get(tool_name, 0) > 1:
                return f"{server_name}__{tool_name}"
            return tool_name

    def resolve(self, final_name: str) -> tuple[str, str] | None:
        """Resolve final tool name to (server_name, original_name)."""
        return self._name_map.get(final_name)

    def get_server_tools(self, server_name: str) -> list[str]:
        return [
            final_name
            for final_name, (sname, _) in self._name_map.items()
            if sname == server_name
        ]
