"""memory_api.py — Thin client for the Agent Memory daemon system.

Agents call this instead of reading/writing memory files directly.
Connects to daemon TCP sockets with automatic fallback to direct
file I/O if daemons aren't running.

Mirrors the production agent_memory_api.py.

Python API:
    from memory_api import MemoryAPI
    api = MemoryAPI()
    hot = api.get_hot()
    api.lesson("Always sanitize slugs before path concatenation")
    api.emit_event("decision", "Chose X over Y", project="MyProject")

CLI:
    python memory_api.py ping
    python memory_api.py get hot
    python memory_api.py get session
    python memory_api.py get warm myproject
    python memory_api.py lesson "Never exceed 5 terminals"
    python memory_api.py event decision "Chose X over Y" --project MyProject
    python memory_api.py events --limit 10
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))
from config import (
    HOT_MD, SESSION_MD, PROJECTS_DIR, PORTS,
)

# Per-call timeout in seconds
SOCKET_TIMEOUT = 2.0


# ── Low-Level TCP Socket Call ──────────────────────────────

def _tcp_call(port: int, payload: dict) -> dict | None:
    """Send a JSON command to a localhost TCP socket and return the response.

    Returns None on any error (timeout, connection refused, decode failure).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(SOCKET_TIMEOUT)
        s.connect(("127.0.0.1", port))
        s.sendall(json.dumps(payload).encode("utf-8") + b"\n")

        chunks = []
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if chunks[-1].endswith(b"\n"):
                break

        s.close()
        raw = b"".join(chunks)
        return json.loads(raw.decode("utf-8"))
    except (ConnectionRefusedError, ConnectionResetError, TimeoutError):
        return None  # Daemon not running — caller will fall back
    except Exception:
        return None


# ── Fallback File Reads ─────────────────────────────────────

def _fallback_read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


# ── Public API ─────────────────────────────────────────────

class MemoryAPI:
    """Thin agent client for the daemon system.

    All methods gracefully degrade to direct file I/O if daemons
    are unreachable. The agent never crashes from a daemon outage.
    """

    def ping(self) -> bool:
        """Return True if both daemons are reachable."""
        r = _tcp_call(PORTS.READER, {"cmd": "PING"})
        w = _tcp_call(PORTS.WRITER, {"cmd": "PING"})
        return bool(r and r.get("pong") and w and w.get("pong"))

    # ── Reads ─────────────────────────────────────────────

    def get_hot(self) -> str:
        """Return hot.md contents (cached by reader daemon, fallback to disk)."""
        resp = _tcp_call(PORTS.READER, {"cmd": "GET_HOT"})
        if resp and resp.get("ok"):
            return resp["content"]
        return _fallback_read(HOT_MD)

    def get_session(self) -> str:
        """Return session.md contents."""
        resp = _tcp_call(PORTS.READER, {"cmd": "GET_SESSION"})
        if resp and resp.get("ok"):
            return resp["content"]
        return _fallback_read(SESSION_MD)

    def get_warm(self, slug: str) -> str:
        """Return warm project file contents for the given slug."""
        slug = slug.strip().lower()
        resp = _tcp_call(PORTS.READER, {"cmd": "GET_WARM", "slug": slug})
        if resp and resp.get("ok"):
            return resp["content"]
        path = PROJECTS_DIR / f"{slug}.md"
        return _fallback_read(path)

    # ── Writes ────────────────────────────────────────────

    def lesson(self, text: str) -> bool:
        """Append a lesson to hot.md RECENT LESSONS section.

        Returns True if write succeeded. Falls back to False if daemon
        is unreachable.
        """
        resp = _tcp_call(PORTS.WRITER, {"cmd": "APPEND_LESSON", "lesson": text})
        return bool(resp and resp.get("ok"))

    def update_session(
        self,
        current_work: str = "",
        files_touched: list[str] | None = None,
        pending_actions: list[str] | None = None,
        critical_context: list[str] | None = None,
    ) -> bool:
        """Overwrite session.md with structured state."""
        payload = {
            "cmd": "UPDATE_SESSION",
            "current_work": current_work,
            "files_touched": files_touched or [],
            "pending_actions": pending_actions or [],
            "critical_context": critical_context or [],
        }
        resp = _tcp_call(PORTS.WRITER, payload)
        return bool(resp and resp.get("ok"))

    def update_hot(self, session_summary: str, open_threads: list[str] | None = None) -> bool:
        """Update hot.md SESSION SUMMARY and optionally OPEN THREADS."""
        payload: dict = {
            "cmd": "UPDATE_HOT",
            "session_summary": session_summary,
        }
        if open_threads is not None:
            payload["open_threads"] = open_threads
        resp = _tcp_call(PORTS.WRITER, payload)
        return bool(resp and resp.get("ok"))

    # ── Loop Detector ────────────────────────────────────

    def record_call(
        self,
        tool: str,
        args_hash: str = "",
        session_id: str = "default",
        detail: str = "",
    ) -> dict:
        """Record a tool call. Returns {loop: False} or {loop: True, mayday: {...}}.

        Call this before each significant tool invocation. If loop=True,
        the agent should stop, re-read the relevant file, and change approach.
        """
        resp = _tcp_call(PORTS.LOOP_DETECTOR, {
            "cmd": "RECORD_CALL",
            "session_id": session_id,
            "tool": tool,
            "args_hash": args_hash,
            "detail": detail,
        })
        if resp is None:
            return {"ok": True, "loop": False}  # daemon down — non-fatal
        return resp

    def loop_status(self, session_id: str = "") -> dict:
        """Return current loop detection state for a session."""
        resp = _tcp_call(PORTS.LOOP_DETECTOR, {
            "cmd": "STATUS",
            "session_id": session_id or None,
        })
        return resp or {"ok": False, "error": "loop-detector unreachable"}

    def loop_reset(self, session_id: str = "default") -> bool:
        """Clear loop state for a session."""
        resp = _tcp_call(PORTS.LOOP_DETECTOR, {
            "cmd": "RESET",
            "session_id": session_id,
        })
        return bool(resp and resp.get("ok"))

    # ── Event Ledger ─────────────────────────────────────

    def emit_event(
        self,
        event_type: str,
        content: str,
        project: str = "",
        meta: dict | None = None,
        model: str = "",
        latency_ms: float = 0,
        resp_hash: str = "",
    ) -> bool:
        """Append a structured event to the JSONL event ledger or Postgres Database.

        Writes directly via the event_ledger wrapper (which uses Store).
        """
        try:
            from event_ledger import append_event
            return append_event(
                event_type, content, project=project, meta=meta,
                model=model, latency_ms=latency_ms, resp_hash=resp_hash
            )
        except ImportError:
            return False

    def get_ledger_events(self, limit: int = 20) -> list[dict]:
        """Read recent events from the JSONL event ledger."""
        try:
            from event_ledger import read_events, count_lines
            total = count_lines()
            start = max(0, total - limit)
            return read_events(since_line=start, limit=limit)
        except ImportError:
            return []


