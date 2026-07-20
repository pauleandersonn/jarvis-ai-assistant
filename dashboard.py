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
import json
from datetime import datetime

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Make the project modules importable when we run from anywhere.
PROJECT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))


# ---- Lightweight .env loader (stdlib only) ----
# Reads KEY=VALUE lines from a file next to this script if the env var
# is not already set. Existing env vars always win — never overwrites.
# Lines starting with '#' or empty lines are ignored. Quotes are stripped.
def _load_env_file(path: pathlib.Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(PROJECT_DIR / ".env")


# ---- Lazy / safe imports for jarvis subsystems ----
# pyaudio is only needed to enumerate microphones; do NOT import at startup
# so the dashboard keeps working even when pyaudio isn't installed.
def _get_pyaudio():
    try:
        import pyaudio
        return pyaudio
    except Exception as exc:  # noqa: BLE001
        LOG.debug("pyaudio unavailable: %s", exc)
        return None

# Track when we started, for the "uptime" tile.
STARTED_AT = time.time()

# ---- Geolocalizacao por IP (silencioso, com cache por uptime) ----
LOCATION_CACHE: dict = {"city": None, "region": None, "country": None}


def _detect_location() -> dict:
    """Detecta a cidade via IP publico (ipapi.co). Roda em thread na inicializacao.

    Retorna dict vazio se falhar. Cacheia no module scope para nao chamar de novo.
    """
    try:
        import urllib.request, json as _json
        req = urllib.request.Request(
            "https://ipapi.co/json/",
            headers={"User-Agent": "JARVIS-AI-Assistant/2.6"},
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            data = _json.loads(r.read().decode("utf-8"))
        return {
            "city": data.get("city"),
            "region": data.get("region"),
            "country": data.get("country_name"),
        }
    except Exception:
        return {}


def _start_location_detection() -> None:
    """Dispara deteccao de localizacao em background (nao bloqueia startup).

    Quando detecta, salva tambem em JARVIS_DETECTED_LOCATION (env var) para que
    Brain/brain.py possa injetar no system prompt do FreeAI.
    """
    import threading, os
    def _worker():
        loc = _detect_location()
        if loc.get("city"):
            LOCATION_CACHE.update(loc)
            hint = f"{loc['city']}-{loc.get('region', '')}, {loc.get('country', 'BR')}".strip(" ,-")
            os.environ["JARVIS_DETECTED_LOCATION"] = hint
    threading.Thread(target=_worker, daemon=True).start()


_start_location_detection()

# File the brain appends to. We surface its contents in the UI.
CHAT_LOG = PROJECT_DIR / "chat_hystory.txt"
LOG_FILE = PROJECT_DIR / "log.txt"

# Logger basico -- usado em /api/trade/webhook e outros endpoints.
# (Antes usava-se uma variavel LOG que nao existia, causando NameError
# quando o webhook era chamado, o que derrubava o dashboard inteiro.)
import logging
LOG = logging.getLogger("jarvis.dashboard")
if not LOG.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                                       datefmt="%Y-%m-%d %H:%M:%S"))
    LOG.addHandler(_h)
    LOG.setLevel(logging.INFO)

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
    # Bloqueia pedido de geolocalizacao e outros recursos sensiveis
    # por outros scripts (extensoes, etc) carregados na pagina.
    "Permissions-Policy": "geolocation=(), microphone=(self), camera=()",
    # Politica de permissao padrao: o navegador exige acao do usuario pra TTS.
    "Referrer-Policy": "no-referrer",
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
@app.get("/api/greeting")
def greeting() -> JSONResponse:
    """Retorna uma saudacao contextual baseada na hora, data e localizacao.

    O frontend chama isso uma vez no boot e usa o texto para o TTS,
    mostrando tambem na UI. Cada hora tem variacoes para evitar repeticao.
    """
    from datetime import datetime
    now = datetime.now()
    hour = now.hour
    weekday = now.strftime("%A")
    city = (LOCATION_CACHE.get("city") or "").strip()

    # Saudacao por periodo
    if 5 <= hour < 12:
        period = "Bom dia"
        period_en = "manha"
    elif 12 <= hour < 18:
        period = "Boa tarde"
        period_en = "tarde"
    elif 18 <= hour < 23:
        period = "Boa noite"
        period_en = "noite"
    else:
        period = "Ola"
        period_en = "madrugada"

    # Dia da semana em PT-BR
    weekdays = {
        "Monday": "segunda-feira", "Tuesday": "terca-feira",
        "Wednesday": "quarta-feira", "Thursday": "quinta-feira",
        "Friday": "sexta-feira", "Saturday": "sabado", "Sunday": "domingo",
    }
    weekday_pt = weekdays.get(weekday, weekday)

    # Variacoes da saudacao
    import random
    base_lines = [
        f"{period}. JARVIS online. Hoje e {weekday_pt}.",
        f"{period}, senhor. Sistema operacional. {weekday_pt}.",
        f"{period}. {weekday_pt.capitalize()}. JARVIS a postos.",
        f"{period}, " + (city + " - " if city else "") + "todos os sistemas ativos.",
        f"{period}. Como posso ajudar nesta {period_en}?",
    ]
    line = random.choice(base_lines)
    city_note = ""
    if city:
        city_note = f" Localizacao detectada: {city}."

    # Anuncia qual LLM esta' em uso (util quando openai_cloud entra em cena).
    # Mostra em chat mas NAO fala via TTS (o campo "speak" e' abaixo).
    try:
        from Brain.llm_client import (
            get_llm_provider as _gprov, get_llm_settings as _gset,
            validate_openai_cloud_key,
        )
        provider = _gprov()
        if provider == "openai_cloud":
            url, model = _gset()
            key_ok = validate_openai_cloud_key(timeout=4)
            status_txt = "online" if key_ok else "offline"
            lline = f"Cerebro: {model} ({status_txt}, via {url})."
        elif provider == "ollama":
            _, model = _gset()
            lline = f"Cerebro: Ollama local ({model})."
        elif provider == "openai":
            _, model = _gset()
            lline = f"Cerebro: OpenAI-compat local ({model})."
        else:
            lline = "Cerebro: FreeAI (sem chave)."
    except Exception as _e:
        lline = "Cerebro: modo padrao."

    return JSONResponse({
        "text":  line,                   # o que fala via TTS (sem o "cerebro")
        "speak": line + city_note,       # idem + cidade
        "llm":   lline,                  # exibido no chat, NAO falado
        "hour":  hour,
        "weekday":  weekday_pt,
        "city":     city,
        "period":   period_en,
    })


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
        "location": dict(LOCATION_CACHE),
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
        # IMPORTANTE: parsear TODAS as mensagens do arquivo, depois pegar as `limit` últimas.
        # O loop antigo parava em `limit * 2`, retornando mensagens do INÍCIO em vez do fim.
        while i < len(lines):
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

    # day-trade-bot integration: only "available" if the token env var is set.
    trade_token_set = bool(os.environ.get("JARVIS_DASHBOARD_TRADE_WEBHOOK_TOKEN"))
    out.append({
        "name": "Day-Trade-Bot",
        "available": trade_token_set,
        "connected": trade_token_set,
        "events_received": len(TRADE_SIGNAL_BUFFER),
    })

    return JSONResponse({"items": out})


