"""loop_detector.py — SQLite-backed repetition detection daemon.

Records tool calls and detects when an agent is stuck in a loop
(repeating the same call pattern). Emits Mayday payloads when
loops exceed the configured threshold.

Commands (over TCP):
    PING        → {"pong": true}
    RECORD_CALL → Record a tool call, returns {loop: bool}
    STATUS      → Current loop state for a session
    RESET       → Clear loop state for a session
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import LOOP_LEDGER_DB, LOOP_THRESHOLD, PORTS

logger = logging.getLogger("daemon.loop_detector")

_DB_INIT = """
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    args_hash TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tc_session ON tool_calls(session_id, ts DESC);
"""


def _init_db() -> sqlite3.Connection:
    """Initialize the loop ledger database."""
    conn = sqlite3.connect(str(LOOP_LEDGER_DB))
    conn.executescript(_DB_INIT)
    return conn


def _record_call(conn: sqlite3.Connection, session_id: str, tool: str,
                 args_hash: str, detail: str) -> dict:
    """Record a tool call and check for loops."""
    now = time.time()
    conn.execute(
        "INSERT INTO tool_calls (session_id, tool, args_hash, detail, ts) VALUES (?, ?, ?, ?, ?)",
        (session_id, tool, args_hash, detail, now),
    )
    conn.commit()

    # Check for loops: fetch last N calls for this session
    window = LOOP_THRESHOLD + 1
    rows = conn.execute(
        "SELECT tool, args_hash FROM tool_calls WHERE session_id = ? ORDER BY ts DESC LIMIT ?",
        (session_id, window),
    ).fetchall()

    if len(rows) >= LOOP_THRESHOLD:
        # Check if all recent calls are identical
        recent = rows[:LOOP_THRESHOLD]
        if all(r[0] == recent[0][0] and r[1] == recent[0][1] for r in recent):
            mayday = {
                "mayday": True,
                "stage": "loop_detection",
                "error": f"Agent repeated '{tool}' with same args {LOOP_THRESHOLD} times",
                "tool": tool,
                "args_hash": args_hash,
                "consecutive_count": LOOP_THRESHOLD,
                "recommended_fix": "Re-read the relevant file, change approach, or ask for help.",
            }
            logger.warning(f"LOOP DETECTED: {tool} x{LOOP_THRESHOLD} (session={session_id})")
            return {"ok": True, "loop": True, "mayday": mayday}

    return {"ok": True, "loop": False}


def _status(conn: sqlite3.Connection, session_id: str | None) -> dict:
    """Return loop detection state."""
    if session_id:
        rows = conn.execute(
            "SELECT tool, args_hash, ts FROM tool_calls WHERE session_id = ? ORDER BY ts DESC LIMIT 10",
            (session_id,),
        ).fetchall()
        return {
            "ok": True,
            "session_id": session_id,
            "recent_calls": [{"tool": r[0], "args_hash": r[1], "ts": r[2]} for r in rows],
            "threshold": LOOP_THRESHOLD,
        }
    else:
        # All sessions
        sessions = conn.execute(
            "SELECT DISTINCT session_id FROM tool_calls"
        ).fetchall()
        return {
            "ok": True,
            "sessions": [s[0] for s in sessions],
            "threshold": LOOP_THRESHOLD,
        }


def _reset(conn: sqlite3.Connection, session_id: str) -> dict:
    """Clear loop state for a session."""
    conn.execute("DELETE FROM tool_calls WHERE session_id = ?", (session_id,))
    conn.commit()
    logger.info(f"Loop state reset for session: {session_id}")
    return {"ok": True}


def _dispatch(conn: sqlite3.Connection, cmd_obj: dict) -> dict:
    cmd = cmd_obj.get("cmd", "")
    if cmd == "PING":
        return {"pong": True}
    elif cmd == "RECORD_CALL":
        return _record_call(
            conn,
            session_id=cmd_obj.get("session_id", "default"),
            tool=cmd_obj.get("tool", "unknown"),
            args_hash=cmd_obj.get("args_hash", ""),
            detail=cmd_obj.get("detail", ""),
        )
    elif cmd == "STATUS":
        return _status(conn, cmd_obj.get("session_id"))
    elif cmd == "RESET":
        return _reset(conn, cmd_obj.get("session_id", "default"))
    return {"ok": False, "error": f"unknown command: {cmd!r}"}


async def _handle_client(conn: sqlite3.Connection,
                         reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter):
    try:
        data = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not data:
            return
        cmd_obj = json.loads(data.decode("utf-8"))
        response = _dispatch(conn, cmd_obj)
        writer.write(json.dumps(response).encode("utf-8") + b"\n")
        await writer.drain()
    except Exception as e:
        logger.error(f"Client handler error: {e}")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def run_loop_detector(shutdown_event: asyncio.Event | None = None):
    """Start the loop detector TCP server."""
    conn = _init_db()

    async def handler(reader, writer):
        await _handle_client(conn, reader, writer)

    server = await asyncio.start_server(handler, "127.0.0.1", PORTS.LOOP_DETECTOR)
    logger.info(f"LoopDetector listening on 127.0.0.1:{PORTS.LOOP_DETECTOR}")

    async with server:
        if shutdown_event:
            await shutdown_event.wait()
            server.close()
        else:
            await server.serve_forever()

    conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_loop_detector())
