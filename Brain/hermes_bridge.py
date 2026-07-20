"""Hermes <-> JARVIS memory bridge.

JARVIS becomes the SOURCE of truth for project knowledge (its Memory/Projects/
directory already has 9 projects with structured data), but Hermes acts as
the INDEX and CROSS-PROJECT MEMORY layer on top.

Layout on disk (Hermes side):
    ~/.hermes/memories/
        memory.md          # global context: who is the user, what does Hermes know
        user.md            # user profile (preferences, tone, recurring corrections)
        jarvis_projects.md # AUTO-GENERATED INDEX of all JARVIS projects
        jarvis_journal.md  # one-line append-only log of JARVIS brain calls (Modo 4)

Reading: JARVIS brain injects Hermes context into the system prompt on demand.
Writing: JARVIS appends to jarvis_journal.md each time it serves an answer.
Sync: every call to get_hermes_context() re-reads the index from disk so
      JARVIS stays in sync without us writing custom diff logic.
"""

import os
import pathlib
import re
import time
from typing import Optional

# Resolve Hermes home cross-platform: %USERPROFILE%/.hermes/memories on Windows.
_HERMES_HOME = pathlib.Path(os.environ.get("HERMES_HOME", pathlib.Path.home() / ".hermes"))
_HERMES_MEM = _HERMES_HOME / "memories"
_HERMES_JOURNAL = _HERMES_MEM / "jarvis_journal.md"
_HERMES_PROJECTS_INDEX = _HERMES_MEM / "jarvis_projects.md"


def _safe_read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_append(p: pathlib.Path, line: str) -> bool:
    """Append a single line with timestamp. Returns True if written."""
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with p.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {line}\n")
        return True
    except Exception:
        return False


# ────────────────────────────────────────────────────────────────────
# Modo 2: Bidirectional bridge — index JARVIS projects into Hermes
# ────────────────────────────────────────────────────────────────────

def sync_projects_index(jarvis_projects: list[dict]) -> str:
    """Regenerate ~/.hermes/memories/jarvis_projects.md from current JARVIS list.

    Each entry: - <name> (`/projeto <slug>`) — last update: <date>
    Idempotent — safe to call every minute.
    """
    if not jarvis_projects:
        return ""

    lines = [
        "---",
        "name: JARVIS Projects Index",
        "description: Auto-synced index of JARVIS persistent projects (source of truth: JARVIS/Memory/Projects/)",
        "type: index",
        "synced_at: " + time.strftime("%Y-%m-%d %H:%M:%S"),
        "---",
        "",
        "# JARVIS Projects (synced)",
        "",
        f"Atualizado em {time.strftime('%Y-%m-%d %H:%M:%S')} — {len(jarvis_projects)} projetos ativos.",
        "",
    ]
    for p in jarvis_projects:
        slug = p.get("slug", "")
        name = p.get("name", slug)
        # Best-effort: read mtime of the project file for "last update"
        last = ""
        try:
            path = pathlib.Path(p.get("path", ""))
            if path.exists():
                last = time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))
        except Exception:
            pass
        line = f"- {name} (`/projeto {slug}`)"
        if last:
            line += f" — última atualização {last}"
        lines.append(line)
    lines.append("")
    lines.append("> Fonte: JARVIS Brain/memory.list_projects()")
    lines.append("")

    try:
        _HERMES_PROJECTS_INDEX.parent.mkdir(parents=True, exist_ok=True)
        _HERMES_PROJECTS_INDEX.write_text("\n".join(lines), encoding="utf-8")
        return str(_HERMES_PROJECTS_INDEX)
    except Exception as exc:
        return f"ERROR: {exc}"


# ────────────────────────────────────────────────────────────────────
# Modo 1: Snapshot for system prompt (cached 5 minutes)
# ────────────────────────────────────────────────────────────────────