# ---------- WebSocket manager (lightweight) ----------

class WSManager:
    """Tracks live WebSocket connections and broadcasts JSON messages.

    Used for trade-signal push notifications. If no clients are connected,
    broadcast() is a no-op — clients just call /api/integrations/trade/recent
    on reconnect to catch up.
    """

    def __init__(self) -> None:
        self._clients: set = set()
        self._lock = threading.Lock()

    async def connect(self, ws) -> None:
        await ws.accept()
        with self._lock:
            self._clients.add(ws)

    def disconnect(self, ws) -> None:
        with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        import asyncio
        msg = json.dumps(payload, ensure_ascii=False, default=str)
        with self._lock:
            stale = []
            for ws in list(self._clients):
                try:
                    await ws.send_text(msg)
                except Exception:  # noqa: BLE001
                    stale.append(ws)
            for ws in stale:
                self._clients.discard(ws)


ws_manager = WSManager()


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for push notifications (trade signals, etc).

    Sends {"type": "hello", "data": {"protocol": "jarvis-ws", "version": 1}}
    on connect, then any subsequent broadcasts.
    """
    await ws_manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({
            "type": "hello",
            "data": {"protocol": "jarvis-ws", "version": 1},
        }, ensure_ascii=False))
        # Keep the connection alive; we don't expect inbound messages but
        # accept and discard them so the connection doesn't drop on us.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        LOG.debug("ws endpoint error: %s", exc)
    finally:
        ws_manager.disconnect(websocket)


# ---------- Trade Webhook (day-trade-bot → JARVIS) ----------

class TradeWebhookPayload(BaseModel):
    event: str  # "signal" | "fill" | "summary"
    timestamp: str
    symbol: str | None = None
    action: str | None = None  # "CALL" | "PUT"
    expiry_minutes: int | None = None
    reason: str | None = None
    indicator_value: float | None = None
    balance: float | None = None
    amount: float | None = None
    pnl: float | None = None
    result: str | None = None
    n_trades: int | None = None
    n_wins: int | None = None
    n_losses: int | None = None
    win_rate: float | None = None
    engine: str | None = None
    story: str | None = None


# In-memory ring buffer for the most recent trade signals (cap 50).
TRADE_SIGNAL_BUFFER: list[dict] = []
TRADE_SIGNAL_BUFFER_MAX = 50


def _validate_trade_token(authorization: str | None) -> bool:
    """Return True if Authorization header matches env token.

    Reads JARVIS_DASHBOARD_TRADE_WEBHOOK_TOKEN. If unset, webhook is disabled
    (returns False for any call) — fail-closed.
    """
    expected = os.environ.get("JARVIS_DASHBOARD_TRADE_WEBHOOK_TOKEN")
    if not expected:
        return False
    if not authorization:
        return False
    # Accept "Bearer xxx" or raw token
    token = authorization
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    # Constant-time-ish compare
    return len(token) == len(expected) and all(a == b for a, b in zip(token, expected))


@app.post("/api/integrations/webhook/trade-signal")
async def api_trade_webhook(payload: TradeWebhookPayload, request: Request) -> JSONResponse:
    """Receives signals from day-trade-bot and broadcasts them to the dashboard.

    Auth: Authorization: Bearer <token> matching JARVIS_DASHBOARD_TRADE_WEBHOOK_TOKEN.
    Returns 401 if token missing/wrong; 503 if webhook not configured.
    """
    import uuid
    auth = request.headers.get("authorization")
    if not os.environ.get("JARVIS_DASHBOARD_TRADE_WEBHOOK_TOKEN"):
        return JSONResponse(
            {"ok": False, "error": "trade webhook disabled (set JARVIS_DASHBOARD_TRADE_WEBHOOK_TOKEN)"},
            status_code=503,
        )
    if not _validate_trade_token(auth):
        return JSONResponse(
            {"ok": False, "error": "invalid or missing Authorization header"},
            status_code=401,
        )

    # Rate-limit simples por IP (defesa contra flood externo).
    # Max 30 requests / 60s por IP. Bots scanners vao bater nesse limite
    # e receber 429 sem conseguir derrubar o dashboard.
    import time as _t
    client_ip = request.client.host if request.client else "unknown"
    now = _t.time()
    if not hasattr(api_trade_webhook, "_rl"):
        api_trade_webhook._rl = {}
    rl = api_trade_webhook._rl
    bucket = rl.setdefault(client_ip, [])
    bucket[:] = [ts for ts in bucket if now - ts < 60]
    if len(bucket) >= 30:
        LOG.warning("trade webhook rate-limit hit from %s", client_ip)
        return JSONResponse(
            {"ok": False, "error": "rate limit exceeded"},
            status_code=429,
        )
    bucket.append(now)

    entry_id = str(uuid.uuid4())
    entry = {"id": entry_id, "received_at": datetime.now().isoformat(), **payload.model_dump()}
    TRADE_SIGNAL_BUFFER.append(entry)
    # Trim oldest beyond cap
    if len(TRADE_SIGNAL_BUFFER) > TRADE_SIGNAL_BUFFER_MAX:
        del TRADE_SIGNAL_BUFFER[: len(TRADE_SIGNAL_BUFFER) - TRADE_SIGNAL_BUFFER_MAX]

    # Grava também no DB de sinais (pra correlação com Telegram)
    try:
        from Brain.actions.telegram_signal_linker import record_signal
        record_signal(
            symbol=entry.get("symbol", ""),
            direction=entry.get("direction") or entry.get("action", ""),
            signal_source="day-trade-bot",
            metadata=entry,
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("record_signal falhou (sinal ainda assim bufferizado): %s", exc)

    # Broadcast via WebSocket (best-effort; clients that aren't connected just miss it).
    try:
        await ws_manager.broadcast({"type": "trade_signal", "data": entry})
    except Exception as exc:  # noqa: BLE001
        LOG.warning("ws broadcast failed: %s", exc)

    LOG.info("trade webhook: %s event=%s symbol=%s action=%s",
             entry_id, payload.event, payload.symbol, payload.action)
    return JSONResponse({"ok": True, "id": entry_id, "buffered": len(TRADE_SIGNAL_BUFFER)})


@app.get("/api/integrations/trade/recent", include_in_schema=False)
def api_trade_recent(limit: int = 20) -> JSONResponse:
    """Return the most recent trade signals received via webhook.

    limit is clamped to [1, 50].
    """
    limit = max(1, min(int(limit), TRADE_SIGNAL_BUFFER_MAX))
    recent = TRADE_SIGNAL_BUFFER[-limit:][::-1]  # newest first
    return JSONResponse({"count": len(recent), "events": recent})


# ---------- WhatsApp Cloud API (Meta) ----------
# Webhook recebe eventos da Meta. Análise de oportunidades com LLM.
# Doc: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
@app.get("/api/integrations/whatsapp/webhook")
def whatsapp_webhook_verify(
    hub_mode: str = "",
    hub_verify_token: str = "",
    hub_challenge: str = "",
) -> Response:
    """Handshake inicial da Meta (GET). Verifica token, retorna challenge."""
    from Brain.integrations.whatsapp import verify_webhook
    challenge = verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


@app.post("/api/integrations/whatsapp/webhook")
async def whatsapp_webhook_receive(request: Request) -> JSONResponse:
    """Recebe evento da Meta (POST). Extrai mensagem, analisa, armazena."""
    from Brain.integrations.whatsapp import extract_message, mark_as_read
    from Brain.actions.whatsapp_analyzer import (
        analyze_conversation,
        quick_keyword_scan,
    )
    from Brain.integrations.opportunities_store import add_opportunity

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON inválido"}, status_code=400)

    msg = extract_message(payload)
    if not msg:
        # Pode ser um update de status (delivered/read), não mensagem de texto
        return JSONResponse({"ok": True, "skipped": "no_text_message"})

    # 1) Triagem rápida sem LLM (economia de tokens)
    scan = quick_keyword_scan(msg["body"])
    if not scan["vertical_match"]:
        # Conversa casual sem nenhuma palavra-chave — pula
        return JSONResponse({"ok": True, "skipped": "no_business_keywords", "scan": scan})

    # 2) Análise completa via LLM
    analysis_result = analyze_conversation(
        messages=[msg["body"]],
        vertical="auto",
        context=f"Contato: {msg['profile_name']} ({msg['from']})",
    )
    if not analysis_result.get("ok"):
        return JSONResponse(
            {"ok": False, "error": "LLM analysis failed", "detail": analysis_result},
            status_code=500,
        )

    # 3) Salva oportunidade no DB
    opp = add_opportunity(
        chat_phone=msg["from"],
        chat_name=msg["profile_name"],
        analysis=analysis_result["analysis"],
        raw_message=msg["body"],
        mensagem_id=msg["message_id"],
    )

    # 4) Marca azulinho (best-effort)
    try:
        mark_as_read(msg["message_id"])
    except Exception:
        pass

    return JSONResponse({
        "ok": True,
        "scan": scan,
        "analysis": analysis_result["analysis"],
        "opportunity_id": opp.get("id"),
        "tokens_used": analysis_result.get("tokens_used", 0),
    })


@app.get("/api/integrations/whatsapp/opportunities")
def whatsapp_opportunities(
    vertical: str = "",
    status: str = "",
    limit: int = 50,
) -> JSONResponse:
    """Lista oportunidades detectadas. Filtros opcionais por vertical/status."""
    from Brain.integrations.opportunities_store import list_opportunities
    opps = list_opportunities(
        vertical=vertical or None,
        status=status or None,
        limit=max(1, min(int(limit), 200)),
    )
    return JSONResponse({"count": len(opps), "opportunities": opps})


@app.get("/api/integrations/whatsapp/opportunities/stats")
def whatsapp_opportunities_stats() -> JSONResponse:
    """Stats agregadas (totais por vertical/status, hot leads)."""
    from Brain.integrations.opportunities_store import get_stats
    return JSONResponse(get_stats())


@app.post("/api/integrations/whatsapp/opportunities/{opp_id}/status")
async def whatsapp_opportunity_update_status(opp_id: str, request: Request) -> JSONResponse:
    """Atualiza status de uma oportunidade (novo/contatado/convertido/perdido)."""
    from Brain.integrations.opportunities_store import update_status
    body = await request.json()
    new_status = body.get("status", "").strip()
    ok = update_status(opp_id, new_status)
    return JSONResponse({"ok": ok, "id": opp_id, "status": new_status})


@app.post("/api/integrations/whatsapp/send")
async def whatsapp_send_message(request: Request) -> JSONResponse:
    """Envia mensagem de texto 1:1 (debug/teste). POST {"to": "+55...", "body": "..."}."""
    from Brain.integrations.whatsapp import send_text_message, is_configured
    if not is_configured():
        return JSONResponse(
            {"ok": False, "error": "WhatsApp não configurado (env vars faltando)"},
            status_code=503,
        )
    body = await request.json()
    result = send_text_message(
        to_phone=body.get("to", ""),
        body=body.get("body", ""),
    )
    return JSONResponse(result)


@app.get("/api/integrations/whatsapp/health")
def whatsapp_health() -> JSONResponse:
    """Health check — testa credenciais via GET na Meta API."""
    from Brain.integrations.whatsapp import health_check, is_configured
    return JSONResponse({
        "configured": is_configured(),
        "api_check": health_check() if is_configured() else None,
    })


@app.get("/api/integrations/whatsapp/signal/preview")
def whatsapp_signal_preview(
    symbol: str = "EURUSD-OTC",
    time: str = "12:50",
    direction: str = "CALL",
    expiry: str = "5min",
    gale: int = 1,
) -> JSONResponse:
    """Preview do template de sinal (formato Pauleanderson/Pollar).

    Nao envia nada — so renderiza o texto. Util pra debug do template
    antes de configurar as credenciais Meta.
    """
    from Brain.integrations.whatsapp import format_signal
    body = format_signal(
        symbol=symbol,
        time_str=time,
        direction=direction,
        expiry=expiry,
        gale_available=bool(int(gale)),
    )
    return JSONResponse({"ok": True, "preview": body})


@app.post("/api/integrations/whatsapp/signal")
async def whatsapp_signal_send(request: Request) -> JSONResponse:
    """Envia sinal formatado pra um contato do WhatsApp.

    POST {
      "to": "+5591987654321",
      "symbol": "EURUSD-OTC",
      "time": "12:50",        # Manaus TZ
      "direction": "CALL",     # ou "PUT"
      "expiry": "5min",
      "gale": true,
      "preview_only": false    # true = so retorna texto, nao envia
    }
    """
    from Brain.integrations.whatsapp import send_signal_message
    body = await request.json()
    result = send_signal_message(
        to_phone=body.get("to", ""),
        symbol=body.get("symbol", "EURUSD-OTC"),
        time_str=body.get("time", "00:00"),
        direction=body.get("direction", "CALL"),
        expiry=body.get("expiry", "5min"),
        gale_available=bool(body.get("gale", True)),
        preview_only=bool(body.get("preview_only", False)),
    )
    return JSONResponse(result)


# ---------- Church Radar (comunicação ministerial) ----------
# Monitora contas de igrejas no IG/FB, detecta oportunidades pastorais
# (visitantes, pedidos de oração, crises), gera conteúdo devocional e posts.
@app.get("/api/church/radar/stats")
def church_radar_stats() -> JSONResponse:
    """Stats agregadas do radar ministerial."""
    from Brain.integrations.church_radar_store import get_stats
    return JSONResponse(get_stats())


@app.post("/api/church/radar/accounts")
async def church_radar_add_account(request: Request) -> JSONResponse:
    """Adiciona conta de igreja pra monitorar.

    POST {
      "platform": "instagram" | "facebook",
      "handle": "@lagoinhamanaus",
      "church_name": "Lagoinha Manaus",
      "denomination": "evangelica",
      "city": "Manaus", "state": "AM",
      "notes": "Igreja da família, monitorar cultos e visitantes"
    }
    """
    from Brain.integrations.church_radar_store import add_account
    body = await request.json()
    result = add_account(
        platform=body.get("platform", "instagram"),
        handle=body.get("handle", ""),
        church_name=body.get("church_name", ""),
        denomination=body.get("denomination", ""),
        city=body.get("city", ""),
        state=body.get("state", ""),
        notes=body.get("notes", ""),
    )
    return JSONResponse(result)


@app.get("/api/church/radar/accounts")
def church_radar_list_accounts() -> JSONResponse:
    """Lista contas de igrejas monitoradas."""
    from Brain.integrations.church_radar_store import list_accounts
    return JSONResponse({"count": 0, "accounts": list_accounts()})


@app.post("/api/church/radar/scan")
async def church_radar_scan_post(request: Request) -> JSONResponse:
    """Analisa 1 post (texto) e classifica como oportunidade ministerial.

    POST {
      "account_id": "abc123" (opcional, associa a uma conta),
      "platform": "instagram" (default),
      "source": "comment" | "dm" | "post" | "ad",
      "source_id": "comment-12345",
      "author_name": "Maria",
      "author_handle": "@maria",
      "text": "Adorei o culto de domingo! Primeira vez lá, foi incrível."
    }
    """
    from Brain.actions.church_radar import classify_post
    from Brain.integrations.church_radar_store import add_radar_item
    # Tolera UTF-8 e Latin-1 (PowerShell às vezes manda CP1252)
    raw_body = await request.body()
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except UnicodeDecodeError:
        body = json.loads(raw_body.decode("latin-1"))
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "text vazio"}, status_code=400)
    classification = classify_post(text)
    item = add_radar_item(
        account_id=body.get("account_id", ""),
        platform=body.get("platform", "instagram"),
        source=body.get("source", "comment"),
        source_id=body.get("source_id", ""),
        author_name=body.get("author_name", ""),
        author_handle=body.get("author_handle", ""),
        raw_text=text,
        themes=classification["themes"],
        opportunities=classification["opportunities"],
        urgency=classification["urgency"],
        suggested_action=classification["suggested_action"],
        score=classification["score"],
    )
    return JSONResponse({
        "ok": True,
        "classification": classification,
        "item": item,
    })


@app.get("/api/church/radar/items")
def church_radar_list_items(
    status: str = "",
    urgency: str = "",
    account_id: str = "",
    limit: int = 50,
) -> JSONResponse:
    """Lista oportunidades ministeriais detectadas (filtros opcionais)."""
    from Brain.integrations.church_radar_store import list_radar_items
    items = list_radar_items(
        status=status or None,
        urgency=urgency or None,
        account_id=account_id or None,
        limit=limit,
    )
    return JSONResponse({"count": len(items), "items": items})


@app.post("/api/church/radar/items/{item_id}/status")
async def church_radar_update_status(item_id: str, request: Request) -> JSONResponse:
    """Atualiza status de uma oportunidade ministerial.

    POST {"status": "acionado" | "resolvido" | "arquivado", "notes": "..."}
    """
    from Brain.integrations.church_radar_store import update_radar_status
    body = await request.json()
    ok = update_radar_status(
        item_id,
        body.get("status", ""),
        notes=body.get("notes", ""),
    )
    return JSONResponse({"ok": ok, "id": item_id})


@app.post("/api/church/radar/devocional")
async def church_radar_generate_devotional(request: Request) -> JSONResponse:
    """Gera devocional diário (com versículo, reflexão, oração).

    POST {
      "theme": "ansiedade" | "fé" | "família" | "amor" | ...,
      "book": "Filipenses" (opcional, customizado),
      "chapter": 4,
      "verse": 6
    }
    """
    from Brain.actions.church_radar import generate_devotional_text
    from Brain.integrations.church_radar_store import add_generated_content
    body = await request.json()
    devocional = generate_devotional_text(
        theme=body.get("theme", ""),
        book=body.get("book", ""),
        chapter=int(body.get("chapter", 0)),
        verse=int(body.get("verse", 0)),
    )
    stored = add_generated_content(
        kind="devocional",
        theme=body.get("theme", ""),
        title=devocional["title"],
        content=devocional,
    )
    return JSONResponse({"ok": True, "devocional": devocional, "stored_id": stored["id"]})


@app.post("/api/church/radar/post")
async def church_radar_generate_post(request: Request) -> JSONResponse:
    """Gera sugestão de post para rede social de igreja.

    POST {
      "theme": "domingo" | "jejum" | "festa junina" | "família" | ...,
      "format": "instagram" | "facebook" | "stories" | "reels"
    }
    """
    from Brain.actions.church_radar import generate_church_post_suggestion
    from Brain.integrations.church_radar_store import add_generated_content
    body = await request.json()
    post = generate_church_post_suggestion(
        theme=body.get("theme", ""),
        format=body.get("format", "instagram"),
    )
    stored = add_generated_content(
        kind=f"post_{post['format']}",
        theme=body.get("theme", ""),
        title=f"Post {post['format'].title()}: {body.get('theme', '')}",
        content=post,
    )
    return JSONResponse({"ok": True, "post": post, "stored_id": stored["id"]})


@app.get("/api/church/radar/content")
def church_radar_list_content(kind: str = "", theme: str = "",
                              limit: int = 50) -> JSONResponse:
    """Lista conteúdo gerado (devocionais, posts)."""
    from Brain.integrations.church_radar_store import list_generated_content
    items = list_generated_content(
        kind=kind or None,
        theme=theme or None,
        limit=limit,
    )
    return JSONResponse({"count": len(items), "items": items})


# ---------- Telegram Opportunities Layer ----------
# Detecta oportunidades de negocio a partir de mensagens do Telegram.
# 3 caminhos de entrada:
#   (a) Webhook python-telegram-bot (POST com update)
#   (b) Polling manual (envia mensagem avulsa)
#   (c) Correlacao automatica com sinais de trade
@app.post("/api/integrations/telegram/inbound")
async def telegram_inbound_message(request: Request) -> JSONResponse:
    """Recebe msg do Telegram (via webhook python-telegram-bot ou polling).

    POST {
      "chat_id": 123,
      "chat_title": "Grupo Trade",
      "chat_type": "group" | "private" | "supergroup",
      "sender_name": "João",
      "sender_id": 12345,
      "message_id": 678,
      "text": "Conteudo da mensagem"
    }
    """
    from Brain.actions.telegram_analyzer import analyze_message
    from Brain.integrations.telegram_opportunities_store import add_opportunity
    from Brain.actions.telegram_signal_linker import (
        add_recent_message,
        get_recent_messages,
        correlate_signal_with_messages,
        generate_correlation_opportunity,
    )

    body = await request.json()
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "text vazio"}, status_code=400)

    chat_id = int(body.get("chat_id", 0))
    chat_title = body.get("chat_title", "")
    chat_type = body.get("chat_type", "private")
    sender_name = body.get("sender_name", "?")
    sender_id = int(body.get("sender_id", 0))

    # 1) Adiciona no buffer RAM pra correlação futura
    add_recent_message(chat_id, sender_name, text)

    # 2) Analisa com LLM (ou triagem rápida)
    result = analyze_message(
        text=text,
        chat_context=f"{chat_title} ({chat_type})",
        sender_name=sender_name,
    )
    if not result.get("ok"):
        return JSONResponse(
            {"ok": False, "error": "análise falhou", "detail": result},
            status_code=500,
        )

    analysis = result["analysis"]
    category = analysis.get("category", "conversa_casual")

    # 3) Se for casual, descarta (mas loga)
    if category == "conversa_casual":
        return JSONResponse({
            "ok": True,
            "skipped": "conversa_casual",
            "analysis": analysis,
        })

    # 4) Persiste oportunidade
    opp = add_opportunity(
        chat_id=chat_id,
        chat_title=chat_title,
        chat_type=chat_type,
        sender_name=sender_name,
        sender_id=sender_id,
        message_id=int(body.get("message_id", 0)),
        message_text=text,
        analysis=analysis,
    )

    # 5) Correlação com sinais: vê se há sinal de trade recente pra esse par
    symbol_keywords = ["EUR", "GBP", "USD", "JPY", "AUD", "CAD"]
    mentioned_symbol = next(
        (s for s in symbol_keywords if s in text.upper()), None
    )
    if mentioned_symbol and chat_type in ("group", "supergroup"):
        # Vê se teve sinal há 15 min
        from Brain.actions.telegram_signal_linker import get_signals_last_n_minutes
        recent_signals = get_signals_last_n_minutes(15, symbol=mentioned_symbol)
        if recent_signals:
            correlation = correlate_signal_with_messages(
                symbol=mentioned_symbol,
                direction="CALL",  # heurística simples
                recent_msgs=get_recent_messages(chat_id, since_minutes=15),
            )
            if correlation:
                generate_correlation_opportunity(correlation, chat_id, chat_title)

    return JSONResponse({
        "ok": True,
        "category": category,
        "score": analysis.get("score"),
        "lead_quente": analysis.get("lead_quente"),
        "opportunity_id": opp.get("id"),
        "tokens_used": result.get("tokens_used", 0),
    })


@app.get("/api/integrations/telegram/opportunities")
def telegram_opportunities(
    category: str = "",
    status: str = "",
    min_score: float = 0.0,
    only_hot: int = 0,
    limit: int = 50,
) -> JSONResponse:
    """Lista oportunidades detectadas."""
    from Brain.integrations.telegram_opportunities_store import list_opportunities
    opps = list_opportunities(
        category=category or None,
        status=status or None,
        min_score=float(min_score),
        only_hot=bool(int(only_hot)),
        limit=max(1, min(int(limit), 200)),
    )
    return JSONResponse({"count": len(opps), "opportunities": opps})


@app.get("/api/integrations/telegram/opportunities/stats")
def telegram_opportunities_stats() -> JSONResponse:
    """Stats agregadas."""
    from Brain.integrations.telegram_opportunities_store import get_stats
    return JSONResponse(get_stats())


@app.get("/api/integrations/telegram/opportunities/top")
def telegram_opportunities_top(limit: int = 5) -> JSONResponse:
    """Top N oportunidades pra briefing diário (novas + hot + score alto)."""
    from Brain.integrations.telegram_opportunities_store import get_top_opportunities
    return JSONResponse({
        "count": limit,
        "opportunities": get_top_opportunities(limit),
    })


@app.get("/api/integrations/telegram/opportunities/brief")
def telegram_opportunities_brief_audio() -> Response:
    """Briefing em áudio das top oportunidades do dia (TTS pt-BR-AntonioNeural)."""
    from Brain.integrations.telegram_opportunities_store import get_top_opportunities
    from Brain.actions.telegram_analyzer import generate_daily_brief
    opps = get_top_opportunities(5)
    texto = generate_daily_brief(opps)

    try:
        import asyncio
        import edge_tts

        async def _synth():
            comm = edge_tts.Communicate(
                texto, voice="pt-BR-AntonioNeural", rate="-8%", pitch="-4Hz",
            )
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            await comm.save(tmp.name)
            with open(tmp.name, "rb") as f:
                return f.read()

        audio_bytes = asyncio.run(_synth())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="opp-brief.mp3"'},
    )


@app.post("/api/integrations/telegram/opportunities/{opp_id}/status")
async def telegram_opportunity_status_update(opp_id: str, request: Request) -> JSONResponse:
    """Atualiza status de uma oportunidade (novo/contatado/convertido/perdido)."""
    from Brain.integrations.telegram_opportunities_store import update_status
    body = await request.json()
    ok = update_status(
        opp_id,
        body.get("status", ""),
        notes=body.get("notes"),
    )
    return JSONResponse({"ok": ok, "id": opp_id})


@app.post("/api/integrations/telegram/signal")
async def telegram_signal_record(request: Request) -> JSONResponse:
    """Registra um sinal de trade (chamado pelo webhook do day-trade-bot).

    POST {
      "symbol": "EURUSD-OTC",
      "direction": "CALL" | "PUT",
      "metadata": {...}    # opcional, fica salvo
    }

    Side effect: verifica correlação com chats Telegram recentes.
    """
    from Brain.actions.telegram_signal_linker import record_signal
    body = await request.json()
    result = record_signal(
        symbol=body.get("symbol", ""),
        direction=body.get("direction", ""),
        signal_source=body.get("source", "day-trade-bot"),
        metadata=body.get("metadata"),
    )
    return JSONResponse(result)


@app.get("/api/integrations/telegram/signals/recent")
def telegram_signals_recent(minutes: int = 30, symbol: str = "") -> JSONResponse:
    """Sinais de trade recentes (últimos N minutos, filtro de símbolo opcional)."""
    from Brain.actions.telegram_signal_linker import get_signals_last_n_minutes
    sigs = get_signals_last_n_minutes(minutes, symbol=symbol or None)
    return JSONResponse({
        "minutes": minutes,
        "count": len(sigs),
        "signals": sigs,
    })


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


# ---------- Email (Gmail) ----------
class EmailSearchPayload(BaseModel):
    query: str = "is:unread"
    max_results: int = 5


class EmailSendPayload(BaseModel):
    to: str
    subject: str
    body: str
    html: bool = False
    from_alias: str | None = None


@app.post("/api/email/search", include_in_schema=False)
def api_email_search(payload: EmailSearchPayload) -> JSONResponse:
    """Busca emails por query Gmail (is:unread, from:X, newer_than:Nd)."""
    from Brain.actions import search_emails
    result = search_emails(query=payload.query, max_results=payload.max_results)
    return JSONResponse(result, status_code=200 if result.get("ok") else 500)


@app.post("/api/email/send", include_in_schema=False)
def api_email_send(payload: EmailSendPayload) -> JSONResponse:
    """Envia email. USAR COM CUIDADO — envia de verdade."""
    from Brain.actions import send_email
    result = send_email(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        html=payload.html,
        from_alias=payload.from_alias,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@app.post("/api/email/inbox-summary", include_in_schema=False)
def api_email_inbox_summary(payload: EmailSearchPayload) -> JSONResponse:
    """Retorna string TTS-friendly com os N emails mais recentes (pra o JARVIS falar)."""
    from Brain.actions import summarize_inbox
    summary = summarize_inbox(query=payload.query, max_results=payload.max_results)
    return JSONResponse({"ok": True, "summary": summary})


# ---------- Calendar (Google Calendar) ----------
class CalendarListPayload(BaseModel):
    start: str | None = None
    end: str | None = None
    max_results: int = 10


class CalendarCreatePayload(BaseModel):
    summary: str
    start_iso: str
    end_iso: str
    location: str | None = None
    description: str | None = None
    attendees: list[str] | None = None


@app.post("/api/calendar/list", include_in_schema=False)
def api_calendar_list(payload: CalendarListPayload) -> JSONResponse:
    """Lista eventos entre start e end (ISO 8601). Default: proximos 7 dias."""
    from Brain.actions import list_events
    result = list_events(
        start=payload.start, end=payload.end, max_results=payload.max_results
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 500)


@app.post("/api/calendar/create", include_in_schema=False)
def api_calendar_create(payload: CalendarCreatePayload) -> JSONResponse:
    """Cria evento. CUIDADO: vai pro Calendar oficial — confirma com usuario antes."""
    from Brain.actions import create_event
    result = create_event(
        summary=payload.summary,
        start_iso=payload.start_iso,
        end_iso=payload.end_iso,
        location=payload.location,
        description=payload.description,
        attendees=payload.attendees,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


class CalendarDeletePayload(BaseModel):
    event_id: str


@app.post("/api/calendar/delete", include_in_schema=False)
def api_calendar_delete(payload: CalendarDeletePayload) -> JSONResponse:
    """Deleta evento por ID. CUIDADO — vai pra lixeira do Google Calendar."""
    from Brain.actions import delete_event
    result = delete_event(payload.event_id)
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@app.post("/api/calendar/agenda-summary", include_in_schema=False)
def api_calendar_agenda_summary(payload: CalendarListPayload) -> JSONResponse:
    """Retorna string TTS-friendly com a agenda do periodo."""
    from Brain.actions import summarize_agenda
    summary = summarize_agenda(
        start=payload.start, end=payload.end, max_events=payload.max_results
    )
    return JSONResponse({"ok": True, "summary": summary})


# ---------- Voice confirmation (MCP server bridge) ----------
class VoiceConfirmRespondPayload(BaseModel):
    request_id: str
    status: str  # 'approved' ou 'denied'
    reason: str = ""


@app.get("/api/voice-confirm/pending", include_in_schema=False)
def api_voice_confirm_pending() -> JSONResponse:
    """Lista pending confirm requests do MCP server. Dashboard faz polling 1s."""
    from Brain.voice_confirm import list_pending
    pending = list_pending()
    return JSONResponse({"ok": True, "pending": pending})


@app.post("/api/voice-confirm/respond", include_in_schema=False)
def api_voice_confirm_respond(payload: VoiceConfirmRespondPayload) -> JSONResponse:
    """Dashboard POSTa a resposta do usuario apos ouvir pelo mic."""
    from Brain.voice_confirm import post_response
    r = post_response(payload.request_id, payload.status, payload.reason)
    return JSONResponse(r, status_code=200 if r.get("ok") else 400)


# ---------- MCP server status ----------
@app.get("/api/mcp/status", include_in_schema=False)
def api_mcp_status() -> JSONResponse:
    """Reporta status do MCP server (se ta rodando, tools disponiveis)."""
    import socket as _socket
    port = 8789
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect(("127.0.0.1", port))
        running = True
    except Exception:
        running = False
    finally:
        sock.close()
    return JSONResponse({
        "running": running,
        "port": port,
        "tools_count": 10,
        "read_tools": [
            "jarvis_list_emails", "jarvis_read_email",
            "jarvis_list_calendar", "jarvis_ask_brain",
            "jarvis_read_hermes_context",
        ],
        "write_tools": [
            "jarvis_send_email", "jarvis_create_event", "jarvis_delete_event",
            "jarvis_set_reminder", "jarvis_open_app",
        ],
    })


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
async def api_speak(request: Request):
    """Gera audio (WAV via SAPI5 OU MP3 via Edge TTS) e devolve os bytes.

    Contrato:
      Request: JSON {"text": str, "engine": "sapi5"|"edge" (default="edge")}
      Response: audio/wav OU audio/mpeg bytes

    Engine padrao: "edge" (pt-BR-AntonioNeural — voz Jarvis-like grave/pausada).
    Pra voltar a SAPI5 (Maria Desktop), envie "engine":"sapi5".

    Validacoes:
      200 + bytes       — fala gerada
      400 + JSON        — texto vazio
      503 + JSON        — engine indisponivel
    """
    body = await request.json()
    raw = (body.get("text") or "").strip()
    engine = (body.get("engine") or "edge").lower()

    if not raw:
        return JSONResponse(
            {"status": "empty", "reason": "text vazio"},
            status_code=400,
        )

    # ── Edge TTS (default — voz Jarvis-like) ──────────────────────
    if engine == "edge":
        try:
            from TextToSpeech.Edge_TTS import speak_to_file as edge_speak
            # speak_to_file e async (detecta loop via asyncio.get_running_loop).
            mp3_path = await edge_speak(raw)
            with open(mp3_path, "rb") as fh:
                mp3_bytes = fh.read()
            # Calcula duracao estimada (MP3 ~ 16kbps pra voz)
            duration = len(mp3_bytes) / 2000.0
            headers = {
                "Cache-Control": "no-store",
                "X-Jarvis-Engine": "edge-tts",
                "X-Jarvis-Voice": os.environ.get("JARVIS_EDGE_VOICE", "pt-BR-AntonioNeural"),
                "X-Jarvis-Duration": f"{duration:.2f}",
                "Content-Disposition": 'inline; filename="jarvis_edge.mp3"',
            }
            return Response(
                content=mp3_bytes,
                media_type="audio/mpeg",
                headers=headers,
            )
        except Exception as exc:  # noqa: BLE001
            _append_log(f"ERROR: edge-tts falhou: {exc}")
            return JSONResponse(
                {"status": "error", "reason": "edge-tts indisponivel", "detail": str(exc)},
                status_code=503,
            )

    # ── SAPI5 fallback (voz Maria Desktop PT-BR) ──────────────────
    from TextToSpeech.Fast_DF_TTS import (
        speak_to_file as sapi_speak,
        _clean_for_speech,
        _has_meta_content,
        _smart_truncate,
    )

    clean = _clean_for_speech(raw)
    if not clean:
        return JSONResponse(
            {"status": "empty", "reason": "text vazio apos limpeza"},
            status_code=400,
        )
    if _has_meta_content(clean):
        _append_log(f"WARN: meta-fala bloqueada: {clean[:80]!r}")
        clean = "Mensagem bloqueada pelo filtro de seguranca."
    text = _smart_truncate(clean, max_chars=600)

    try:
        wav_path = sapi_speak(text)
    except Exception as exc:  # noqa: BLE001
        _append_log(f"ERROR: speak_to_file falhou: {exc}")
        return JSONResponse(
            {"status": "error", "reason": "sapi5 indisponivel", "detail": str(exc)},
            status_code=503,
        )

    # Returns: WAV file
    from pathlib import Path
    wav_bytes = Path(wav_path).read_bytes()
    duration = len(wav_bytes) / 32000.0
    headers = {
        "Cache-Control": "no-store",
        "X-Jarvis-Engine": "sapi5",
        "X-Jarvis-Voice": "Microsoft Maria Desktop",
        "X-Jarvis-Duration": f"{duration:.2f}",
        "Content-Disposition": 'inline; filename="jarvis_sapi5.wav"',
    }
    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers=headers,
    )

    # SAPI5 fallback: le o WAV do disco e devolve.
    from pathlib import Path
    wav_bytes = Path(wav_path).read_bytes()
    fname = os.path.basename(wav_path)
    _append_log(
        f"OK: speak wav -> {len(wav_bytes)} bytes, sapi5 fallback"
    )
    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Content-Disposition": f'inline; filename="{fname}"',
            "X-Jarvis-Engine": "sapi5",
            "X-Jarvis-Duration": f"{duration:.2f}",
            "Content-Length": str(len(wav_bytes)),
        },
    )


def _wav_dur(wav_bytes: bytes) -> float:
    """Decode duration from a WAV blob's header (no temp file needed)."""
    try:
        import struct
        # 'RIFF' header
        if wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
            return 0.0
        # Walk chunks to find 'fmt ' and 'data'.
        pos = 12
        sample_rate = 0
        num_channels = 0
        bits_per_sample = 0
        data_size = 0
        while pos + 8 <= len(wav_bytes):
            chunk_id = wav_bytes[pos:pos + 4]
            chunk_size = struct.unpack("<I", wav_bytes[pos + 4:pos + 8])[0]
            if chunk_id == b"fmt ":
                fmt = wav_bytes[pos + 8:pos + 8 + chunk_size]
                if len(fmt) >= 16:
                    num_channels = struct.unpack("<H", fmt[2:4])[0]
                    sample_rate = struct.unpack("<I", fmt[4:8])[0]
                    bits_per_sample = struct.unpack("<H", fmt[14:16])[0]
            elif chunk_id == b"data":
                data_size = chunk_size
                break
            pos += 8 + chunk_size + (chunk_size % 2)
        if sample_rate <= 0 or num_channels <= 0 or bits_per_sample <= 0:
            return 0.0
        bytes_per_second = sample_rate * num_channels * bits_per_sample // 8
        return float(data_size) / float(bytes_per_second) if bytes_per_second else 0.0
    except Exception:
        return 0.0


