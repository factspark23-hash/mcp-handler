"""Tests for MCP Hub core modules."""
import asyncio
import pytest
import tempfile
import os

# ── Config ─────────────────────────────────────────────────────────────

from src.config import Config


def test_config_loads_defaults(tmp_path):
    cfg_path = tmp_path / "test.yaml"
    cfg_path.write_text("hub:\n  name: Test\nservers: {}\n")
    c = Config(str(cfg_path))
    data = c.load()
    assert data["hub"]["name"] == "Test"
    assert data["hub"]["log_level"] == "info"  # default
    assert data["namespacing"]["mode"] == "auto"


def test_config_expands_env_vars(tmp_path):
    os.environ["TEST_VAR"] = "hello"
    cfg_path = tmp_path / "test.yaml"
    cfg_path.write_text("servers:\n  test:\n    transport: stdio\n    command: ${TEST_VAR}\n")
    c = Config(str(cfg_path))
    data = c.load()
    assert data["servers"]["test"]["command"] == "hello"


def test_config_validate_stdio_needs_command(tmp_path):
    cfg_path = tmp_path / "test.yaml"
    cfg_path.write_text("servers:\n  bad:\n    transport: stdio\n")
    c = Config(str(cfg_path))
    with pytest.raises(ValueError, match="stdio transport requires 'command'"):
        c.load()


def test_config_detects_changes(tmp_path):
    cfg_path = tmp_path / "test.yaml"
    cfg_path.write_text("hub:\n  name: V1\n")
    c = Config(str(cfg_path))
    c.load()
    assert not c.has_changed()
    import time; time.sleep(0.1)
    cfg_path.write_text("hub:\n  name: V2\n")
    assert c.has_changed()


# ── Aliases ────────────────────────────────────────────────────────────

from src.aliases import AliasManager


def test_aliases_set_and_resolve():
    am = AliasManager()
    am.set_alias("fs", "read_file", "fs_read")
    assert am.resolve("fs_read") == ("fs", "read_file")
    assert am.get_alias("fs", "read_file") == "fs_read"
    assert am.resolve("nope") is None


def test_aliases_remove():
    am = AliasManager()
    am.set_alias("fs", "read_file", "fs_read")
    assert am.remove_alias("fs_read")
    assert am.resolve("fs_read") is None
    assert not am.remove_alias("nope")


def test_aliases_load_from_config():
    am = AliasManager()
    am.load_from_config({
        "fs": {"aliases": {"read_file": "fs_read", "write_file": "fs_write"}},
        "db": {"aliases": {"query": "db_query"}},
    })
    aliases = am.list_aliases()
    assert len(aliases) == 3
    assert aliases["fs_read"] == ("fs", "read_file")


# ── Namespacing ────────────────────────────────────────────────────────

from src.namespacing import NamespaceManager


def test_namespacing_auto_no_conflict():
    ns = NamespaceManager("auto")
    result = ns.build_names({"server_a": ["read", "write"], "server_b": ["query"]})
    assert "read" in result
    assert "query" in result
    assert result["read"] == ("server_a", "read")


def test_namespacing_auto_with_conflict():
    ns = NamespaceManager("auto")
    result = ns.build_names({"server_a": ["query"], "server_b": ["query"]})
    assert "server_a__query" in result
    assert "server_b__query" in result
    assert "query" not in result


def test_namespacing_always():
    ns = NamespaceManager("always")
    result = ns.build_names({"s1": ["tool1"]})
    assert "s1__tool1" in result


# ── Quiet ──────────────────────────────────────────────────────────────

from src.quiet import QuietManager


def test_quiet_tool():
    qm = QuietManager()
    assert not qm.is_quiet("tool1")
    qm.quiet_tool("tool1", duration=60)
    assert qm.is_quiet("tool1")
    assert not qm.is_quiet("tool2")
    qm.unquiet_tool("tool1")
    assert not qm.is_quiet("tool1")


def test_quiet_server():
    qm = QuietManager()
    qm.quiet_server("srv1")
    assert qm.is_quiet("any_tool", "srv1")
    status = qm.get_status()
    assert "srv1" in status["servers"]


def test_quiet_unquiet_all():
    qm = QuietManager()
    qm.quiet_tool("t1")
    qm.quiet_server("s1")
    qm.unquiet_all()
    assert not qm.is_quiet("t1")
    assert not qm.is_quiet("x", "s1")


# ── Session ────────────────────────────────────────────────────────────

from src.session import SessionTracker


def test_session_tracking():
    st = SessionTracker()
    st.record_call("success", 100.0)
    st.record_call("error", 200.0)
    stats = st.get_stats()
    assert stats["total_calls"] == 2
    assert stats["success_calls"] == 1
    assert stats["error_calls"] == 1
    assert stats["avg_duration_ms"] == 150.0


def test_session_reset():
    st = SessionTracker()
    st.record_call("success", 100)
    st.reset()
    stats = st.get_stats()
    assert stats["total_calls"] == 0


# ── Database ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_init_and_log(tmp_path):
    from src.db import Database
    db = Database(str(tmp_path / "test.db"))
    await db.init()

    await db.log_call("srv1", "tool1", 50.0, "success", session_id="s1")
    await db.log_call("srv1", "tool1", 100.0, "error", session_id="s1")

    stats = await db.get_stats()
    assert len(stats) == 1
    assert stats[0]["total_calls"] == 2
    assert stats[0]["success_calls"] == 1

    total = await db.get_total_calls()
    assert total == 2

    errors = await db.get_error_summary()
    assert len(errors) == 1

    await db.close()


@pytest.mark.asyncio
async def test_db_replay(tmp_path):
    from src.db import Database
    db = Database(str(tmp_path / "test.db"))
    await db.init()

    await db.add_replay_entry("srv", "tool", '{"x": 1}', '{"result": "ok"}')
    entries = await db.get_replay_entries(5)
    assert len(entries) == 1
    assert entries[0]["tool_name"] == "tool"

    entry = await db.get_replay_entry(entries[0]["id"])
    assert entry is not None

    await db.close()


@pytest.mark.asyncio
async def test_db_health(tmp_path):
    from src.db import Database
    db = Database(str(tmp_path / "test.db"))
    await db.init()

    await db.log_health("srv1", "up", latency_ms=10.0, tool_count=5)
    await db.log_health("srv1", "down")

    history = await db.get_health_history("srv1")
    assert len(history) == 2
    assert history[0]["status"] == "down"  # DESC order

    await db.close()


# ── Connector (unit test without real server) ──────────────────────────

from src.connector import ServerConnector


def test_connector_properties():
    sc = ServerConnector("test", {"transport": "stdio", "command": "echo"})
    assert sc.name == "test"
    assert sc.is_connected is False
    assert sc.tools == []
    assert sc.restart_count == 0
    sc.increment_restart()
    assert sc.restart_count == 1
    sc.reset_restart()
    assert sc.restart_count == 0
