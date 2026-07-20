"""Persistent memory module.

Reads/writes the Memory/ directory and exposes helpers that the brain
and the dashboard use to look up projects, decisions and tasks.

Layout on disk:
    Memory/
        MEMORY.md          # index
        decisions.md       # cross-project decisions log
        tasks.md           # global pending tasks
        Projects/
            <slug>.md      # one file per project
"""

import pathlib
import re
from typing import Iterable


_MEMORY_DIR = pathlib.Path(__file__).resolve().parent.parent / "Memory"
_PROJECTS_DIR = _MEMORY_DIR / "Projects"
_INDEX = _MEMORY_DIR / "MEMORY.md"


def _safe_read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_write(p: pathlib.Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def list_projects() -> list[dict]:
    """Return [{slug, name, path}] for every project file found."""
    if not _PROJECTS_DIR.exists():
        return []
    out = []
    for f in sorted(_PROJECTS_DIR.glob("*.md")):
        slug = f.stem
        text = _safe_read(f)
        name = slug
        m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if m:
            name = m.group(1).strip()
        out.append({"slug": slug, "name": name, "path": str(f)})
    return out


def read_project(slug: str) -> str | None:
    """Return the full markdown of a project file, or None if not found."""
    p = _PROJECTS_DIR / f"{slug}.md"
    if not p.exists():
        return None
    return _safe_read(p)


def detect_project(text: str) -> str | None:
    """Best-effort: if `text` mentions a project name, return its slug.

    Matching is fuzzy — case-insensitive substring on the human-readable
    name. Returns None when nothing matches.
    """
    if not text:
        return None
    haystack = text.lower()
    candidates = sorted(
        list_projects(),
        key=lambda x: len(x["name"]),
        reverse=True,  # longest first so "Pollar Agência" wins over "Pollar"
    )
    for p in candidates:
        if p["name"].lower() in haystack:
            return p["slug"]
    return None


def update_project(slug: str, section: str, addition: str) -> str:
    """Append `addition` under `## section` in a project file.

    Creates the section if missing. Returns the new file path.
    """
    p = _PROJECTS_DIR / f"{slug}.md"
    if not p.exists():
        raise FileNotFoundError(f"project {slug} not found")
    content = _safe_read(p)
    header = f"## {section}"
    if header in content:
        content = content.replace(header, header + "\n" + addition, 1)
    else:
        content = content.rstrip() + f"\n\n## {section}\n{addition}\n"
    _safe_write(p, content)
    return str(p)


def get_global_context() -> str:
    """Return a compact context block with index + global decisions + tasks.

    Used by the brain to ground every reply in the user's actual projects.
    """
    projects = list_projects()
    if not projects:
        return ""

    project_lines = "\n".join(f"- {p['name']} (`/projeto {p['slug']}`)" for p in projects)
    decisions = _safe_read(_MEMORY_DIR / "decisions.md")
    tasks = _safe_read(_MEMORY_DIR / "tasks.md")
    persona = _safe_read(_MEMORY_DIR / "jarvis-persona.md")
    integrations = _safe_read(_MEMORY_DIR / "integrations.md")

    # Cap to keep prompts reasonable.
    decisions_short = decisions[:1500]
    tasks_short = tasks[:1000]
    persona_short = persona[:2000]
    integrations_short = integrations[:2500]  # Gmail + Calendar

    sections = [
        "CONTEXTO GLOBAL DO JARVIS (memória persistente):\n\n"
        f"Projetos conhecidos do usuário:\n{project_lines}\n\n"
        f"Constituição cognitiva (persona):\n{persona_short}\n\n"
        f"Decisões globais recentes:\n{decisions_short}\n\n"
        f"Tarefas globais pendentes:\n{tasks_short}\n"
    ]
    if integrations_short:
        sections.append(f"\nIntegrações externas conectadas (Gmail, Calendar, etc):\n{integrations_short}\n")

    return "".join(sections)


def get_project_context(slug: str) -> str:
    """Return a project's markdown, capped, for inclusion in a prompt."""
    content = read_project(slug)
    if not content:
        return ""
    return f"\n\nDETALHES DO PROJETO ({slug}):\n" + content[:2500]