@app.get("/api/audio/{filename}")
def api_audio(filename: str) -> Response:
    """Serve a generated WAV file for browser playback.

    Only files inside TextToSpeech/tmp_audio/ are served (path traversal
    blocked). Returns 404 if missing.
    """
    from TextToSpeech.Fast_DF_TTS import TMP_DIR
    safe = (filename or "").lstrip("/")
    if ".." in safe or "/" in safe or "\\" in safe:
        return Response(content="forbidden", status_code=403)
    full = (TMP_DIR / safe).resolve()
    if not str(full).startswith(str(TMP_DIR.resolve())):
        return Response(content="forbidden", status_code=403)
    if not full.exists() or not full.is_file():
        return Response(content="not found", status_code=404)
    return Response(
        content=full.read_bytes(),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "Accept-Ranges": "bytes",
        },
    )


@app.post("/api/ask")
def api_ask(payload: TextPayload) -> dict:
    """Send `text` to the brain."""
    from Brain.brain import Main_Brain
    return _safe_run(Main_Brain, payload.text)


@app.post("/api/hermes/ask")
def api_hermes_ask(payload: TextPayload) -> dict:
    """Ask Hermes a quick question. Returns the Hermes context block verbatim.

    Modo 3 (Modo 3 do plano 'conectar JARVIS a mente do Hermes'): manual,
    on-demand. Nao chama nenhum LLM externo — apenas devolve o contexto
    que JÁ ESTARIA injetado no prompt do JARVIS (memoria + projects index).

    Use cases reais:
      - "que projetos o usuario tem ativos?" -> Projects Index
      - "qual a persona do JARVIS?" -> memory.md
      - "quais tarefas estao pendentes hoje?" -> tasks

    Resposta rapida (sem custo de IA) — sempre < 200ms.
    """
    from Brain.hermes_bridge import get_hermes_context, journal_stats
    try:
        # force_refresh=True pra pegar snapshot mais recente do disco.
        ctx = get_hermes_context(jarvis_projects=None, force_refresh=True)
        if payload.text and payload.text.strip():
            # Filtra pelo termo: devolve so linhas que mencionam o termo.
            terms = [t.lower() for t in payload.text.split() if len(t) > 3]
            if terms:
                filtered = "\n".join(
                    line for line in ctx.splitlines()
                    if any(term in line.lower() for term in terms)
                )
                if filtered.strip():
                    ctx = filtered
        return {
            "status": "ok",
            "context": ctx,
            "journal": journal_stats(),
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/api/hermes/journal")
def api_hermes_journal(last_n: int = 30) -> dict:
    """Return the last `last_n` entries from jarvis_journal.md."""
    from Brain.hermes_bridge import read_journal, journal_stats
    try:
        return {
            "status": "ok",
            "entries": read_journal(last_n=last_n),
            "stats": journal_stats(),
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.post("/api/hermes/refresh")
def api_hermes_refresh() -> dict:
    """Force-rebuild the JARVIS projects index in ~/.hermes/memories/."""
    from Brain.hermes_bridge import sync_projects_index, invalidate_cache
    try:
        from Brain.memory import list_projects
        path = sync_projects_index(list_projects())
        invalidate_cache()
        return {"status": "ok", "index_path": path, "projects": len(list_projects())}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


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


# ---------- Briefing "cheguei em casa" ----------
@app.get("/api/briefing/arrival")
def briefing_arrival() -> JSONResponse:
    """O que o JARVIS fala pro Paulo quando ele chega em casa.

    Retorna texto natural (pt-BR) pronto pra TTS + estrutura com bullets
    caso o frontend queira renderizar também. Lê o estado atual do
    dashboard pra dar info em tempo real (sinais trade, agenda, email).

    Pensado pra 2 cenários de uso:
    1. TTS (voz pt-BR-AntonioNeural grave) via /api/tts/speak
    2. Visual na aba 'Chegada' do drawer (futuro)
    """
    from datetime import datetime, timezone, timedelta

    # Manaus = UTC-4 (sem DST)
    manaus_tz = timezone(timedelta(hours=-4))
    agora = datetime.now(manaus_tz)
    hora = agora.hour

    # 1) Saudação contextual
    if 5 <= hora < 12:
        saudacao = "Bom dia"
        periodo = "manhã"
    elif 12 <= hora < 18:
        saudacao = "Boa tarde"
        periodo = "tarde"
    else:
        saudacao = "Boa noite"
        periodo = "noite"

    # 2) Estado real do JARVIS (sinais trade recebidos)
    try:
        n_sinais = len(TRADE_SIGNAL_BUFFER)
        ultimo_sinal = TRADE_SIGNAL_BUFFER[-1] if TRADE_SIGNAL_BUFFER else None
        if ultimo_sinal:
            ev = ultimo_sinal.get("event", "?")
            ultimo_texto = (
                f"Último evento às {str(ultimo_sinal.get('timestamp', '?'))[:16]}: "
                f"{ev} - {ultimo_sinal.get('action', ultimo_sinal.get('summary', '?'))} "
                f"em {ultimo_sinal.get('symbol', '-')}."
            )
        else:
            ultimo_texto = "Sem sinais de trade hoje."
    except (NameError, Exception):
        n_sinais = 0
        ultimo_texto = "Buffer de trade ainda não inicializado."

    # 3) Próximo evento do Calendar (se houver)
    proximo_evento_txt = "Sem compromissos nas próximas horas."
    try:
        from datetime import datetime as _dt
        from Brain.actions import list_events as _list_events  # type: ignore
        # Janela de 24h à frente
        start_iso = agora.isoformat()
        end_iso = (agora + timedelta(hours=24)).isoformat()
        result = _list_events(time_min=start_iso, time_max=end_iso, max_results=3)
        eventos = result.get("events", []) if isinstance(result, dict) else []
        if eventos:
            ev = eventos[0]
            ev_start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
            try:
                ev_dt = _dt.fromisoformat(ev_start.replace("Z", "+00:00")).astimezone(manaus_tz)
                ev_hora = ev_dt.strftime("%H:%M")
            except Exception:
                ev_hora = "horário indefinido"
            proximo_evento_txt = (
                f"Próximo compromisso: {ev.get('summary', 'sem título')} às {ev_hora}."
            )
    except Exception:
        # Calendar pode não estar autenticado ainda — não bloqueia o briefing
        pass

    # 4) Pendências (lê do pc-runbook se existir)
    pendencias = [
        {
            "id": "bot-financas-fly",
            "titulo": "Bot Finanças 24/7 no Fly.io",
            "prioridade": "alta",
            "tempo_estimado": "15 min",
            "acao": "Rodar setup-rapido.ps1 com 4 secrets (TELEGRAM_BOT_TOKEN novo, etc).",
            "bloqueador": "Token Telegram precisa ser regenerado no @BotFather primeiro.",
        },
        {
            "id": "trade-telegram-fix",
            "titulo": "✅ Telegram do bot trade (HTTP 401)",
            "prioridade": "concluido",
            "tempo_estimado": "0",
            "acao": "Resolvido 20/07 18h via @BotFather. Bot @luaptrade_bot LIVE, mensagem msg_id 560 enviada com sucesso.",
            "bloqueador": "nenhum",
        },
        {
            "id": "whatsapp-jarvis-mvp",
            "titulo": "WhatsApp JARVIS — MVP ministerial",
            "prioridade": "media",
            "tempo_estimado": "1 fim de semana",
            "acao": "Provisionar chip Vivo + Meta Business Manager + devocional diário.",
            "bloqueador": "Aprovação Meta demora 1-3 dias.",
        },
        {
            "id": "limpezas",
            "titulo": "Limpezas opcionais",
            "prioridade": "baixa",
            "tempo_estimado": "5 min",
            "acao": "Deletar JARVIS duplicata em Documents/PROGRAMAÇÃO/. Adicionar remote no day-trade-bot (se quiser publicar).",
            "bloqueador": "nenhum",
        },
    ]

    # 5) Recomendação do que fazer AGORA
    # Lógica: se bot Finanças ainda não tá no Fly, essa é a próxima (desbloqueia
    # uso real). Senão, priorizar MVP WhatsApp. Telegram já tá OK (20/07 18h).
    pendencias = [p for p in pendencias if p["id"] != "trade-telegram-fix"]
    proxima_acao = pendencias[0]  # Bot Finanças Fly (próxima desbloqueada)
    proxima_acao_destaque = proxima_acao["acao"]

    # 6) Monta texto corrido pro TTS (sem repetir a info de sinais)
    if n_sinais > 0:
        linha_trade = f"Recebi {n_sinais} sinais de trade hoje. {ultimo_texto}"
    else:
        linha_trade = "Ainda não recebi sinais de trade hoje."

    texto_tts = (
        f"{saudacao}, Paulo. "
        f"Bem-vindo de volta. "
        f"São {hora}h{agora.minute:02d} da {periodo} em Manaus. "
        f"{proximo_evento_txt} "
        f"{linha_trade} "
        f"O Telegram do bot de trade já tá funcionando  token regenerado agora há pouco. "
        f"Próxima frente: fazer deploy do bot de Finanças no Fly.io, uns quinze minutos. "
        f"Tem o roteiro completo no Obsidian, na nota PC Runbook 2026-07-20. "
        f"Bom descanso. Se quiser, é só pedir e eu guio passo a passo."
    )

    return JSONResponse({
        "saudacao": saudacao,
        "periodo": periodo,
        "hora_local": agora.strftime("%H:%M"),
        "data_local": agora.strftime("%Y-%m-%d"),
        "timezone": "America/Manaus (UTC-4)",
        "proximo_evento": proximo_evento_txt,
        "sinais_trade": {
            "total_buffer": n_sinais,
            "ultimo": ultimo_texto,
        },
        "pendencias": pendencias,
        "proxima_acao_destaque": proxima_acao_destaque,
        "texto_tts": texto_tts,
        "gerado_em": agora.isoformat(),
    })


# ---------- Briefing "cheguei em casa" — versão ÁUDIO (TTS server-side) ----------
@app.get("/api/briefing/arrival/audio")
def briefing_arrival_audio() -> Response:
    """Gera MP3 com o briefing em voz pt-BR-AntonioNeural (grave).

    Usa Edge TTS (mesmo engine do jarvis-ai-assistant/.env). Retorna audio/mpeg
    pronto pra tocar no navegador via <audio src="..."> ou download.

    Padrão: voz 'pt-BR-AntonioNeural', rate -8%, pitch -4Hz (configurado em
    jarvis-persona.md como a voz "do JARVIS" — grave, ministerial).
    """
    # Reutiliza a lógica do briefing textual (não duplica)
    resp = briefing_arrival()
    payload = json.loads(resp.body)
    texto = payload["texto_tts"]

    # Edge TTS em thread separada (nao conflita com o event loop do FastAPI).
    # Usa temp file pq edge-tts tem API assincrona mas .save() simplifica.
    import tempfile
    import os as _os
    try:
        import edge_tts

        async def _synth(out_path: str) -> int:
            communicate = edge_tts.Communicate(
                texto,
                voice="pt-BR-AntonioNeural",
                rate="-8%",
                pitch="-4Hz",
            )
            await communicate.save(out_path)
            return _os.path.getsize(out_path)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
            tmp_path = tf.name
        try:
            import asyncio
            size = asyncio.run(_synth(tmp_path))
            with open(tmp_path, "rb") as fh:
                audio_bytes = fh.read()
        finally:
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {"error": "TTS falhou", "detail": str(exc)},
            status_code=500,
        )

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": 'inline; filename="briefing-chegada.mp3"',
            "Cache-Control": "no-store",
        },
    )


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