# MCP Hub

A meta-MCP server that aggregates multiple backend MCP servers into one unified interface. Your host agent (Claude, Codex, OpenClaw) sees only **one** MCP server, but gets tools from **all** of them.

## Quick Start

```bash
git clone https://github.com/factspark23-hash/mcp-handler.git
cd mcp-handler
pip install -e .
cp config.example.yaml mcp_hub.yaml
# Edit mcp_hub.yaml with your servers
```

Add to your host agent config (Claude Desktop example):

```json
{
  "mcpServers": {
    "mcp-hub": {
      "command": "python3",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/mcp-hub"
    }
  }
}
```

Restart your host agent. All tools from all servers are available.

## What It Does

- **34 management tools** for complete control through your host agent
- **Cross-server composition** — chain tools from different servers in one call
- **Stateful sessions** — multi-step workflows with context carryover
- **Cost estimation** — register and check tool costs before calling
- **Usage tracking** — SQLite-backed per-call logging, stats, error summaries
- **Tool aliases** — short names like `fs_read` instead of `filesystem__read_file`
- **Smart namespacing** — auto-prefixes only when tool names conflict
- **Quiet mode** — temporarily disable tools/servers without editing config
- **Auto-restart** — crashed servers restart automatically
- **Call replay** — replay previous calls for debugging
- **Config hot-reload** — edit config, add/remove servers without restart
- **Per-session stats** — track what happens in each session
- **Zero extra infrastructure** — just Python + SQLite

## Config

```yaml
hub:
  name: "My MCP Hub"
  database: "data/hub.db"
  health_check_interval: 30    # seconds between health pings
  auto_restart: true
  max_restart_attempts: 3
  restart_delay: 5             # seconds between restart attempts

servers:
  filesystem:
    transport: "stdio"
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    enabled: true
    aliases:
      read_file: "fs_read"
      write_file: "fs_write"
      list_directory: "fs_ls"
    depends_on: []             # server names that must be up first

  sqlite:
    transport: "stdio"
    command: "uvx"
    args: ["mcp-server-sqlite", "--db", "/tmp/app.db"]
    enabled: true
    aliases:
      query: "db_query"
    depends_on: [filesystem]

namespacing:
  mode: "auto"                 # auto | always | never
  # auto: prefix only when multiple servers have same tool name

tracking:
  enabled: true
  max_records: 100000
  track_params: false          # log tool call parameters (privacy off by default)
  session_tracking: true

hotreload:
  enabled: true
  watch_interval: 5            # seconds between config file checks
```

### Environment Variables

Use `${VAR}` or `$VAR` in config values:

