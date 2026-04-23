<div align="center">

# 🔌 MCP Hub

**One server to rule all your MCP tools.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP SDK](https://img.shields.io/badge/MCP_SDK-1.6+-green.svg)](https://github.com/modelcontextprotocol/python-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-19%20passed-brightgreen.svg)](#running-tests)

A **meta-MCP server** that aggregates multiple backend MCP servers into one unified interface.

Your host agent (Claude, Codex, OpenClaw) sees only **one** MCP server, but gets tools from **all** of them.

[Quick Start](#quick-start) • [What It Does](#what-it-does) • [Config](#config) • [Tools Reference](#tools-reference) • [Contributing](#contributing)

</div>

---

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

Restart your host agent. All tools from all servers are available. ✅

---

## What It Does

<table>
<tr>
<td width="50%">

### 🧠 Smart Management
- **34 management tools** for complete control
- **Smart namespacing** — auto-prefixes only when tool names conflict
- **Tool aliases** — `fs_read` instead of `filesystem__read_file`
- **Quiet mode** — temporarily disable tools/servers
- **Config hot-reload** — edit config without restart

</td>
<td width="50%">

### 🔗 Cross-Server Power
- **Cross-server composition** — chain tools from different servers
- **Stateful sessions** — multi-step workflows with context
- **Cost estimation** — check costs before calling
- **Auto-restart** — crashed servers restart automatically
- **Call replay** — replay past calls for debugging

</td>
</tr>
<tr>
<td width="50%">

### 📊 Analytics & Tracking
- **Usage tracking** — SQLite-backed per-call logging
- **Per-session stats** — track success rates, durations
- **Error summaries** — grouped error analysis
- **Slow tool detection** — find bottlenecks
- **Export stats** — JSON export for analysis

</td>
<td width="50%">

### 🛡️ Zero Hassle
- **Zero extra infrastructure** — just Python + SQLite
- **Auto health checks** — periodic server pings
- **Dependency ordering** — servers start in correct order
- **Graceful failures** — individual tool errors don't crash hub
- **Environment variable support** — `${VAR}` in config

</td>
</tr>
</table>

---

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
    depends_on: []

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

tracking:
  enabled: true
  max_records: 100000
  track_params: false          # privacy: don't log params by default
  session_tracking: true

hotreload:
  enabled: true
  watch_interval: 5
```

### Environment Variables

```yaml
servers:
  github:
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

---

## Tools Reference

<details>
<summary><b>Status & Discovery</b> (5 tools)</summary>

| Tool | Description |
|------|-------------|
| `hub_status` | Hub and all servers status |
| `hub_tools` | List all tools. Optional: `server`, `search` |
| `hub_tool_info` | Detailed info: schema, server, alias, cost |
| `hub_search_tools` | Search tools by name or description |
| `hub_refresh` | Re-discover tools from all servers |

</details>

<details>
<summary><b>Usage Analytics</b> (6 tools)</summary>

| Tool | Description |
|------|-------------|
| `hub_stats` | Aggregated stats. Optional: `since_hours` |
| `hub_stats_detailed` | Filtered call history |
| `hub_top_tools` | Most used tools |
| `hub_error_summary` | Recent errors grouped by message |
| `hub_session_stats` | Current session stats |
| `hub_slow_tools` | Slowest tools by average duration |

</details>

<details>
<summary><b>Server Management</b> (5 tools)</summary>

| Tool | Description |
|------|-------------|
| `hub_server_info` | Server details: connected, transport, tool count |
| `hub_enable_server` | Enable and connect a disabled server |
| `hub_disable_server` | Disconnect a server |
| `hub_restart_server` | Restart a server |
| `hub_server_logs` | Server health history |

</details>

<details>
<summary><b>Tool Control</b> (6 tools)</summary>

| Tool | Description |
|------|-------------|
| `hub_quiet_on` | Temporarily disable tools/servers |
| `hub_quiet_off` | Re-enable |
| `hub_quiet_status` | Show currently quieted items |
| `hub_alias_set` | Set alias for a tool |
| `hub_alias_remove` | Remove alias |
| `hub_alias_list` | List all aliases |

</details>

<details>
<summary><b>Cross-Server Composition</b> (2 tools)</summary>

| Tool | Description |
|------|-------------|
| `hub_compose` | Chain tools from different servers |
| `hub_compose_template` | Save/load/run composition templates |

Example:

```json
{
  "steps": [
    {"tool": "fs_read", "arguments": {"path": "data.csv"}},
    {"tool": "db_query", "arguments": {"sql": "INSERT INTO imports VALUES ('{{step_1.output}}')"}}
  ]
}
```

</details>

<details>
<summary><b>Stateful Sessions</b> (2 tools)</summary>

| Tool | Description |
|------|-------------|
| `hub_session_begin` | Start session with optional context |
| `hub_session_step` | Execute step with auto-injected context |

</details>

<details>
<summary><b>Cost Estimation</b> (2 tools)</summary>

| Tool | Description |
|------|-------------|
| `hub_cost_register` | Register cost for a tool |
| `hub_cost_estimate` | Check cost before calling |

</details>

<details>
<summary><b>Advanced</b> (6 tools)</summary>

| Tool | Description |
|------|-------------|
| `hub_replay` | Replay last N calls |
| `hub_replay_one` | Replay specific call by ID |
| `hub_config_reload` | Reload config file |
| `hub_config_show` | Show current config as JSON |
| `hub_health_history` | Health history per server |
| `hub_export_stats` | Export all stats as JSON |

</details>

---

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

---

## Project Structure

```
mcp-hub/
├── pyproject.toml           # Package config + dependencies
├── config.example.yaml      # Example config
├── src/
│   ├── server.py            # Main MCP Server (34 hub_* tools)
│   ├── router.py            # Routes calls to backends
│   ├── registry.py          # Tool discovery + namespacing
│   ├── connector.py         # MCP server connections (stdio/HTTP)
│   ├── db.py                # SQLite layer (4 tables)
│   ├── config.py            # YAML config loader + validation
│   ├── aliases.py           # Bidirectional alias mapping
│   ├── namespacing.py       # Auto/prefix/never modes
│   ├── quiet.py             # Temporary tool/server disabling
│   ├── session.py           # Per-session statistics
│   ├── health.py            # Health checks + uptime
│   ├── autorun.py           # Auto-restart with dependency ordering
│   ├── replay.py            # Replay past tool calls
│   └── hotreload.py         # Config file watching
├── data/                    # SQLite database (auto-created)
└── tests/
    ├── test_core.py         # 19 unit tests
    └── test_integration.py  # Integration tests
```

---

## Running Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v

# 19/19 tests pass ✅
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Protocol | MCP SDK 1.6+ |
| Config | YAML (PyYAML) |
| Storage | SQLite (aiosqlite) |
| Async | asyncio |
| HTTP | httpx |

---

## Contributing

Contributions welcome! Here's how:

1. **Fork** this repo
2. **Create** a feature branch (`git checkout -b feat/amazing-feature`)
3. **Commit** your changes (`git commit -m 'feat: add amazing feature'`)
4. **Push** to the branch (`git push origin feat/amazing-feature`)
5. **Open** a Pull Request

### Ideas for contributions:
- [ ] WebSocket transport support
- [ ] Tool usage dashboard (web UI)
- [ ] Rate limiting per tool
- [ ] Authentication layer
- [ ] Docker support
- [ ] More transport types (SSE, gRPC)

---

## License

MIT — use it however you want.

---

<div align="center">

**Built with ❤️ for the MCP community**

⭐ Star this repo if you find it useful!

</div>
