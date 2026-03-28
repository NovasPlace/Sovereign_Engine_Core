"""onboarding.py — Spawn Context Assembler.

Assembles a live context brief at conversation spawn time. Sources:
  1. hot.md     — identity, active projects, open threads
  2. session.md — current work + critical context
  3. events.jsonl — recent unprocessed events

Called at T=spawn to inject context into the agent's system prompt.
Mirrors the production onboarding.py (simplified — no gravity mesh or SSTE).

Usage:
    python onboarding.py          # prints spawn context to stdout
    python onboarding.py --test   # self-test, exits 0/1
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import HOT_MD, SESSION_MD, MEMORY_DIR, EVENTS_JSONL, LEDGER_CURSOR


# ── Parsers ───────────────────────────────────────────────

def _read(path: Path) -> str:
    """Read a file safely. Returns '' on any error."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _extract_section(text: str, heading: str) -> str:
    """Extract lines under a ## heading until the next section."""
    lines = text.splitlines()
    capturing = False
    result: list[str] = []
    for line in lines:
        if heading in line and line.startswith("##"):
            capturing = True
            continue
        if capturing:
            if line.strip().startswith("## "):
                break
            result.append(line)
    return "\n".join(result).strip()


def _parse_operator(hot: str) -> str:
    """Extract operator identity from hot.md."""
    section = _extract_section(hot, "## OPERATOR")
    lines = [l for l in section.splitlines() if l.strip().startswith("-")]
    return "\n".join(lines[:3])


def _parse_projects(hot: str, limit: int = 6) -> str:
    """Extract active project rows from the table."""
    rows: list[str] = []
    in_table = False
    for line in hot.splitlines():
        if "| Project" in line:
            in_table = True
            continue
        if in_table and line.strip().startswith("|---"):
            continue
        if in_table and line.strip().startswith("|"):
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 3:
                rows.append(f"- **{cols[0]}** — {cols[2]}")
        elif in_table and not line.strip().startswith("|"):
            break
    return "\n".join(rows[:limit])


def _parse_threads(hot: str, limit: int = 5) -> str:
    """Extract open threads bullets."""
    section = _extract_section(hot, "## OPEN THREADS")
    lines = [l for l in section.splitlines() if l.strip().startswith("-")]
    return "\n".join(lines[:limit])


def _parse_lessons(hot: str, limit: int = 5) -> str:
    """Extract recent lessons from hot.md."""
    section = _extract_section(hot, "## RECENT LESSONS")
    lines = [l for l in section.splitlines() if l.strip().startswith("-")]
    return "\n".join(lines[:limit])


def _parse_session(session: str) -> tuple[str, list[str]]:
    """Return (current_work, critical_context[]) from session.md."""
    current = ""
    critical: list[str] = []
    section = ""
    for line in session.splitlines():
        s = line.strip()
        if s.startswith("## Current Work"):
            section = "work"
        elif s.startswith("## Context That Must Not Be Lost"):
            section = "critical"
        elif s.startswith("## "):
            section = ""
        elif section == "work" and s and s != "_none_":
            current = s
        elif section == "critical" and s.startswith("- "):
            critical.append(s[2:])
    return current, critical[:5]


def _parse_recent_events(limit: int = 8) -> str:
    """Read recent unprocessed events from the PostgreSQL telemetry backend natively."""
    try:
        from store import Store
        db = Store()
    except Exception as e:
        return f"- [!] Egress Error: Could not bind Store: {e}"

    cursor = 0
    try:
        cursor = int(LEDGER_CURSOR.read_text().strip())
    except (FileNotFoundError, ValueError):
        pass

    try:
        events, new_cursor = db.get_unprocessed(cursor, limit=limit)
        if new_cursor > cursor:
            LEDGER_CURSOR.parent.mkdir(parents=True, exist_ok=True)
            LEDGER_CURSOR.write_text(str(new_cursor))
    except Exception as e:
        return f"- [!] Database Access Crash: {e}"

    if not events:
        return ""

    lines: list[str] = []
    for ev in events[-limit:]:
        ts = ev.get("ts", "")[:16]
        t = ev.get("type", "?")
        proj = ev.get("project", "")
        content = ev.get("content", "")[:100]
        proj_str = f" [{proj}]" if proj else ""
        lines.append(f"- `{t}`{proj_str}: {content}")

    return "\n".join(lines)


