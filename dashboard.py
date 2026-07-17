"""Jarvis Dashboard — FastAPI app.

Run with:
    python dashboard.py
Then open http://localhost:8765 in your browser.

This dashboard reads live state from the cleaned-up jarvis-ai-assistant
modules so it never has to talk to jarvis.py directly. That keeps the
two layers independent and the dashboard safe to restart at any time.
"""

import os
import pathlib
import sys
import threading
import time
from datetime import datetime

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Make the project modules importable when we run from anywhere.
PROJECT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

# ---- Lazy / safe imports for jarvis subsystems ----
import pyaudio  # resolves to the sounddevice-based shim in this project

# Track when we started, for the "uptime" tile.
STARTED_AT = time.time()

# File the brain appends to. We surface its contents in the UI.
CHAT_LOG = PROJECT_DIR / "chat_hystory.txt"
LOG_FILE = PROJECT_DIR / "log.txt"

# WebSocket clients that are currently connected to /ws/logs.
_ws_clients: set[WebSocket] = set()
_ws_lock = threading.Lock()


# ---------- FastAPI app ----------
app = FastAPI(title="Jarvis Dashboard", version="1.0.0")


# Serve the static frontend from ./dashboard_static
STATIC_DIR = PROJECT_DIR / "dashboard_static"
STATIC_DIR.mkdir(exist_ok=True)
# Servido via rota customizada /static/{file_path:path} abaixo (com no-cache).
# (Mantido comentado caso queira voltar ao StaticFiles padrão.)
# app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Return the main dashboard page."""
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        return "<h1>dashboard_static/index.html missing</h1>"
    return html_path.read_text(encoding="utf-8")


# ---------- Static files com no-cache (evita JS/CSS velho em cache) ----------
# Em produção você trocaria por StaticFiles mountado com hash nos nomes
# dos arquivos. Em dev, no-cache garante que cada reload pega a versão nova.
_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/static/{file_path:path}", include_in_schema=False)
def static_files(file_path: str) -> Response:
    """Serve arquivos de dashboard_static/ sem cache.

    Bloqueia path traversal (não permite .. ou caminhos absolutos).
    """
    safe = (file_path or "").lstrip("/")
    if ".." in safe or safe.startswith("/"):
        return Response(content="forbidden", status_code=403)
    full = (STATIC_DIR / safe).resolve()
    if not str(full).startswith(str(STATIC_DIR.resolve())):
        return Response(content="forbidden", status_code=403)
    if not full.exists() or not full.is_file():
        return Response(content="not found", status_code=404)
    # MIME simples
    suffix = full.suffix.lower()
    mime = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".ico": "image/x-icon",
        ".json": "application/json",
        ".woff2": "font/woff2",
    }.get(suffix, "application/octet-stream")
    return Response(
        content=full.read_bytes(),
        media_type=mime,
        headers=_NO_CACHE,
    )


