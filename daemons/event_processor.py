"""event_processor.py — Background daemon that processes the event ledger.

Polls events.jsonl for unprocessed entries and:
1. Updates warm project files with project-specific events
2. Rolls up lessons into hot.md
3. Advances the processing cursor

Mirrors the production ledger_daemon.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MEMORY_DIR, PROJECTS_DIR, HOT_MD, EVENTS_JSONL, EVENT_POLL_INTERVAL, PORTS
from event_ledger import get_unprocessed, set_cursor, get_cursor, count_lines

logger = logging.getLogger("daemon.event_processor")


def _slugify(name: str) -> str:
    """Convert a project name to a filesystem slug."""
    return name.strip().lower().replace(" ", "-").replace("/", "-")


def _ensure_warm_file(slug: str) -> Path:
    """Create a warm project file if it doesn't exist."""
    path = PROJECTS_DIR / f"{slug}.md"
    if not path.exists():
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# {slug}\n\n"
            f"> Auto-created warm file.\n\n"
            f"## Status\n\nActive\n\n"
            f"## Recent Activity\n\n"
            f"## Decisions\n\n"
            f"## Known Issues\n\n",
            encoding="utf-8",
        )
        logger.info(f"Created warm file: {path}")
    return path


def _append_to_warm(slug: str, event: dict) -> None:
    """Append an event summary to a warm project file."""
    path = _ensure_warm_file(slug)
    content = path.read_text(encoding="utf-8")

    ts = event.get("ts", "")[:16]
    etype = event.get("type", "?")
    text = event.get("content", "")[:120]
    line = f"- `{ts}` [{etype}] {text}\n"

    # Append to the "Recent Activity" section
    marker = "## Recent Activity"
    if marker in content:
        idx = content.index(marker) + len(marker)
        # Find next newline after marker
        nl = content.index("\n", idx)
        content = content[:nl + 1] + "\n" + line + content[nl + 1:]
    else:
        content += f"\n{marker}\n\n{line}"

    path.write_text(content, encoding="utf-8")


def _process_lesson(event: dict) -> None:
    """Roll a lesson event into hot.md."""
    text = event.get("content", "")
    if not text:
        return

    hot = HOT_MD.read_text(encoding="utf-8") if HOT_MD.exists() else ""

    # Duplicate guard
    if text.strip() in hot:
        return

    marker = "## RECENT LESSONS"
    if marker not in hot:
        hot += f"\n\n{marker}\n\n- {text}\n"
    else:
        lines = hot.split("\n")
        insert_idx = len(lines)
        in_section = False
        for i, line in enumerate(lines):
            if marker in line:
                in_section = True
                continue
            if in_section and line.startswith("## "):
                insert_idx = i
                break
            if in_section and line.strip().startswith("- "):
                insert_idx = i + 1
        lines.insert(insert_idx, f"- {text}")
        hot = "\n".join(lines)

    HOT_MD.write_text(hot, encoding="utf-8")
    logger.info(f"Lesson rolled into hot.md: {text[:60]}...")


from store import Store
_store = Store()

def process_batch() -> int:
    """Process one batch of unprocessed events. Returns count processed."""
    cursor = get_cursor()
    events, new_cursor = _store.get_unprocessed(cursor, limit=50)
    if not events:
        return 0

    for event in events:
        etype = event.get("type", "")
        project = event.get("project", "")

        # Route by type
        if etype == "lesson":
            _process_lesson(event)

        # All project-tagged events go to warm files
        if project:
            slug = _slugify(project)
            _append_to_warm(slug, event)

    # Advance cursor
    set_cursor(new_cursor)
    logger.info(f"Processed {len(events)} events (cursor → {new_cursor})")
    return len(events)


async def run_event_processor(shutdown_event: asyncio.Event | None = None):
    """Background loop that processes events periodically."""
    logger.info(f"EventProcessor started (poll every {EVENT_POLL_INTERVAL}s)")

    while True:
        try:
            count = process_batch()
            if count > 0:
                logger.info(f"Batch complete: {count} events processed")
        except Exception as e:
            logger.error(f"Event processing failed: {e}")

        # Wait for next poll or shutdown
        if shutdown_event:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=EVENT_POLL_INTERVAL)
                break
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(EVENT_POLL_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_event_processor())
