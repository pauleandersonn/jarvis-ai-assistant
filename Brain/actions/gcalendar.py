"""Calendar action — listar, criar, deletar eventos.

Wrapper sobre a skill `google-workspace` (Google Calendar API v3).

Funcoes expostas:
  - list_events(start, end, max_results)  -> lista de dicts
  - create_event(summary, start_iso, end_iso, location, description, attendees)
  - delete_event(event_id)
  - summarize_agenda(start, end)          -> string TTS-friendly

ISO 8601 com timezone: "2026-07-21T14:00:00-03:00" ou "2026-07-21T14:00:00Z".
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = logging.getLogger("jarvis.actions.calendar")

_GAPI_PATH = (
    Path.home()
    / "AppData"
    / "Local"
    / "hermes"
    / "skills"
    / "productivity"
    / "google-workspace"
    / "scripts"
    / "google_api.py"
)


def _run_gapi(*args: str, timeout: int = 30) -> tuple[bool, str]:
    """Roda google_api.py com os args dados."""
    if not _GAPI_PATH.exists():
        return False, f"google-workspace skill nao encontrada em {_GAPI_PATH}"

    cmd = [sys.executable, str(_GAPI_PATH), *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "unknown error").strip()
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, f"timeout apos {timeout}s"
    except Exception as e:
        return False, f"execucao falhou: {e}"


def list_events(
    start: str | None = None,
    end: str | None = None,
    max_results: int = 25,
) -> dict:
    """Lista eventos entre `start` e `end` (ISO 8601). Default: proximos 7 dias UTC."""
    if start is None:
        start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if end is None:
        end_dt = datetime.now(timezone.utc) + timedelta(days=7)
        end = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    ok, out = _run_gapi(
        "calendar", "list",
        "--start", start,
        "--end", end,
        "--max", str(max_results),
    )
    if not ok:
        return {"ok": False, "error": out}
    try:
        events = json.loads(out)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"resposta nao e JSON: {out[:200]}"}

    if not isinstance(events, list):
        return {"ok": False, "error": f"formato inesperado: {type(events).__name__}"}

    return {"ok": True, "count": len(events), "events": events}


def create_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    location: str | None = None,
    description: str | None = None,
    attendees: list[str] | None = None,
) -> dict:
    """Cria evento no calendario primario.

    CONFIRMAR COM USUARIO ANTES (vai pro Calendar oficial).
    """
    if not summary.strip():
        return {"ok": False, "error": "summary vazio"}
    if not start_iso or not end_iso:
        return {"ok": False, "error": "start_iso/end_iso obrigatorios"}

    args = [
        "calendar", "create",
        "--summary", summary,
        "--start", start_iso,
        "--end", end_iso,
    ]
    if location:
        args.extend(["--location", location])
    if description:
        args.extend(["--description", description])
    if attendees:
        args.extend(["--attendees", ",".join(attendees)])

    ok, out = _run_gapi(*args, timeout=30)
    if not ok:
        return {"ok": False, "error": out}
    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        return {"ok": True, "raw_response": out[:200]}
    return {"ok": result.get("status") == "created", "event": result}


def delete_event(event_id: str) -> dict:
    """Deleta evento por ID (vai pra lixeira)."""
    if not event_id:
        return {"ok": False, "error": "event_id vazio"}
    ok, out = _run_gapi("calendar", "delete", event_id)
    if not ok:
        return {"ok": False, "error": out}
    return {"ok": True, "deleted_id": event_id}


def summarize_agenda(
    start: str | None = None,
    end: str | None = None,
    max_events: int = 5,
) -> str:
    """Retorna string natural pra TTS com a agenda do periodo."""
    res = list_events(start=start, end=end, max_results=max_events)
    if not res.get("ok"):
        return f"Nao consegui ler a agenda: {res.get('error')}"

    events = res.get("events", [])
    if not events:
        return "Sua agenda esta livre nesse periodo."

    lines = [f"O senhor tem {len(events)} compromisso(s):"]  # sem cedilha
    for i, e in enumerate(events, 1):
        summary = e.get("summary") or "(sem titulo)"
        start_str = e.get("start", "")
        # Tenta extrair data+hora de formatos comuns
        time_str = _humanize_when(start_str)
        where = f" em {e['location']}" if e.get("location") else ""
        lines.append(f"{i}: {summary}{time_str}{where}.")
    return " ".join(lines)


def _humanize_when(iso_str: str) -> str:
    """Converte ISO 8601 pra "amanha as 14h" ou "hoje as 9h" ou "21/07 14h"."""
    if not iso_str:
        return ""
    # Pode ser "2026-07-21T14:00:00-03:00" ou "2026-07-21" (all-day)
    try:
        if "T" in iso_str:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            local = dt.astimezone()  # converte pra local
            now = datetime.now().astimezone()
            day_diff = (local.date() - now.date()).days
            time_part = local.strftime("%H:%M").lstrip("0")
            if day_diff == 0:
                return f" hoje as {time_part}"
            elif day_diff == 1:
                return f" amanha as {time_part}"
            elif day_diff < 7:
                weekday = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
                return f" {weekday[local.weekday()]} as {time_part}"
            else:
                return f" em {local.strftime('%d/%m')} as {time_part}"
        else:
            # all-day: "2026-07-21"
            dt = datetime.fromisoformat(iso_str)
            now = datetime.now()
            day_diff = (dt.date() - now.date()).days
            if day_diff == 0:
                return " hoje (dia inteiro)"
            elif day_diff == 1:
                return " amanha (dia inteiro)"
            else:
                return f" em {dt.strftime('%d/%m')} (dia inteiro)"
    except (ValueError, AttributeError):
        return f" em {iso_str}"


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "agenda"
    if cmd == "agenda":
        print(summarize_agenda())
    elif cmd == "list":
        r = list_events()
        print(json.dumps(r, indent=2, ensure_ascii=False))
    elif cmd == "create":
        if len(sys.argv) < 5:
            print("uso: create <summary> <start_iso> <end_iso> [location]")
        else:
            r = create_event(sys.argv[2], sys.argv[3], sys.argv[4],
                             sys.argv[5] if len(sys.argv) > 5 else None)
            print(json.dumps(r, indent=2, ensure_ascii=False))