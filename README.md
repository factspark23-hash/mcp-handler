# MCP Hub

A meta-MCP server that aggregates multiple backend MCP servers into one unified interface. Your host agent (Claude, Codex, OpenClaw) sees only **one** MCP server, but gets tools from **all** of them.

## What It Does

- **28 management tools** for complete control through your host agent
- **Cross-server composition** — chain tools from different servers in one call (`hub_compose`)
- **Stateful sessions** — multi-step workflows with context (`hub_session_begin` / `hub_session_step`)
- **Cost estimation** — register and check tool costs before calling (`hub_cost_register` / `hub_cost_estimate`)
- **Usage tracking** with SQLite (per-call logging, stats, error summaries)
- **Tool aliases** — short names like `fs_read` instead of `filesystem__read_file`
- **Smart namespacing** — auto-prefixes only when tool names conflict
- **Quiet mode** — temporarily disable tools/servers without editing config
- **Auto-restart** — crashed servers restart automatically with dependency ordering
- **Call replay** — replay previous calls for debugging
- **Config hot-reload** — edit config, add/remove servers, changes apply without restart
- **Per-session stats** — track what happens in each session
- **Zero extra infrastructure** — just Python + SQLite

## Quick Start

### 1. Install

```bash
pip install mcp-hub
```

Or from source:

```bash
git clone https://github.com/factspark23-hash/mcp-handler.git
cd mcp-handler
pip install -e .
```

### 2. Configure

```bash
cp config.example.yaml mcp_hub.yaml
# Edit mcp_hub.yaml with your servers
```

### 3. Add to Your Host Agent

**Claude Desktop** (`claude_desktop_config.json`):

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

Restart Claude. All tools are available.

## Config Example

```yaml
hub:
  name: "My MCP Hub"
  database: "data/hub.db"
  health_check_interval: 30
  auto_restart: true
  max_restart_attempts: 3

servers:
  filesystem:
    transport: "stdio"
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/docs"]
    enabled: true
    aliases:
      read_file: "fs_read"
      write_file: "fs_write"

  sqlite:
    transport: "stdio"
    command: "uvx"
    args: ["mcp-server-sqlite", "--db", "/tmp/app.db"]
    enabled: true
    aliases:
      query: "db_query"
    depends_on: [filesystem]
```

## The 28 Hub Tools

### Status & Discovery
| Tool | What it does |
|------|-------------|
| `hub_status` | Hub + all servers status |
| `hub_tools` | List all tools (filterable) |
| `hub_tool_info` | Detailed tool info |
| `hub_search_tools` | Search by name/description |
| `hub_refresh` | Re-discover tools |

### Usage Analytics
| Tool | What it does |
|------|-------------|
| `hub_stats` | Aggregated stats |
| `hub_stats_detailed` | Filtered call history |
| `hub_top_tools` | Most used tools |
| `hub_error_summary` | Recent errors |
| `hub_session_stats` | Current session stats |
| `hub_slow_tools` | Slowest tools |

### Server Management
| Tool | What it does |
|------|-------------|
| `hub_server_info` | Server details |
| `hub_enable_server` | Enable server |
| `hub_disable_server` | Disable server |
| `hub_restart_server` | Restart server |
| `hub_server_logs` | Server health logs |

### Tool Control
| Tool | What it does |
|------|-------------|
| `hub_quiet_on` | Temporarily disable tools |
| `hub_quiet_off` | Re-enable quieted tools |
| `hub_quiet_status` | Show quiet state |
| `hub_alias_set` | Set tool alias |
| `hub_alias_remove` | Remove alias |
| `hub_alias_list` | List all aliases |

### Advanced
| Tool | What it does |
|------|-------------|
| `hub_replay` | Replay last N calls |
| `hub_replay_one` | Replay specific call |
| `hub_config_reload` | Reload config |
| `hub_config_show` | Show current config |
| `hub_health_history` | Health over time |
| `hub_export_stats` | Export stats as JSON |

### Cross-Server Composition
| Tool | What it does |
|------|-------------|
| `hub_compose` | Chain tools from different servers in one call |
| `hub_compose_template` | Save/load/run workflow templates |

### Stateful Sessions
| Tool | What it does |
|------|-------------|
| `hub_session_begin` | Start a session with context |
| `hub_session_step` | Execute step in session (context auto-injected) |

### Cost Estimation
| Tool | What it does |
|------|-------------|
| `hub_cost_estimate` | Check cost before calling a tool |
| `hub_cost_register` | Register cost metadata for a tool |

## How It Works

```
User: "filesystem mein readme.md read karo"
  |
  v
Claude decides: call tool "fs_read" (alias)
  |
  v
MCP Hub receives call
  +-> Check quiet mode -> NOT quieted
  +-> Registry: "fs_read" -> server="filesystem", original="read_file"
  +-> Router: get connector for "filesystem"
  +-> connector.call_tool("read_file", {path: "readme.md"})
  +-> Track: log_call(filesystem, fs_read, 45ms, success)
  |
  v
Return response to Claude -> Claude tells user
```

## Project Structure

```
mcp-hub/
├── pyproject.toml
├── config.example.yaml
├── mcp_hub.yaml
├── src/
│   ├── server.py       # Main MCP Server (28 hub_* tools)
│   ├── router.py       # Tool call routing
│   ├── registry.py     # Tool discovery
│   ├── connector.py    # MCP connections
│   ├── tracker.py      # (via router/db)
│   ├── health.py       # Health monitoring
│   ├── config.py       # Config loader
│   ├── db.py           # SQLite layer
│   ├── aliases.py      # Tool aliasing
│   ├── namespacing.py  # Smart namespacing
│   ├── session.py      # Per-session stats
│   ├── autorun.py      # Auto-restart
│   ├── replay.py       # Call replay
│   ├── hotreload.py    # Config hot-reload
│   └── quiet.py        # Quiet mode
├── data/
└── tests/
```

## License

MIT
