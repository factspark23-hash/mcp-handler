"""SQLite layer for MCP Hub - all database operations."""
import aiosqlite
import time
import json
from pathlib import Path


class Database:
    def __init__(self, db_path: str = "data/hub.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._create_tables()

    async def _create_tables(self):
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                session_id TEXT,
                server_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                original_tool_name TEXT,
                duration_ms REAL,
                status TEXT NOT NULL,
                error_message TEXT,
                params_hash TEXT,
                response_size INTEGER
            );

            CREATE TABLE IF NOT EXISTS server_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                server_name TEXT NOT NULL,
                status TEXT NOT NULL,
                latency_ms REAL,
                tool_count INTEGER,
                restart_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tool_stats (
                server_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                total_calls INTEGER DEFAULT 0,
                success_calls INTEGER DEFAULT 0,
                error_calls INTEGER DEFAULT 0,
                total_duration_ms REAL DEFAULT 0,
                avg_duration_ms REAL DEFAULT 0,
                last_called REAL,
                PRIMARY KEY (server_name, tool_name)
            );

            CREATE TABLE IF NOT EXISTS replay_buffer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                server_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                params_json TEXT,
                result_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_calls_timestamp ON tool_calls(timestamp);
            CREATE INDEX IF NOT EXISTS idx_calls_server ON tool_calls(server_name);
            CREATE INDEX IF NOT EXISTS idx_health_server ON server_health(server_name);
            CREATE INDEX IF NOT EXISTS idx_replay_timestamp ON replay_buffer(timestamp);
        """)
        await self._db.commit()

    async def log_call(self, server_name: str, tool_name: str, duration_ms: float,
                       status: str, session_id: str = None, original_tool_name: str = None,
                       error_message: str = None, params_hash: str = None,
                       response_size: int = None):
        now = time.time()
        await self._db.execute(
            """INSERT INTO tool_calls
               (timestamp, session_id, server_name, tool_name, original_tool_name,
                duration_ms, status, error_message, params_hash, response_size)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, session_id, server_name, tool_name, original_tool_name,
             duration_ms, status, error_message, params_hash, response_size)
        )
        # Update aggregated stats
        await self._db.execute("""
            INSERT INTO tool_stats (server_name, tool_name, total_calls, success_calls,
                                    error_calls, total_duration_ms, avg_duration_ms, last_called)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(server_name, tool_name) DO UPDATE SET
                total_calls = total_calls + 1,
                success_calls = success_calls + ?,
                error_calls = error_calls + ?,
                total_duration_ms = total_duration_ms + ?,
                avg_duration_ms = (total_duration_ms + ?) / (total_calls),
                last_called = ?
        """, (server_name, tool_name,
              1 if status == "success" else 0,
              1 if status == "error" else 0,
              duration_ms, duration_ms, now,
              1 if status == "success" else 0,
              1 if status == "error" else 0,
              duration_ms, duration_ms, now))
        await self._db.commit()

    async def log_health(self, server_name: str, status: str, latency_ms: float = None,
                         tool_count: int = 0, restart_count: int = 0):
        await self._db.execute(
            """INSERT INTO server_health
               (timestamp, server_name, status, latency_ms, tool_count, restart_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (time.time(), server_name, status, latency_ms, tool_count, restart_count)
        )
        await self._db.commit()

    async def get_stats(self, since_hours: float = None):
        if since_hours:
            cutoff = time.time() - (since_hours * 3600)
            async with self._db.execute(
                "SELECT * FROM tool_stats WHERE last_called > ? ORDER BY total_calls DESC",
                (cutoff,)
            ) as cursor:
                return [dict(row) async for row in cursor]
        async with self._db.execute(
            "SELECT * FROM tool_stats ORDER BY total_calls DESC"
        ) as cursor:
            return [dict(row) async for row in cursor]

    async def get_call_history(self, limit: int = 50, since_hours: float = None,
                               server_name: str = None, status: str = None):
        conditions = []
        params = []
        if since_hours:
            conditions.append("timestamp > ?")
            params.append(time.time() - since_hours * 3600)
        if server_name:
            conditions.append("server_name = ?")
            params.append(server_name)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM tool_calls {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        async with self._db.execute(query, params) as cursor:
            return [dict(row) async for row in cursor]

    async def get_error_summary(self, since_hours: float = 24):
        cutoff = time.time() - since_hours * 3600
        async with self._db.execute(
            """SELECT error_message, COUNT(*) as count
               FROM tool_calls WHERE status = 'error' AND timestamp > ?
               GROUP BY error_message ORDER BY count DESC""",
            (cutoff,)
        ) as cursor:
            return [dict(row) async for row in cursor]

    async def get_slow_tools(self, limit: int = 10):
        async with self._db.execute(
            """SELECT server_name, tool_name, avg_duration_ms, total_calls
               FROM tool_stats ORDER BY avg_duration_ms DESC LIMIT ?""",
            (limit,)
        ) as cursor:
            return [dict(row) async for row in cursor]

    async def get_health_history(self, server_name: str = None, limit: int = 50):
        if server_name:
            async with self._db.execute(
                "SELECT * FROM server_health WHERE server_name = ? ORDER BY timestamp DESC LIMIT ?",
                (server_name, limit)
            ) as cursor:
                return [dict(row) async for row in cursor]
        async with self._db.execute(
            "SELECT * FROM server_health ORDER BY timestamp DESC LIMIT ?", (limit,)
        ) as cursor:
            return [dict(row) async for row in cursor]

    async def add_replay_entry(self, server_name: str, tool_name: str,
                               params_json: str, result_json: str):
        await self._db.execute(
            """INSERT INTO replay_buffer (timestamp, server_name, tool_name, params_json, result_json)
               VALUES (?, ?, ?, ?, ?)""",
            (time.time(), server_name, tool_name, params_json, result_json)
        )
        await self._db.commit()

    async def get_replay_entries(self, count: int = 5):
        async with self._db.execute(
            "SELECT * FROM replay_buffer ORDER BY timestamp DESC LIMIT ?", (count,)
        ) as cursor:
            rows = [dict(row) async for row in cursor]
            return list(reversed(rows))

    async def get_replay_entry(self, entry_id: int):
        async with self._db.execute(
            "SELECT * FROM replay_buffer WHERE id = ?", (entry_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_total_calls(self, since_hours: float = None):
        if since_hours:
            cutoff = time.time() - since_hours * 3600
            async with self._db.execute(
                "SELECT COUNT(*) as cnt FROM tool_calls WHERE timestamp > ?", (cutoff,)
            ) as cursor:
                row = await cursor.fetchone()
                return row["cnt"]
        async with self._db.execute("SELECT COUNT(*) as cnt FROM tool_calls") as cursor:
            row = await cursor.fetchone()
            return row["cnt"]

    async def export_stats(self):
        stats = {
            "tool_stats": await self.get_stats(),
            "recent_calls": await self.get_call_history(limit=200),
            "error_summary": await self.get_error_summary(since_hours=168),
            "slow_tools": await self.get_slow_tools(),
        }
        return json.dumps(stats, indent=2, default=str)

    async def prune_old_records(self, max_records: int):
        async with self._db.execute("SELECT COUNT(*) as cnt FROM tool_calls") as cursor:
            row = await cursor.fetchone()
            if row["cnt"] > max_records:
                excess = row["cnt"] - max_records
                await self._db.execute(
                    """DELETE FROM tool_calls WHERE id IN (
                        SELECT id FROM tool_calls ORDER BY timestamp ASC LIMIT ?
                    )""", (excess,)
                )
                await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()
