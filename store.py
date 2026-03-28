"""store.py — PostgreSQL persistence layer for the Advanced Kit.

Replaces flat-file storage (events.jsonl, hot.md, session.md, projects/*.md)
with a real database behind the consumer's POSTGRES_DSN.

Falls back to flat files when POSTGRES_DSN is not configured.

Tables:
    events      — structured event ledger (replaces events.jsonl)
    memories    — tiered markdown blobs (hot, session, warm, vision)

Usage:
    from store import Store
    db = Store()  # auto-connects if POSTGRES_DSN is set
    db.append_event("decision", "Chose X over Y", project="Kit")
    events = db.get_events(limit=20)
    db.set_memory("hot", content)
    hot = db.get_memory("hot")
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

# ── Connection ────────────────────────────────────────────

_pg_pool = None
_sq_pool = None

def _get_dsn() -> str | None:
    """Extract and clean POSTGRES_DSN from environment."""
    dsn = os.getenv("POSTGRES_DSN", "").strip().strip('"').strip("'")
    return dsn if dsn and dsn.startswith("postgres") else None


def _connect_pg():
    """Return a psycopg2 connection or None if unavailable."""
    dsn = _get_dsn()
    if not dsn:
        return None
    try:
        import psycopg2
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"[store] Postgres connection failed: {e}", file=sys.stderr)
        return None


def _connect_sq():
    """Return a robust embedded SQLite connection."""
    from config import MEMORY_DIR
    import sqlite3
    db_path = MEMORY_DIR / "cortex.db"
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def _cursor(pg: bool = True):
    """Yield a cursor from the active connection pool."""
    if pg:
        global _pg_pool
        if _pg_pool is None or _pg_pool.closed:
            _pg_pool = _connect_pg()
        if _pg_pool is None:
            yield None
            return
        try:
            cur = _pg_pool.cursor()
            yield cur
            cur.close()
        except Exception as e:
            print(f"[store] Postgres Cursor error: {e}", file=sys.stderr)
            _pg_pool = None  
            yield None
    else:
        global _sq_pool
        if _sq_pool is None:
            _sq_pool = _connect_sq()
        try:
            cur = _sq_pool.cursor()
            yield cur
            cur.close()
            _sq_pool.commit()
        except Exception as e:
            print(f"[store] SQLite Cursor error: {e}", file=sys.stderr)
            if _sq_pool:
                _sq_pool.rollback()
            yield None

def close_pool():
    global _pg_pool, _sq_pool
    if _pg_pool is not None and not _pg_pool.closed:
        _pg_pool.close()
        _pg_pool = None
    if _sq_pool is not None:
        _sq_pool.close()
        _sq_pool = None

# ── Schema ────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type  VARCHAR(32) NOT NULL,
    content     TEXT NOT NULL,
    project     VARCHAR(128) DEFAULT '',
    meta        JSONB DEFAULT '{}'::jsonb,
    model       VARCHAR(64) DEFAULT '',
    latency_ms  REAL DEFAULT 0,
    resp_hash   VARCHAR(64) DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type);
CREATE INDEX IF NOT EXISTS idx_events_project ON events (project);

CREATE TABLE IF NOT EXISTS memories (
    tier        VARCHAR(32) PRIMARY KEY,
    content     TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed default tiers if empty
INSERT INTO memories (tier, content) VALUES ('hot', '')
    ON CONFLICT (tier) DO NOTHING;
INSERT INTO memories (tier, content) VALUES ('session', '')
    ON CONFLICT (tier) DO NOTHING;
INSERT INTO memories (tier, content) VALUES ('vision', '')
    ON CONFLICT (tier) DO NOTHING;
"""


def migrate(pg: bool = True) -> bool:
    """Run schema migration safely depending on backend dialect."""
    with _cursor(pg) as cur:
        if cur is None:
            return False
        try:
            sql = SCHEMA_SQL
            if not pg:
                sql = sql.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
                sql = sql.replace("JSONB", "TEXT")
                sql = sql.replace("TIMESTAMPTZ", "TIMESTAMP")
                sql = sql.replace("NOW()", "CURRENT_TIMESTAMP")
                sql = sql.replace("DEFAULT '{}'::jsonb", "DEFAULT '{}'")
                cur.executescript(sql)
            else:
                cur.execute(sql)
            return True
        except Exception as e:
            print(f"[store] Migration failed: {e}", file=sys.stderr)
            return False


# ── Public API ────────────────────────────────────────────

