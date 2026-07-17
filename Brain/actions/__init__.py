"""JARVIS adapter for Mark-XLIX reminder + open_app.

Importa os módulos adaptados de Mark-XLIX (FatihMakes, CC BY-NC 4.0) e expõe
funções com a assinatura esperada pelo nosso dashboard.py.
"""

from __future__ import annotations

import logging
import platform
import sys
from datetime import datetime, timedelta
from pathlib import Path

LOG = logging.getLogger("jarvis.actions")

# Garante import do módulo original
_ACTIONS_DIR = Path(__file__).resolve().parent
if str(_ACTIONS_DIR) not in sys.path:
    sys.path.insert(0, str(_ACTIONS_DIR))

try:
    import reminder as _reminder_mod
    import open_app as _openapp_mod
    HAVE_REMINDER = True
    HAVE_OPENAPP = True
except Exception as e:
    LOG.warning("Mark-XLIX actions import failed: %s", e)
    HAVE_REMINDER = False
    HAVE_OPENAPP = False


# ───────────── Reminders ─────────────

def add_reminder(message: str, minutes: int) -> dict:
    """Schedule a reminder N minutes from now via Windows Task Scheduler (schtasks).

    Internamente usa Mark-XLIX reminder.reminder() — agendamento real,
    não sleep em background.
    """
    if not HAVE_REMINDER:
        return {"ok": False, "error": "reminder module not available"}

    minutes = max(1, min(int(minutes), 24 * 60 * 7))  # 1 min .. 7 dias
    target_dt = datetime.now() + timedelta(minutes=minutes)
    date_str = target_dt.strftime("%Y-%m-%d")
    time_str = target_dt.strftime("%H:%M")

    try:
        # A função `reminder` é a entrypoint tool-callable do Mark-XLIX
        _reminder_mod.reminder(parameters={
            "date": date_str,
            "time": time_str,
            "message": (message or "Lembrete JARVIS").strip(),
        })
        return {
            "ok": True,
            "task_name": f"JARVISReminder_{target_dt.strftime('%Y%m%d_%H%M%S')}",
            "trigger_time": target_dt.isoformat(timespec="seconds"),
            "message": message,
            "in_minutes": minutes,
        }
    except Exception as e:
        LOG.exception("add_reminder failed")
        return {"ok": False, "error": str(e)}


def list_reminders() -> list[dict]:
    """Lista lembretes JARVIS agendados via schtasks query."""
    if not platform.system().lower() == "windows":
        return []
    import subprocess
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/FO", "CSV", "/V"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return []
        # Filter only JARVIS tasks
        tasks = []
        for line in result.stdout.splitlines():
            if "JARVIS" in line.upper():
                tasks.append({"raw": line.strip()[:300]})
        return tasks[:20]
    except Exception as e:
        LOG.warning("list_reminders failed: %s", e)
        return []


def remove_reminder(task_name: str) -> dict:
    """Remove a scheduled reminder by name."""
    import subprocess
    if not task_name or not task_name.upper().startswith("JARVIS"):
        return {"ok": False, "error": "task_name deve começar com JARVIS (segurança)"}
    try:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            capture_output=True, text=True, timeout=10,
        )
        return {"ok": result.returncode == 0, "task_name": task_name}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ───────────── Open apps ─────────────

def open_app(query: str) -> dict:
    """Open an application by friendly name.

    O modulo Mark-XLIX open_app expoe apenas open_app(query) que detecta
    a plataforma internamente (Windows/Darwin/Linux) e abre via aliases.
    """
    if not HAVE_OPENAPP:
        return {"ok": False, "error": "open_app module not available"}

    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "query vazio"}

    system = platform.system()  # Windows / Linux / Darwin
    # Mark-XLIX usa 'print' com chars Unicode (→) que quebram em consoles cp1252.
    # Redirecionamos stdout/stderr pra /dev/null durante a chamada pra silenciar
    # esses prints e evitar UnicodeEncodeError. O retorno da funcao ja vem
    # como string com a mensagem descritiva.
    import contextlib as _ctxlib
    import io as _io
    try:
        devnull = open(os.devnull, "w", encoding="utf-8", errors="replace")
    except Exception:
        devnull = _io.StringIO()

    with _ctxlib.redirect_stdout(devnull), _ctxlib.redirect_stderr(devnull):
        try:
            result = _openapp_mod.open_app(parameters={"app_name": query})
        except Exception as e:
            result = f"Error: {e}"
    try:
        devnull.close()
    except Exception:
        pass

    result_str = result if isinstance(result, str) else str(result)
    # Limpa nao-ASCII pra JSONResponse nao reclamar (charmap no Windows).
    result_str = result_str.encode("ascii", errors="replace").decode("ascii")
    success = result_str.lower().startswith(("opened", "success", "launched"))
    return {
        "ok": success,
        "query": query,
        "method": "open_app",
        "launched": result_str,
        "platform": system,
    }


# ───────────── Self-test ─────────────

if __name__ == "__main__":
    import json
    print(json.dumps({
        "HAVE_REMINDER": HAVE_REMINDER,
        "HAVE_OPENAPP": HAVE_OPENAPP,
        "reminders_count": len(list_reminders()),
    }, indent=2, ensure_ascii=False, default=str))