```yaml
servers:
  github:
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

## Tools Reference

### Status & Discovery (5 tools)

| Tool | Description |
|------|-------------|
| `hub_status` | Hub and all servers status |
| `hub_tools` | List all tools. Optional: `server` (filter), `search` (text search) |
| `hub_tool_info` | Detailed info about a tool: schema, server, alias, cost |
| `hub_search_tools` | Search tools by name or description |
| `hub_refresh` | Re-discover tools from all servers |

### Usage Analytics (6 tools)

| Tool | Description |
|------|-------------|
| `hub_stats` | Aggregated stats. Optional: `since_hours` |
| `hub_stats_detailed` | Filtered call history. Optional: `limit`, `since_hours`, `server`, `status` |
| `hub_top_tools` | Most used tools. Optional: `limit` |
| `hub_error_summary` | Recent errors grouped by message. Optional: `since_hours` |
| `hub_session_stats` | Current session stats (calls, success rate, avg duration) |
| `hub_slow_tools` | Slowest tools by average duration. Optional: `limit` |

### Server Management (5 tools)

| Tool | Description |
|------|-------------|
| `hub_server_info` | Server details: connected, transport, tool count, restarts |
| `hub_enable_server` | Enable and connect a disabled server |
| `hub_disable_server` | Disconnect a server |
| `hub_restart_server` | Restart a server (disconnect + reconnect + rediscover) |
| `hub_server_logs` | Server health history. Optional: `limit` |

### Tool Control (6 tools)

| Tool | Description |
|------|-------------|
| `hub_quiet_on` | Temporarily disable. Args: `target`, `duration` (seconds, omit for indefinite), `scope` (tool/server) |
| `hub_quiet_off` | Re-enable. Args: `target` (name or "all") |
| `hub_quiet_status` | Show currently quieted items |
| `hub_alias_set` | Set alias. Args: `tool` (full name), `alias` (short name) |
| `hub_alias_remove` | Remove alias. Args: `alias` |
| `hub_alias_list` | List all aliases |

### Cross-Server Composition (2 tools)

| Tool | Description |
|------|-------------|
| `hub_compose` | Chain tools. Args: `steps` — array of `{tool, arguments}`. Use `{{step_N.output}}` to pipe results |
| `hub_compose_template` | Save/load/run templates. Args: `action` (save/load/list/delete), `name`, `steps` |

Example composition:

```json
{
  "steps": [
    {"tool": "fs_read", "arguments": {"path": "data.csv"}},
    {"tool": "db_query", "arguments": {"sql": "INSERT INTO imports VALUES ('{{step_1.output}}')"}}
  ]
}
```

### Stateful Sessions (2 tools)

| Tool | Description |
|------|-------------|
| `hub_session_begin` | Start session. Args: `name`, `context` (optional initial data) |
| `hub_session_step` | Execute step. Args: `session_id`, `tool`, `arguments`. Context auto-injected as `__context__` |

### Cost Estimation (2 tools)

| Tool | Description |
|------|-------------|
| `hub_cost_register` | Register cost. Args: `tool`, `cost_type` (free/flat/per_call/per_token/per_byte), `cost_value` (USD), `description` |
| `hub_cost_estimate` | Check cost. Args: `tool` |

### Advanced (6 tools)

| Tool | Description |
|------|-------------|
| `hub_replay` | Replay last N calls. Args: `count` |
| `hub_replay_one` | Replay specific call. Args: `id` |
| `hub_config_reload` | Reload config file |
| `hub_config_show` | Show current config as JSON |
| `hub_health_history` | Health history. Optional: `server`, `limit` |
| `hub_export_stats` | Export all stats as JSON |

## How It Works

```
User: "read the config file"
  │
  ▼
Claude decides: call tool "fs_read" (alias)
  │
  ▼
MCP Hub receives call
  ├── Check quiet mode → not quieted
  ├── Registry: "fs_read" → server="filesystem", original="read_file"
  ├── Router: get connector for "filesystem"
  ├── connector.call_tool("read_file", {path: "config.yaml"})
  ├── Track: log_call(filesystem, fs_read, 45ms, success)
  │
  ▼
Return response to Claude → Claude tells user
```

## Project Structure

```
mcp-hub/
├── pyproject.toml           # Package config + dependencies
├── config.example.yaml      # Example config
├── README.md
├── src/
│   ├── server.py            # Main MCP Server (34 hub_* tools + dispatch)
│   ├── router.py            # Routes calls to backends (retry, tracking)
│   ├── registry.py          # Tool discovery + namespacing + aliases
│   ├── connector.py         # MCP server connections (stdio/HTTP)
│   ├── db.py                # SQLite layer (4 tables)
│   ├── config.py            # YAML config loader + validation
│   ├── aliases.py           # Bidirectional tool alias mapping
│   ├── namespacing.py       # Auto/prefix/never namespacing modes
│   ├── quiet.py             # Temporary tool/server disabling
│   ├── session.py           # Per-session call statistics
│   ├── health.py            # Periodic health checks + uptime
│   ├── autorun.py           # Auto-restart with dependency ordering
│   ├── replay.py            # Replay past tool calls
│   └── hotreload.py         # Config file watching + live reload
├── data/                    # SQLite database (created on first run)
└── tests/
    └── test_core.py         # 19 tests covering all core modules
```

## Running Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Protocol | MCP SDK 1.6+ |
| Config | YAML (PyYAML) |
| Storage | SQLite (aiosqlite) |
| Async | asyncio |
| HTTP | httpx (for remote MCP servers) |

## License

MIT