# ── CLI ─────────────────────────────────────────────────────

def _cli() -> None:
    args = sys.argv[1:]
    if not args:
        print("Antigravity Memory API")
        print()
        print("Usage:")
        print("  memory_api.py ping")
        print("  memory_api.py get <hot|session|warm SLUG>")
        print("  memory_api.py lesson <text>")
        print("  memory_api.py event <type> <content> [--project NAME]")
        print("  memory_api.py events [--limit N]")
        return

    api = MemoryAPI()
    cmd = args[0]

    if cmd == "ping":
        ok = api.ping()
        print("OK — daemons reachable" if ok else "DEGRADED — falling back to disk reads")
        raise SystemExit(0 if ok else 1)

    elif cmd == "get":
        if len(args) < 2:
            print("Usage: get <hot|session|warm SLUG>", file=sys.stderr)
            raise SystemExit(1)
        target = args[1]
        if target == "hot":
            print(api.get_hot())
        elif target == "session":
            print(api.get_session())
        elif target == "warm":
            if len(args) < 3:
                print("Usage: get warm <slug>", file=sys.stderr)
                raise SystemExit(1)
            print(api.get_warm(args[2]))
        else:
            print(f"Unknown target: {target!r}", file=sys.stderr)
            raise SystemExit(1)

    elif cmd == "lesson":
        if len(args) < 2:
            print("Usage: lesson <text>", file=sys.stderr)
            raise SystemExit(1)
        text = " ".join(args[1:])
        ok = api.lesson(text)
        print("Lesson written." if ok else "Write failed (daemon unreachable?)")
        raise SystemExit(0 if ok else 1)

    elif cmd == "event":
        if len(args) < 3:
            print("Usage: event <type> <content> [--project NAME]", file=sys.stderr)
            raise SystemExit(1)
        event_type = args[1]
        content = args[2]
        project = ""
        if "--project" in args:
            idx = args.index("--project")
            if idx + 1 < len(args):
                project = args[idx + 1]
        ok = api.emit_event(event_type, content, project=project)
        print("Event logged." if ok else "Failed to log event.")
        raise SystemExit(0 if ok else 1)

    elif cmd == "events":
        limit = 20
        if "--limit" in args:
            idx = args.index("--limit")
            if idx + 1 < len(args):
                limit = int(args[idx + 1])
        events = api.get_ledger_events(limit=limit)
        if not events:
            print("No events found.")
        for ev in events:
            ts = ev.get("ts", "")[:16]
            t = ev.get("type", "?")
            proj = ev.get("project", "")
            content = ev.get("content", "")[:80]
            proj_str = f" [{proj}]" if proj else ""
            print(f"  {ts} [{t}]{proj_str}: {content}")

    else:
        print(f"Unknown command: {cmd!r}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    _cli()
