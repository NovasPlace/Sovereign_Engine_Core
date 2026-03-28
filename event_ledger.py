"""event_ledger.py — JSONL-based event journal for the organism.

DEPRECATED: This module now delegates entirely to `store.py` for
PostgreSQL/JSONL persistence. Kept for CLI backward compatibility.

Usage (CLI):
    python event_ledger.py append decision "Chose SQLite over PostgreSQL" --project MyProject
    python event_ledger.py read --limit 10
    python event_ledger.py count
"""
from __future__ import annotations

import sys
from pathlib import Path

# Provide get_cursor/set_cursor utilities needed by event_processor
try:
    from config import LEDGER_CURSOR
except ImportError:
    LEDGER_CURSOR = Path(__file__).parent / "memory" / ".ledger_cursor"

# All heavy lifting routes through Store
try:
    from store import Store
    _store = Store()
except ImportError:
    print("[event_ledger] Failed to import Store. Ensure config.py and store.py are present.", file=sys.stderr)
    sys.exit(1)

VALID_TYPES = {
    "decision", "file_edit", "lesson", "architecture",
    "thread", "error", "context", "status",
}


def append_event(
    event_type: str,
    content: str,
    project: str = "",
    meta: dict | None = None,
    model: str = "",
    latency_ms: float = 0,
    resp_hash: str = "",
) -> bool:
    if event_type not in VALID_TYPES:
        print(f"[event_ledger] Unknown type: {event_type!r}. "
              f"Valid: {', '.join(sorted(VALID_TYPES))}", file=sys.stderr)
        return False
    return _store.append_event(
        event_type, content, project, meta,
        model=model, latency_ms=latency_ms, resp_hash=resp_hash
    )


def read_events(since_line: int = 0, limit: int = 20) -> list[dict]:
    """Read events handling either JSONL line num or PG integer ID."""
    events, _ = _store.get_unprocessed(since_line, limit)
    return events


def count_lines() -> int:
    return _store.count_events()


def get_cursor() -> int:
    try:
        return int(LEDGER_CURSOR.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def set_cursor(line: int) -> None:
    LEDGER_CURSOR.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_CURSOR.write_text(str(line))


def get_unprocessed(limit: int = 50) -> list[dict]:
    # Returns only events. Daemon now uses Store directly for the tuple.
    cursor = get_cursor()
    events, _ = _store.get_unprocessed(cursor, limit)
    return events


# ── CLI ─────────────────────────────────────────────────────

def _cli() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: event_ledger.py <append|read|count> [args]")
        return

    cmd = args[0]

    if cmd == "append":
        if len(args) < 3:
            print("Usage: append <type> <content> [--project NAME]")
            raise SystemExit(1)
        event_type = args[1]
        content = args[2]
        project = ""
        if "--project" in args:
            idx = args.index("--project")
            if idx + 1 < len(args):
                project = args[idx + 1]
        ok = append_event(event_type, content, project=project)
        print("Event logged." if ok else "Failed to log event.")
        raise SystemExit(0 if ok else 1)

    elif cmd == "read":
        limit = 20
        if "--limit" in args:
            idx = args.index("--limit")
            if idx + 1 < len(args):
                limit = int(args[idx + 1])
        # Using get_events grabs the most recent limit events, regardless of cursor
        events = _store.get_events(limit=limit)
        for ev in reversed(events):  # print chronological
            ts = ev.get("ts", "")[:16]
            t = ev.get("type", "?")
            proj = ev.get("project", "")
            content = ev.get("content", "")[:80]
            proj_str = f" [{proj}]" if proj else ""
            print(f"  {ts} [{t}]{proj_str}: {content}")

    elif cmd == "count":
        print(f"Total events: {count_lines()}")

    else:
        print(f"Unknown command: {cmd!r}")
        raise SystemExit(1)


if __name__ == "__main__":
    _cli()