_CACHE: dict = {"ts": 0.0, "text": "", "projects_index": ""}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def invalidate_cache() -> None:
    """Drop the cache so the next get_hermes_context() re-reads disk."""
    _CACHE["ts"] = 0.0
    _CACHE["text"] = ""


def get_hermes_context(jarvis_projects: Optional[list[dict]] = None, force_refresh: bool = False) -> str:
    """Return a compact context block with Hermes memory + projects index.

    Strategy:
      1. Re-sync JARVIS projects index into ~/.hermes (cheap file write).
      2. Read ~/.hermes/memories/{memory,user,jarvis_projects}.md
      3. Cache the result for 5 minutes; pass force_refresh=True to bypass.

    Returns empty string if Hermes home is missing or unreadable.
    """
    now = time.time()
    if not force_refresh and _CACHE["text"] and (now - _CACHE["ts"]) < _CACHE_TTL_SECONDS:
        return _CACHE["text"]

    # 1. Refresh project index if we have a fresh list from JARVIS.
    if jarvis_projects is not None:
        sync_projects_index(jarvis_projects)

    # 2. Read Hermes memory files (cap to keep prompt small).
    memory = _safe_read(_HERMES_MEM / "memory.md")[:1500]
    user = _safe_read(_HERMES_MEM / "user.md")[:1200]
    proj_index = _safe_read(_HERMES_PROJECTS_INDEX)[:2000]

    parts = ["CONTEXTO HERMES (memória compartilhada entre Hermes e JARVIS):\n"]
    if memory:
        parts.append(f"Memória global Hermes:\n{memory}\n")
    if user:
        parts.append(f"Perfil do usuário (Hermes):\n{user}\n")
    if proj_index:
        parts.append(f"Índice de projetos JARVIS:\n{proj_index}\n")

    text = "\n".join(parts).strip()
    _CACHE["ts"] = now
    _CACHE["text"] = text
    return text


# ────────────────────────────────────────────────────────────────────
# Modo 4: Journal append-only log of JARVIS brain activity
# ────────────────────────────────────────────────────────────────────

def append_journal(user_text: str, ai_text: str, project_slug: Optional[str] = None) -> bool:
    """Append a one-line entry to ~/.hermes/jarvis_journal.md.

    Format: [<ts>] user=<80 chars> | ai=<80 chars> | project=<slug or '-'>
    Hermes reads this file at the start of every session to recall
    "what was JARVIS up to yesterday".
    """
    def _trim(s: str, n: int = 120) -> str:
        s = (s or "").replace("\n", " ").replace("\r", " ").strip()
        return s[:n] + ("..." if len(s) > n else "")

    line = (
        f"user=\"{_trim(user_text)}\" | "
        f"ai=\"{_trim(ai_text)}\" | "
        f"project={project_slug or '-'}"
    )
    return _safe_append(_HERMES_JOURNAL, line)


def read_journal(last_n: int = 50) -> str:
    """Return the last `last_n` lines of the JARVIS journal (Hermes-friendly)."""
    if not _HERMES_JOURNAL.exists():
        return ""
    try:
        text = _HERMES_JOURNAL.read_text(encoding="utf-8")
        lines = [l for l in text.splitlines() if l.strip()]
        return "\n".join(lines[-last_n:])
    except Exception:
        return ""


def journal_stats() -> dict:
    """Quick stats for the UI tile: total entries, last entry, size."""
    if not _HERMES_JOURNAL.exists():
        return {"exists": False, "entries": 0, "size_bytes": 0}
    try:
        text = _HERMES_JOURNAL.read_text(encoding="utf-8")
        lines = [l for l in text.splitlines() if l.strip()]
        return {
            "exists": True,
            "entries": len(lines),
            "size_bytes": len(text.encode("utf-8")),
            "path": str(_HERMES_JOURNAL),
            "last": lines[-1] if lines else "",
        }
    except Exception:
        return {"exists": False, "entries": 0, "size_bytes": 0}
