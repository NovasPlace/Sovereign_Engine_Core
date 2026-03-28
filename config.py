"""config.py — Single source of truth for all Agent Memory Kit paths.

Every daemon and API client imports from here. Override defaults via
environment variables. TCP ports used instead of Unix sockets for
cross-platform compatibility (Windows + Linux).

Usage:
    from config import MEMORY_DIR, KIT_ROOT, PORTS
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Base Directories ──────────────────────────────────────────

# Kit root (parent of this file)
KIT_ROOT: Path = Path(__file__).parent.resolve()

# Root of all memory markdown files (hot.md, warm files, session state)
MEMORY_DIR: Path = Path(os.environ.get(
    "AGENT_MEMORY_DIR",
    str(KIT_ROOT / "memory"),
))

# Warm project files
PROJECTS_DIR: Path = MEMORY_DIR / "projects"

# ── Derived Paths ─────────────────────────────────────────────

HOT_MD:       Path = MEMORY_DIR / "hot.md"
SESSION_MD:   Path = MEMORY_DIR / "session.md"
VISION_MD:    Path = MEMORY_DIR / "vision.md"
EVENTS_JSONL: Path = MEMORY_DIR / "events.jsonl"
LEDGER_CURSOR: Path = MEMORY_DIR / ".ledger_cursor"

# ── SQLite State Files ────────────────────────────────────────

LOOP_LEDGER_DB: Path = MEMORY_DIR / "loop_ledger.db"

# ── TCP Ports (replaces Unix sockets for Windows compat) ──────

class PORTS:
    """TCP localhost ports for daemon communication."""
    READER:        int = int(os.environ.get("AGENT_PORT_READER", "9100"))
    WRITER:        int = int(os.environ.get("AGENT_PORT_WRITER", "9101"))
    LOOP_DETECTOR: int = int(os.environ.get("AGENT_PORT_LOOP", "9102"))
    EVENT_PROC:    int = int(os.environ.get("AGENT_PORT_EVENT", "9103"))

# ── Daemon Tuning ─────────────────────────────────────────────

# Loop detector: how many consecutive identical tool calls = a loop
LOOP_THRESHOLD: int = int(os.environ.get("AGENT_LOOP_THRESHOLD", "3"))

# Event processor: poll interval in seconds
EVENT_POLL_INTERVAL: int = int(os.environ.get("AGENT_EVENT_POLL", "30"))

# Context pressure: safe token limit before flush recommendation
PRESSURE_SAFE_LIMIT: int = int(os.environ.get("AGENT_PRESSURE_LIMIT", "150000"))


def ensure_dirs() -> None:
    """Create all required directories if they don't exist."""
    for d in [MEMORY_DIR, PROJECTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    print("Agent Memory Kit — Configuration")
    print(f"  KIT_ROOT:     {KIT_ROOT}")
    print(f"  MEMORY_DIR:   {MEMORY_DIR}")
    print(f"  PROJECTS_DIR: {PROJECTS_DIR}")
    print(f"  HOT_MD:       {HOT_MD}")
    print(f"  EVENTS_JSONL: {EVENTS_JSONL}")
    print(f"  READER port:  {PORTS.READER}")
    print(f"  WRITER port:  {PORTS.WRITER}")
    print(f"  LOOP port:    {PORTS.LOOP_DETECTOR}")
    print(f"  EVENT port:   {PORTS.EVENT_PROC}")
    ensure_dirs()
    print("  Directories: OK")
