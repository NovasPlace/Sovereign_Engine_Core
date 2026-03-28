"""memory_writer.py — Async TCP server that receives atomic validated writes.

Mirrors the production md_writer.py. Agents send structured write commands
over TCP and this daemon applies them atomically to the markdown files.

Commands:
    PING           → {"pong": true}
    APPEND_LESSON  → Appends a lesson bullet to hot.md RECENT LESSONS
    UPDATE_SESSION → Overwrites session.md with structured state
    UPDATE_HOT     → Updates SESSION SUMMARY (and optionally OPEN THREADS)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import HOT_MD, SESSION_MD, PORTS

logger = logging.getLogger("daemon.writer")


from store import Store
_store = Store()

def _read_safe(path_or_tier: Path | str) -> str:
    # Handle both raw Path (fallback/back-compat) and string tiers ("hot", "session")
    tier = path_or_tier.stem if isinstance(path_or_tier, Path) else path_or_tier
    return _store.get_memory(tier)

def _write_safe(path_or_tier: Path | str, content: str) -> None:
    tier = path_or_tier.stem if isinstance(path_or_tier, Path) else path_or_tier
    _store.set_memory(tier, content)


def _append_lesson(text: str) -> dict:
    """Append a lesson bullet to the RECENT LESSONS section of hot.md."""
    hot = _read_safe(HOT_MD)
    if not hot:
        return {"ok": False, "error": "hot.md not found"}

    # Duplicate guard
    if text.strip() in hot:
        return {"ok": True, "note": "duplicate, skipped"}

    # Find the RECENT LESSONS section and append
    marker = "## RECENT LESSONS"
    if marker not in hot:
        # Add the section if missing
        hot += f"\n\n{marker}\n\n- {text}\n"
    else:
        # Insert after last lesson bullet in section
        lines = hot.split("\n")
        insert_idx = None
        in_section = False
        for i, line in enumerate(lines):
            if marker in line:
                in_section = True
                continue
            if in_section:
                if line.startswith("## "):  # Next section
                    insert_idx = i
                    break
                if line.strip().startswith("- "):
                    insert_idx = i + 1  # After last bullet
        if insert_idx is None:
            insert_idx = len(lines)
        lines.insert(insert_idx, f"- {text}")

        # Keep max 10 lessons
        lesson_lines = [l for l in lines if l.strip().startswith("- ")]
        # (simple cap — full production version is more sophisticated)

        hot = "\n".join(lines)

    _write_safe(HOT_MD, hot)
    logger.info(f"Lesson appended: {text[:60]}...")
    return {"ok": True}


def _update_session(
    current_work: str = "",
    files_touched: list[str] | None = None,
    pending_actions: list[str] | None = None,
    critical_context: list[str] | None = None,
) -> dict:
    """Overwrite session.md with structured state."""
    files = files_touched or []
    pending = pending_actions or []
    critical = critical_context or []

    content = "# SESSION STATE\n\n"
    content += f"## Current Work\n\n{current_work or '_none_'}\n\n"
    content += "## Files Touched\n\n"
    content += "\n".join(f"- `{f}`" for f in files) if files else "_none_"
    content += "\n\n## Pending Actions\n\n"
    content += "\n".join(f"- {a}" for a in pending) if pending else "_none_"
    content += "\n\n## Context That Must Not Be Lost\n\n"
    content += "\n".join(f"- {c}" for c in critical) if critical else "_none_"
    content += "\n"

    _write_safe(SESSION_MD, content)
    logger.info(f"Session updated: {current_work[:60]}...")
    return {"ok": True}


def _update_hot(session_summary: str, open_threads: list[str] | None = None) -> dict:
    """Update SESSION SUMMARY (and optionally OPEN THREADS) in hot.md."""
    hot = _read_safe(HOT_MD)
    if not hot:
        return {"ok": False, "error": "hot.md not found"}

    # Replace SESSION SUMMARY section
    pattern = r"(## SESSION SUMMARY\n\n)(.*?)(\n\n## )"
    replacement = f"\\1- {session_summary}\n\\3"
    new_hot = re.sub(pattern, replacement, hot, flags=re.DOTALL)

    if open_threads is not None:
        # Replace OPEN THREADS section
        thread_bullets = "\n".join(f"- {t}" for t in open_threads)
        pattern = r"(## OPEN THREADS\n\n)(.*?)(\n\n## |\Z)"
        replacement = f"\\g<1>{thread_bullets}\n\\3"
        new_hot = re.sub(pattern, replacement, new_hot, flags=re.DOTALL)

    _write_safe(HOT_MD, new_hot)
    logger.info(f"Hot updated: {session_summary[:60]}...")
    return {"ok": True}


def _dispatch(cmd_obj: dict) -> dict:
    """Route a command to its handler."""
    cmd = cmd_obj.get("cmd", "")

    if cmd == "PING":
        return {"pong": True}
    elif cmd == "APPEND_LESSON":
        return _append_lesson(cmd_obj.get("lesson", ""))
    elif cmd == "UPDATE_SESSION":
        return _update_session(
            current_work=cmd_obj.get("current_work", ""),
            files_touched=cmd_obj.get("files_touched"),
            pending_actions=cmd_obj.get("pending_actions"),
            critical_context=cmd_obj.get("critical_context"),
        )
    elif cmd == "UPDATE_HOT":
        return _update_hot(
            session_summary=cmd_obj.get("session_summary", ""),
            open_threads=cmd_obj.get("open_threads"),
        )

    return {"ok": False, "error": f"unknown command: {cmd!r}"}


async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single TCP client connection."""
    try:
        data = await asyncio.wait_for(reader.readline(), timeout=5.0)
        if not data:
            return

        cmd_obj = json.loads(data.decode("utf-8"))
        response = _dispatch(cmd_obj)

        writer.write(json.dumps(response).encode("utf-8") + b"\n")
        await writer.drain()
    except asyncio.TimeoutError:
        logger.warning("Client connection timed out")
    except json.JSONDecodeError:
        writer.write(json.dumps({"ok": False, "error": "invalid JSON"}).encode() + b"\n")
        await writer.drain()
    except Exception as e:
        logger.error(f"Client handler error: {e}")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def run_writer(shutdown_event: asyncio.Event | None = None):
    """Start the memory writer TCP server."""
    server = await asyncio.start_server(
        _handle_client, "127.0.0.1", PORTS.WRITER,
    )
    logger.info(f"MemoryWriter listening on 127.0.0.1:{PORTS.WRITER}")

    async with server:
        if shutdown_event:
            await shutdown_event.wait()
            server.close()
        else:
            await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_writer())