class Store:
    """PostgreSQL persistence with flat-file fallback."""

    def __init__(self):
        self.pg_available = migrate(pg=True)
        if self.pg_available:
            print("[store] PostgreSQL connected — using database storage.")
        else:
            migrate(pg=False)
            print("[store] PostgreSQL unavailable — using Embedded SQLite fallback.")

    # ── Events ────────────────────────────────────────

    def append_event(
        self,
        event_type: str,
        content: str,
        project: str = "",
        meta: dict | None = None,
        model: str = "",
        latency_ms: float = 0,
        resp_hash: str = "",
    ) -> bool:
        """Write an event to the ledger (Postgres or JSONL fallback)."""
        if self.pg_available:
            return self._pg_append_event(
                event_type, content, project, meta, model, latency_ms, resp_hash
            )
        return self._sqlite_append_event(event_type, content, project, meta, model, latency_ms, resp_hash)

    def get_events(self, limit: int = 20) -> list[dict]:
        """Read recent events."""
        if self.pg_available:
            return self._pg_get_events(limit)
        return self._sqlite_get_events(limit)

    def get_unprocessed(self, cursor: int, limit: int = 50) -> tuple[list[dict], int]:
        """Return (events, new_cursor) safely handling both backends."""
        if self.pg_available:
            return self._pg_get_unprocessed(cursor, limit)
        return self._sqlite_get_unprocessed(cursor, limit)

    def count_events(self) -> int:
        """Total event count."""
        if self.pg_available:
            return self._pg_count_events()
        return self._sqlite_count_events()

    # ── Memories ──────────────────────────────────────

    def get_memory(self, tier: str) -> str:
        """Read a memory tier (hot, session, vision, or warm:slug)."""
        if self.pg_available:
            return self._pg_get_memory(tier)
        return self._file_get_memory(tier)

    def set_memory(self, tier: str, content: str) -> bool:
        """Write a memory tier."""
        if self.pg_available:
            return self._pg_set_memory(tier, content)
        return self._file_set_memory(tier, content)

    def count_pathways(self) -> int:
        """Count warm project files / entries."""
        if self.pg_available:
            return self._pg_count_pathways()
        return self._file_count_pathways()

    # ── Postgres Implementations ──────────────────────

    def _pg_append_event(self, event_type, content, project, meta, model, latency_ms, resp_hash) -> bool:
        with _cursor(pg=True) as cur:
            if cur is None:
                return False
            try:
                cur.execute(
                    """INSERT INTO events (event_type, content, project, meta, model, latency_ms, resp_hash)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (event_type, content, project,
                     json.dumps(meta or {}), model, latency_ms, resp_hash)
                )
                return True
            except Exception as e:
                print(f"[store] Event insert failed: {e}", file=sys.stderr)
                return False

    def _pg_get_events(self, limit: int) -> list[dict]:
        with _cursor(pg=True) as cur:
            if cur is None:
                return []
            try:
                cur.execute(
                    """SELECT ts, event_type, content, project, meta, model, latency_ms
                       FROM events ORDER BY ts DESC LIMIT %s""",
                    (limit,)
                )
                rows = cur.fetchall()
                return [
                    {
                        "ts": row[0].isoformat() if row[0] else "",
                        "type": row[1], "content": row[2],
                        "project": row[3], "meta": row[4] or {},
                        "model": row[5] or "", "latency_ms": row[6] or 0,
                    }
                    for row in reversed(rows)
                ]
            except Exception as e:
                print(f"[store] Event read failed: {e}", file=sys.stderr)
                return []

    def _pg_get_unprocessed(self, cursor: int, limit: int) -> tuple[list[dict], int]:
        with _cursor(pg=True) as cur:
            if cur is None:
                return [], cursor
            try:
                cur.execute(
                    """SELECT id, ts, event_type, content, project, meta, model, latency_ms
                       FROM events WHERE id > %s ORDER BY id ASC LIMIT %s""",
                    (cursor, limit)
                )
                rows = cur.fetchall()
                events = []
                new_cursor = cursor
                for row in rows:
                    new_cursor = row[0]
                    events.append({
                        "ts": row[1].isoformat() if row[1] else "",
                        "type": row[2], "content": row[3],
                        "project": row[4], "meta": row[5] or {},
                        "model": row[6] or "", "latency_ms": row[7] or 0,
                    })
                return events, new_cursor
            except Exception as e:
                print(f"[store] Unprocessed read failed: {e}", file=sys.stderr)
                return [], cursor

    def _pg_count_events(self) -> int:
        with _cursor(pg=True) as cur:
            if cur is None:
                return self._file_count_events()
            try:
                cur.execute("SELECT COUNT(*) FROM events")
                return cur.fetchone()[0]
            except Exception:
                return self._file_count_events()

    def _pg_get_memory(self, tier: str) -> str:
        with _cursor(pg=True) as cur:
            if cur is None:
                return self._file_get_memory(tier)
            try:
                cur.execute("SELECT content FROM memories WHERE tier = %s", (tier,))
                row = cur.fetchone()
                return row[0] if row else ""
            except Exception:
                return self._file_get_memory(tier)

    def _pg_set_memory(self, tier: str, content: str) -> bool:
        with _cursor(pg=True) as cur:
            if cur is None:
                return self._file_set_memory(tier, content)
            try:
                cur.execute(
                    """INSERT INTO memories (tier, content, updated_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (tier) DO UPDATE SET content = %s, updated_at = NOW()""",
                    (tier, content, content)
                )
                return True
            except Exception as e:
                print(f"[store] Memory write failed: {e}", file=sys.stderr)
                return False

    def _pg_count_pathways(self) -> int:
        with _cursor(pg=True) as cur:
            if cur is None:
                return self._file_count_pathways()
            try:
                cur.execute("SELECT COUNT(*) FROM memories WHERE tier LIKE 'warm:%'")
                return cur.fetchone()[0]
            except Exception:
                return self._file_count_pathways()

    # ── SQLite Fallbacks ──────────────────────────────

    def _sqlite_append_event(self, event_type, content, project, meta, model, latency_ms, resp_hash) -> bool:
        with _cursor(pg=False) as cur:
            if cur is None: return False
            try:
                cur.execute(
                    """INSERT INTO events (event_type, content, project, meta, model, latency_ms, resp_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (event_type, content, project,
                     json.dumps(meta or {}), model, latency_ms, resp_hash)
                )
                return True
            except Exception as e:
                print(f"[store] SQLite insert failed: {e}", file=sys.stderr)
                return False

    def _sqlite_get_events(self, limit: int) -> list[dict]:
        with _cursor(pg=False) as cur:
            if cur is None: return []
            try:
                cur.execute(
                    """SELECT ts, event_type, content, project, meta, model, latency_ms
                       FROM events ORDER BY ts DESC LIMIT ?""",
                    (limit,)
                )
                rows = cur.fetchall()
                return [
                    {
                        "ts": row[0],
                        "type": row[1], "content": row[2],
                        "project": row[3], "meta": json.loads(row[4] or "{}"),
                        "model": row[5] or "", "latency_ms": row[6] or 0,
                    }
                    for row in reversed(rows)
                ]
            except Exception:
                return []

    def _sqlite_get_unprocessed(self, cursor: int, limit: int) -> tuple[list[dict], int]:
        with _cursor(pg=False) as cur:
            if cur is None: return [], cursor
            try:
                cur.execute(
                    """SELECT id, ts, event_type, content, project, meta, model, latency_ms
                       FROM events WHERE id > ? ORDER BY id ASC LIMIT ?""",
                    (cursor, limit)
                )
                rows = cur.fetchall()
                events = []
                new_cursor = cursor
                for row in rows:
                    new_cursor = row[0]
                    events.append({
                        "ts": row[1],
                        "type": row[2], "content": row[3],
                        "project": row[4], "meta": json.loads(row[5] or "{}"),
                        "model": row[6] or "", "latency_ms": row[7] or 0,
                    })
                return events, new_cursor
            except Exception:
                return [], cursor

    def _sqlite_count_events(self) -> int:
        with _cursor(pg=False) as cur:
            if cur is None: return 0
            try:
                cur.execute("SELECT COUNT(*) FROM events")
                return cur.fetchone()[0]
            except Exception:
                return 0

    # ── Flat-File (Memories only) ─────────────────────

    def _file_count_events(self) -> int:
        from config import EVENTS_JSONL
        if not EVENTS_JSONL.exists():
            return 0
        try:
            with open(EVENTS_JSONL, "r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        except Exception:
            return 0

    def _file_get_memory(self, tier: str) -> str:
        from config import HOT_MD, SESSION_MD, VISION_MD, PROJECTS_DIR
        lookup = {"hot": HOT_MD, "session": SESSION_MD, "vision": VISION_MD}
        if tier in lookup:
            p = lookup[tier]
            return p.read_text(encoding="utf-8") if p.exists() else ""
        if tier.startswith("warm:"):
            slug = tier.split(":", 1)[1]
            p = PROJECTS_DIR / f"{slug}.md"
            return p.read_text(encoding="utf-8") if p.exists() else ""
        return ""

    def _file_set_memory(self, tier: str, content: str) -> bool:
        from config import HOT_MD, SESSION_MD, VISION_MD, PROJECTS_DIR
        lookup = {"hot": HOT_MD, "session": SESSION_MD, "vision": VISION_MD}
        try:
            if tier in lookup:
                lookup[tier].parent.mkdir(parents=True, exist_ok=True)
                lookup[tier].write_text(content, encoding="utf-8")
                return True
            if tier.startswith("warm:"):
                slug = tier.split(":", 1)[1]
                p = PROJECTS_DIR / f"{slug}.md"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                return True
        except Exception:
            return False
        return False

    def _file_count_pathways(self) -> int:
        from config import PROJECTS_DIR
        return len(list(PROJECTS_DIR.glob("*.md"))) if PROJECTS_DIR.exists() else 0


# ── Standalone Test ───────────────────────────────────────

if __name__ == "__main__":
    db = Store()
    print(f"  Storage Engine: {'PostgreSQL' if db.pg_available else 'Embedded SQLite (.db)'}")
    
    # Remove old dev check that guarded test writes on Postgres availability
    # Both architectures now support fully native SQL queries
    initial_count = db.count_events()
    print(f"  Events Initial: {initial_count}")
    print(f"  Pathways: {db.count_pathways()}")
    
    # Inject heartbeat directly onto storage layer
    success = db.append_event("status", f"Store self-test passed on {'PG' if db.pg_available else 'SQ'}", model="test", latency_ms=1.5)
    print(f"  Append Event Success: {success}")
    print(f"  Events Present: {db.count_events()}")
