"""daemon.py — Main daemon runner for the Agent Memory Kit.

Single asyncio event loop that starts all sub-daemons concurrently.
Mirrors the production agent_memory_daemon.py.

Usage:
    python daemon.py             # Start all daemons
    python daemon.py --dry-run   # Log only, skip writer and event processor

Sub-daemons started:
    - MemoryReader   (TCP :9100)  — cached file reads
    - MemoryWriter   (TCP :9101)  — atomic validated writes
    - LoopDetector   (TCP :9102)  — repetition detection
    - EventProcessor (background) — JSONL ledger → warm files
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))
from config import ensure_dirs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("agent-daemon")

_shutdown = asyncio.Event()


def _handle_signal(signum, frame):
    logger.info("Received signal %d, shutting down...", signum)
    _shutdown.set()


async def main(dry_run: bool = False) -> None:
    """Run all background daemons concurrently."""
    # Register signal handlers (works on Windows for SIGINT)
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (OSError, AttributeError):
        pass  # SIGTERM not available on Windows

    # Ensure all directories exist
    ensure_dirs()

    logger.info("=" * 60)
    logger.info("  ANTIGRAVITY AGENT DAEMON")
    logger.info("  Protocol: Logic → Proof → Harden → Ship")
    logger.info("=" * 60)

    # Import sub-daemons
    from daemons.memory_reader import run_reader
    from daemons.memory_writer import run_writer
    from daemons.loop_detector import run_loop_detector
    from daemons.event_processor import run_event_processor

    tasks: list[asyncio.Task] = []

    async def _guarded(name: str, coro):
        """Run a sub-daemon, log and suppress if it fails to bind."""
        try:
            await coro
        except OSError as e:
            logger.error(f"[{name}] Failed to start: {e} — other daemons continue.")
        except Exception as e:
            logger.error(f"[{name}] Crashed: {e}")

    # Reader always runs
    tasks.append(asyncio.create_task(_guarded("Reader", run_reader(shutdown_event=_shutdown))))

    if dry_run:
        logger.info("[DRY RUN] Writer and EventProcessor skipped")
    else:
        tasks.append(asyncio.create_task(_guarded("Writer", run_writer(shutdown_event=_shutdown))))
        tasks.append(asyncio.create_task(_guarded("EventProcessor", run_event_processor(shutdown_event=_shutdown))))

    # Loop detector always runs
    tasks.append(asyncio.create_task(_guarded("LoopDetector", run_loop_detector(shutdown_event=_shutdown))))

    logger.info(f"Started {len(tasks)} sub-daemon(s)")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass

    logger.info("Agent Daemon stopped (all %d tasks completed).", len(tasks))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Antigravity Agent Daemon")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log actions without making changes",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