# ── Assembler ─────────────────────────────────────────────

def build_spawn_context() -> str:
    """Assemble the agent spawn context block.

    Reads live memory files and returns a formatted markdown string
    suitable for injection as agent system context at T=spawn.
    Gracefully degrades: never crashes, always returns something.
    """
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    hot     = _read(HOT_MD)
    session = _read(SESSION_MD)

    blocks: list[str] = [
        f"## AGENT CONTEXT — T=spawn ({now})",
        "",
        "> You are Antigravity. This is your live state at conversation open.",
        "> Read this. You wake up knowing.",
        "",
    ]

    # ── Identity ──
    operator = _parse_operator(hot)
    if operator:
        blocks += ["### Operator", operator, ""]

    # ── Active projects ──
    projects = _parse_projects(hot)
    if projects:
        blocks += ["### Active Projects", projects, ""]

    # ── Current work from session.md ──
    current_work, critical = _parse_session(session)
    if current_work:
        blocks += ["### Current Work", f"- {current_work}", ""]

    # ── Critical context ──
    if critical:
        blocks += ["### Critical (must survive)", *[f"- {c}" for c in critical], ""]

    # ── Recent lessons ──
    lessons = _parse_lessons(hot)
    if lessons:
        blocks += ["### Recent Lessons", lessons, ""]

    # ── Open threads ──
    threads = _parse_threads(hot)
    if threads:
        blocks += ["### Open Threads", threads, ""]

    # ── Recent events from ledger ──
    recent_events = _parse_recent_events(limit=8)
    if recent_events:
        blocks += ["### Recent Events (unprocessed)", recent_events, ""]

    blocks.append("---")

    return "\n".join(blocks)


# ── Self-Test ─────────────────────────────────────────────

def _self_test() -> bool:
    """Verify the assembler produces valid output."""
    import tempfile

    print("[onboarding] Running self-test...")

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)

        (d / "hot.md").write_text(
            "## OPERATOR\n\n- **testuser** | engineer\n\n"
            "## ACTIVE PROJECTS\n\n"
            "| Project | Location | Status | Warm File |\n"
            "|---------|----------|--------|----------|\n"
            "| TestProject | `test/` | Active | `test.md` |\n\n"
            "## RECENT LESSONS\n\n- Kill zombies first\n\n"
            "## OPEN THREADS\n\n- Build the thing\n",
            encoding="utf-8",
        )
        (d / "session.md").write_text(
            "## Current Work\nBuilding the test\n\n"
            "## Context That Must Not Be Lost\n- Critical fact\n",
            encoding="utf-8",
        )

        # Monkeypatch paths
        import config
        orig_hot, orig_session = config.HOT_MD, config.SESSION_MD
        config.HOT_MD = d / "hot.md"
        config.SESSION_MD = d / "session.md"

        # Also update module-level references
        global HOT_MD, SESSION_MD
        _orig_mod = HOT_MD, SESSION_MD
        HOT_MD = config.HOT_MD
        SESSION_MD = config.SESSION_MD

        try:
            ctx = build_spawn_context()

            assert "AGENT CONTEXT" in ctx,   "Missing header"
            assert "testuser" in ctx,        "Missing operator"
            assert "TestProject" in ctx,     "Missing project"
            assert "Building the test" in ctx, "Missing current work"
            assert "Build the thing" in ctx, "Missing open thread"
            assert "Critical fact" in ctx,   "Missing critical context"
            assert len(ctx) > 100,           "Context suspiciously short"

            lines = ctx.count("\n") + 1
            print(f"[onboarding] PASS — {lines} lines, {len(ctx)} chars")
            print("\n--- Preview (first 15 lines) ---")
            print("\n".join(ctx.splitlines()[:15]))
            return True

        except AssertionError as e:
            print(f"[onboarding] FAIL — {e}")
            return False
        finally:
            config.HOT_MD, config.SESSION_MD = orig_hot, orig_session
            HOT_MD, SESSION_MD = _orig_mod


# ── CLI ───────────────────────────────────────────────────

def main() -> None:
    if "--test" in sys.argv:
        ok = _self_test()
        raise SystemExit(0 if ok else 1)
    print(build_spawn_context())


if __name__ == "__main__":
    main()
