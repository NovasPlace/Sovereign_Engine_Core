"""memory_reader.py — Async TCP server that caches and serves memory files.

Mirrors the production md_reader.py. Serves hot.md, session.md, and
warm project files over a localhost TCP socket with JSON protocol.

Commands:
    PING       → {"pong": true}
    GET_HOT    → {"ok": true, "content": "..."}
    GET_SESSION → {"ok": true, "content": "..."}
    GET_WARM   → {"ok": true, "content": "..."}  (requires "slug" param)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MEMORY_DIR, HOT_MD, SESSION_MD, PROJECTS_DIR, PORTS

logger = logging.getLogger("daemon.reader")

# In-memory cache with TTL
_cache: dict[str, tuple[str, float]] = {}
CACHE_TTL = 5.0  # seconds


def _read_cached(path: Path) -> str:
    """Read file with simple TTL cache."""
    key = str(path)
    now = time.time()
    if key in _cache:
        content, ts = _cache[key]
        if now - ts < CACHE_TTL:
            return content

    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""
    _cache[key] = (content, now)
    return content


def _dispatch(cmd_obj: dict) -> dict:
    """Route a command to its handler."""
    cmd = cmd_obj.get("cmd", "")

    if cmd == "PING":
        return {"pong": True}

    elif cmd == "GET_HOT":
        return {"ok": True, "content": _read_cached(HOT_MD)}

    elif cmd == "GET_SESSION":
        return {"ok": True, "content": _read_cached(SESSION_MD)}

    elif cmd == "GET_WARM":
        slug = cmd_obj.get("slug", "").strip().lower()
        if not slug:
            return {"ok": False, "error": "slug required"}
        # Sanitize slug to prevent path traversal
        slug = slug.replace("/", "").replace("\\", "").replace("..", "")
        path = PROJECTS_DIR / f"{slug}.md"
        return {"ok": True, "content": _read_cached(path)}

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


async def run_reader(shutdown_event: asyncio.Event | None = None):
    """Start the memory reader TCP server."""
    server = await asyncio.start_server(
        _handle_client, "127.0.0.1", PORTS.READER,
        reuse_address=True,
    )
    logger.info(f"MemoryReader listening on 127.0.0.1:{PORTS.READER}")

    async with server:
        if shutdown_event:
            await shutdown_event.wait()
            server.close()
        else:
            await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_reader())