# ---------- Favicon (corta 404 do /favicon.ico automático do navegador) ----------
@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> Response:
    """Retorna um SVG inline como favicon para silenciar o 404 automático do navegador.
    O SVG é o mesmo gradiente do logo JARVIS (azul→roxo→ciano)."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<defs><radialGradient id="g" cx="30%" cy="30%">'
        '<stop offset="0" stop-color="#22D3EE"/>'
        '<stop offset="0.5" stop-color="#5B6CFF"/>'
        '<stop offset="1" stop-color="#A855F7"/>'
        '</radialGradient></defs>'
        '<circle cx="16" cy="16" r="14" fill="url(#g)"/>'
        '</svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")


# ---------- Status endpoint ----------
@app.get("/api/status")
def status() -> JSONResponse:
    """Return current state of every subsystem the dashboard knows about."""
    uptime = int(time.time() - STARTED_AT)

    # Mic info via the pyaudio shim
    try:
        pa = pyaudio.PyAudio()
        mic_count = pa.get_device_count()
        mic_name = pa.get_default_input_device_info().get("name", "unknown")
        pa.terminate()
    except Exception as exc:  # noqa: BLE001
        mic_count = 0
        mic_name = f"error: {exc}"

    # Volume
    volume_pct = -1
    try:
        from Features.set_get_volume import _volume_control
        vol = _volume_control()
        volume_pct = int(round(vol.GetMasterVolumeLevelScalar() * 100))
    except Exception:
        pass

    # Brightness
    brightness_pct = -1
    try:
        import wmi
        c = wmi.WMI(namespace="wmi")
        brightness_pct = int(c.WmiMonitorBrightness()[0].CurrentBrightness)
    except Exception:
        pass

    # Battery
    battery = None
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is not None:
            battery = {
                "percent": int(b.percent),
                "plugged": bool(b.power_plugged),
            }
    except Exception:
        pass

    # Last brain response (last "AI:" line in chat history)
    last_ai = ""
    try:
        if CHAT_LOG.exists():
            content = CHAT_LOG.read_text(encoding="utf-8")
            for line in reversed(content.splitlines()):
                if line.startswith("AI:"):
                    last_ai = line[3:].strip()
                    break
    except Exception:
        pass

    return JSONResponse({
        "uptime_seconds": uptime,
        "started_at": datetime.fromtimestamp(STARTED_AT).strftime("%Y-%m-%d %H:%M:%S"),
        "mic": {"name": mic_name, "devices": mic_count, "ok": mic_count > 0},
        "volume": volume_pct,
        "brightness": brightness_pct,
        "battery": battery,
        "last_ai_response": last_ai,
        # What AI engine is currently wired to the brain endpoint.
        # Keep this in sync with Brain/brain.py — currently FreeAI from
        # the `webscout` package (no API key required).
        "ai_name": "FreeAI",
        "ai_provider": "webscout",
        "ai_notes": "free, no API key, no login",
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })


# ---------- Chat history ----------
@app.get("/api/chat")
def chat_history(limit: int = 50) -> JSONResponse:
    """Return the most recent `limit` exchanges from chat_hystory.txt."""
    try:
        if not CHAT_LOG.exists():
            return JSONResponse({"messages": []})
        content = CHAT_LOG.read_text(encoding="utf-8").strip()
        if not content:
            return JSONResponse({"messages": []})
        # Parse "User: ...\nAI: ..." blocks
        messages = []
        lines = content.splitlines()
        i = 0
        while i < len(lines) and len(messages) < limit * 2:
            if lines[i].startswith("User:"):
                u = lines[i][5:].strip()
                a = ""
                if i + 1 < len(lines) and lines[i + 1].startswith("AI:"):
                    a = lines[i + 1][3:].strip()
                    i += 2
                else:
                    i += 1
                messages.append({"user": u, "ai": a})
            else:
                i += 1
        # Keep only the most recent `limit`
        return JSONResponse({"messages": messages[-limit:]})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=500)


# ---------- Command endpoints ----------
# ---------- System info (real) ----------
@app.get("/api/system")
def system_info() -> JSONResponse:
    """Return live system metrics: CPU, RAM, disk, uptime, integrations."""
    import psutil

    # CPU: psutil.cpu_percent needs a small interval to be meaningful.
    cpu = psutil.cpu_percent(interval=None)

    # RAM
    mem = psutil.virtual_memory()

    # Disk for the project root
    try:
        disk = psutil.disk_usage(str(PROJECT_DIR))
        disk_pct = disk.percent
        disk_free_gb = round(disk.free / (1024 ** 3), 1)
    except Exception:
        disk_pct = -1
        disk_free_gb = -1.0

    # Internet connectivity (cheap HEAD request to a stable endpoint)
    internet_ok = False
    try:
        requests.get("https://duckduckgo.com", timeout=3)
        internet_ok = True
    except Exception:
        pass

    # Battery
    battery = None
    try:
        b = psutil.sensors_battery()
        if b is not None:
            battery = {
                "percent": int(b.percent),
                "plugged": bool(b.power_plugged),
            }
    except Exception:
        pass

    # Boot time
    boot_ts = psutil.boot_time()
    boot_dt = datetime.fromtimestamp(boot_ts).strftime("%Y-%m-%d %H:%M:%S")

    return JSONResponse({
        "cpu_percent": cpu,
        "ram_percent": mem.percent,
        "ram_used_gb": round(mem.used / (1024 ** 3), 1),
        "ram_total_gb": round(mem.total / (1024 ** 3), 1),
        "disk_percent": disk_pct,
        "disk_free_gb": disk_free_gb,
        "internet_ok": internet_ok,
        "battery": battery,
        "boot_at": boot_dt,
        "process_uptime_seconds": int(time.time() - STARTED_AT),
    })


@app.get("/api/integrations")
def integrations() -> JSONResponse:
    """Report which integrations / tools are currently wired up.

    'available' means the module is importable; 'connected' is true if
    the integration would actually work (e.g. mic device present).
    """
    out = []

    # Voice / mic — via the pyaudio shim
    mic_ok = False
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        mic_ok = pa.get_device_count() > 0
        pa.terminate()
    except Exception:
        pass
    out.append({"name": "Microfone", "available": mic_ok, "connected": mic_ok})

    # TTS
    tts_ok = False
    try:
        import win32com.client  # noqa: F401
        tts_ok = True
    except Exception:
        pass
    out.append({"name": "TTS (voz)", "available": tts_ok, "connected": tts_ok})

    # Brain (FreeAI via webscout)
    brain_ok = False
    try:
        from webscout import FreeAI  # noqa: F401
        brain_ok = True
    except Exception:
        pass
    out.append({"name": "Cérebro (FreeAI)", "available": brain_ok, "connected": brain_ok})

    # Web research (DDG + FreeAI)
    web_ok = False
    try:
        import ddgs  # noqa: F401
        web_ok = True
    except ImportError:
        try:
            import duckduckgo_search  # noqa: F401
            web_ok = True
        except Exception:
            pass
    out.append({"name": "Pesquisa Web", "available": web_ok, "connected": web_ok})

    # Image generation (Pollinations)
    out.append({"name": "Geração de Imagem", "available": True, "connected": True})

    # Weather
    out.append({"name": "Clima", "available": True, "connected": True})

    # Volume / Brightness / Battery
    out.append({"name": "Volume", "available": True, "connected": True})
    out.append({"name": "Brilho", "available": True, "connected": True})

    # These are placeholders — actual integration requires the user to
    # log in / set env vars. We report availability separately.
    out.append({"name": "GitHub", "available": False, "connected": False})
    out.append({"name": "MCP", "available": False, "connected": False})
    out.append({"name": "Telegram", "available": False, "connected": False})
    out.append({"name": "WhatsApp", "available": True, "connected": False})
    out.append({"name": "Calendário", "available": False, "connected": False})

    return JSONResponse({"items": out})


# ---------- Memory (projects, decisions, tasks) ----------
@app.get("/api/memory/projects")
def api_memory_projects() -> JSONResponse:
    """List every registered project (from Memory/Projects/*.md)."""
    from Brain.memory import list_projects
    return JSONResponse({"projects": list_projects()})


@app.get("/api/memory/project/{slug}")
def api_memory_project(slug: str) -> JSONResponse:
    """Return the full markdown content of a single project file."""
    from Brain.memory import read_project
    content = read_project(slug)
    if content is None:
        return JSONResponse({"error": "project not found"}, status_code=404)
    return JSONResponse({"slug": slug, "content": content})


class ProjectUpdatePayload(BaseModel):
    slug: str
    section: str
    addition: str


@app.post("/api/memory/project/update")
def api_memory_project_update(payload: ProjectUpdatePayload) -> JSONResponse:
    """Append `addition` under `section` in the given project file."""
    from Brain.memory import update_project
    try:
        path = update_project(payload.slug, payload.section, payload.addition)
        return JSONResponse({"status": "ok", "path": path})
    except FileNotFoundError as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=404)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=500)


# ---------- Reminders (adaptado de Mark-XLIX, CC BY-NC 4.0) ----------
class ReminderPayload(BaseModel):
    message: str
    minutes: int = 5


@app.post("/api/reminder/add", include_in_schema=False)
def api_reminder_add(payload: ReminderPayload) -> JSONResponse:
    """Agenda um lembrete via Windows Task Scheduler (schtasks)."""
    from Brain.actions import add_reminder, list_reminders
    result = add_reminder(payload.message, payload.minutes)
    status = 200 if result.get("ok") else 500
    return JSONResponse(result, status_code=status)


@app.get("/api/reminder/list", include_in_schema=False)
def api_reminder_list() -> JSONResponse:
    """Lista lembretes JARVIS pendentes."""
    from Brain.actions import list_reminders
    return JSONResponse({"reminders": list_reminders()})


class ReminderDeletePayload(BaseModel):
    task_name: str


@app.post("/api/reminder/delete", include_in_schema=False)
def api_reminder_delete(payload: ReminderDeletePayload) -> JSONResponse:
    """Remove um lembrete pelo nome da task (deve comecar com JARVIS)."""
    from Brain.actions import remove_reminder
    result = remove_reminder(payload.task_name)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


# ---------- Open apps (adaptado de Mark-XLIX, CC BY-NC 4.0) ----------
class OpenAppPayload(BaseModel):
    query: str


@app.post("/api/open-app", include_in_schema=False)
def api_open_app(payload: OpenAppPayload) -> JSONResponse:
    """Abre um aplicativo por nome (chrome, vscode, spotify, etc.)."""
    from Brain.actions import open_app
    result = open_app(payload.query)
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)


# ---------- Web search ----------
class TextPayload(BaseModel):
    text: str


class WeatherPayload(BaseModel):
    city: str


class ImagePayload(BaseModel):
    prompt: str


class VolumePayload(BaseModel):
    level: int


class BrightnessPayload(BaseModel):
    level: int


def _safe_run(fn, *args, **kwargs):
    """Run fn in a thread so the HTTP request returns immediately.

    The brain / image gen / network calls take seconds; we don't want the
    browser to hang waiting. The result is appended to log.txt.
    """
    def _runner():
        try:
            result = fn(*args, **kwargs)
            _append_log(f"OK: {fn.__name__} -> {str(result)[:200]}")
        except Exception as exc:  # noqa: BLE001
            _append_log(f"FAIL: {fn.__name__} -> {exc}")
    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    return {"status": "queued"}


def _append_log(line: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {line}\n")
    except Exception:
        pass


@app.post("/api/speak")
async def api_speak(payload: TextPayload) -> dict:
    """Speak `text` through the local TTS.

    Renders to a WAV via SAPI5, then opens the file with the OS default
    player. Returns the duration (in seconds) so the frontend knows when
    the speech actually ends.
    """
    import asyncio
    from TextToSpeech.Fast_DF_TTS import speak, wav_duration_seconds

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, speak, payload.text)
        _append_log(f"OK: speak -> {str(result)[:200]}")

        # Try to extract the duration of the WAV we just made so the
        # UI can switch back to idle when playback actually ends.
        duration = 0.0
        try:
            if "Played:" in result:
                wav_path = str(result).split("Played:", 1)[1].strip()
                duration = wav_duration_seconds(wav_path)
        except Exception:
            pass

        return {
            "status": "ok",
            "result": result,
            "duration_seconds": duration,
        }
    except Exception as exc:  # noqa: BLE001
        _append_log(f"FAIL: speak -> {exc}")
        return {"status": "error", "error": str(exc)}


@app.post("/api/ask")
def api_ask(payload: TextPayload) -> dict:
    """Send `text` to the brain."""
    from Brain.brain import Main_Brain
    return _safe_run(Main_Brain, payload.text)


@app.post("/api/weather")
def api_weather(payload: WeatherPayload) -> dict:
    """Fetch weather for a city."""
    from Weather_Check.check_weather import get_weather_by_address
    return _safe_run(get_weather_by_address, payload.city)


@app.post("/api/image")
def api_image(payload: ImagePayload) -> dict:
    """Generate an image from a prompt."""
    from TextToImage.gen_image import generate_image
    return _safe_run(generate_image, payload.prompt)


@app.post("/api/research")
def api_research(payload: TextPayload) -> dict:
    """Run a web research query and return the synthesized answer + sources."""
    from Brain.researcher import research
    return _safe_run(research, payload.text)


@app.post("/api/volume")
def api_volume(payload: VolumePayload) -> dict:
    """Set the system volume to a percentage (0-100)."""
    from Features.set_get_volume import set_volume_windows
    return _safe_run(set_volume_windows, payload.level)


@app.post("/api/brightness")
def api_brightness(payload: BrightnessPayload) -> dict:
    """Set the screen brightness to a percentage (0-100)."""
    from Features.set_br import set_brightness_windows
    return _safe_run(set_brightness_windows, payload.level)


@app.post("/api/clear-chat")
def api_clear_chat() -> dict:
    """Truncate the chat history file."""
    try:
        CHAT_LOG.write_text("", encoding="utf-8")
        return {"status": "cleared"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


# ---------- WebSocket for live logs ----------
@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket) -> None:
    """Stream new lines from log.txt to connected clients in real time."""
    await websocket.accept()
    with _ws_lock:
        _ws_clients.add(websocket)
    try:
        # Send current tail so newly-connected clients have context.
        if LOG_FILE.exists():
            tail = LOG_FILE.read_text(encoding="utf-8").splitlines()[-20:]
            for line in tail:
                await websocket.send_text(line)

        # Stream new lines until the client disconnects.
        last_size = LOG_FILE.stat().st_size if LOG_FILE.exists() else 0
        while True:
            await asyncio_sleep(1)
            if not LOG_FILE.exists():
                continue
            size = LOG_FILE.stat().st_size
            if size > last_size:
                with open(LOG_FILE, "r", encoding="utf-8") as fh:
                    fh.seek(last_size)
                    new = fh.read(size - last_size)
                for line in new.splitlines():
                    await websocket.send_text(line)
                last_size = size
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"[ws] error: {exc}")
    finally:
        with _ws_lock:
            _ws_clients.discard(websocket)


import asyncio


async def asyncio_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


# ---------- Entrypoint ----------
if __name__ == "__main__":
    import uvicorn
    # Allow overriding the port via env var, useful when 8765 is taken
    # by an orphaned process we can't kill.
    port = int(os.environ.get("JARVIS_DASHBOARD_PORT", "8765"))
    print("\n" + "=" * 60)
    print("  Jarvis Dashboard")
    print(f"  Open: http://localhost:{port}")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")