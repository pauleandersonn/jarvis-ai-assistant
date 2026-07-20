"""Telegram Signal Linker — correlaciona sinais de trade com oportunidades.

Detecta quando:
  1. Um sinal CALL/PUT chega → vê se algum chat está discutindo esse par
  2. Vários sinais coincidem com chat movimentado → cria oportunidade
  'sinal_correlato' automaticamente
  3. Loss streak numa sessão → notifica Paulo "pessoal tá perdendo, talvez
     enviar mensagem motivacional no grupo"

Storage: usa mesmo DB de oportunidades (campo trade_signal_id).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

LOG = logging.getLogger("jarvis.actions.signal_linker")

MANAUS_TZ = timezone(timedelta(hours=-4))
DB_PATH = Path(os.environ.get("JARVIS_DATA_DIR", "./data")) / "trade_signals_history.db"

# Buffer em RAM: últimas N mensagens do Telegram por chat
# (recriado a cada restart — persistência fica no DB de oportunidades)
_RECENT_MESSAGES: dict[int, list[dict]] = {}  # chat_id -> [{text, ts, sender}]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trade_signals_history (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                direction TEXT,
                timestamp TIMESTAMP,
                signal_source TEXT,        -- 'day-trade-bot', 'manual', etc
                metadata_json TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ts ON trade_signals_history(timestamp)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol ON trade_signals_history(symbol)
        """)


def record_signal(
    symbol: str,
    direction: str,
    signal_source: str = "day-trade-bot",
    metadata: Optional[dict] = None,
) -> dict:
    """Registra um sinal de trade. Chamado pelo webhook trade-signal."""
    init_db()
    signal_id = str(uuid.uuid4())[:8]
    now = datetime.now(MANAUS_TZ).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO trade_signals_history (id, symbol, direction, timestamp, signal_source, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (signal_id, symbol.upper(), direction.upper(), now, signal_source,
             json.dumps(metadata or {}, ensure_ascii=False)),
        )
        conn.commit()
    return {"ok": True, "id": signal_id, "timestamp": now}


def get_signals_last_n_minutes(minutes: int = 30, symbol: Optional[str] = None) -> list[dict]:
    """Recupera sinais recentes (últimos N minutos)."""
    init_db()
    cutoff = (datetime.now(MANAUS_TZ) - timedelta(minutes=minutes)).isoformat()
    sql = "SELECT * FROM trade_signals_history WHERE timestamp >= ?"
    params = [cutoff]
    if symbol:
        sql += " AND symbol = ?"
        params.append(symbol.upper())
    sql += " ORDER BY timestamp DESC"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def add_recent_message(chat_id: int, sender_name: str, text: str) -> None:
    """Adiciona msg no buffer em RAM (mantém últimas 50 por chat)."""
    if chat_id not in _RECENT_MESSAGES:
        _RECENT_MESSAGES[chat_id] = []
    _RECENT_MESSAGES[chat_id].append({
        "sender": sender_name,
        "text": text,
        "ts": datetime.now(MANAUS_TZ).isoformat(),
    })
    # Mantém só últimas 50
    _RECENT_MESSAGES[chat_id] = _RECENT_MESSAGES[chat_id][-50:]


def get_recent_messages(chat_id: int, since_minutes: int = 30) -> list[dict]:
    """Mensagens recentes do chat (buffer RAM)."""
    from datetime import datetime as _dt
    cutoff = _dt.now(MANAUS_TZ) - timedelta(minutes=since_minutes)
    msgs = _RECENT_MESSAGES.get(chat_id, [])
    out = []
    for m in msgs:
        try:
            ts = _dt.fromisoformat(m["ts"])
            if ts >= cutoff:
                out.append(m)
        except (KeyError, ValueError):
            continue
    return out


def correlate_signal_with_messages(
    symbol: str,
    direction: str,
    recent_msgs: list[dict],
    minutes_window: int = 15,
) -> Optional[dict]:
    """Detecta se há conversa recente sobre esse par/direção.

    Returns:
        dict com chat_id, sender, msg_match se correlato, None se não.
    """
    if not recent_msgs:
        return None
    # Normaliza symbol pra "EURUSD" (sem barra / sem -OTC)
    symbol_norm = symbol.replace("/", "").replace("-OTC", "").upper()[:6]
    matches = []
    for msg in recent_msgs:
        text_upper = msg.get("text", "").upper()
        if symbol_norm in text_upper:
            matches.append(msg)
        elif direction.upper() in text_upper and any(w in text_upper for w in ("WIN", "LOSS", "ENTREI", "ENTRADA")):
            matches.append(msg)
    if not matches:
        return None
    return {
        "symbol": symbol,
        "direction": direction,
        "matched_count": len(matches),
        "window_minutes": minutes_window,
        "best_match": matches[-1],  # mais recente
    }


def generate_correlation_opportunity(correlation: dict, chat_id: int, chat_title: str) -> dict:
    """Cria uma oportunidade 'sinal_correlato' a partir de correlação detectada."""
    init_db()
    opp_id = str(uuid.uuid4())[:8]
    with sqlite3.connect(str(
        Path(os.environ.get("JARVIS_DATA_DIR", "./data")) / "telegram_opportunities.db"
    )) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """INSERT INTO telegram_opportunities (
                id, chat_id, chat_title, chat_type, sender_name, sender_id,
                message_id, message_text, analysis_json, category, score,
                lead_quente, summary, next_action
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                opp_id, chat_id, chat_title, "group", "sistema", 0,
                0, correlation["best_match"]["text"][:4000],
                json.dumps(correlation, ensure_ascii=False),
                "sinal_correlato", 0.75, 0,
                f"Pessoal falando de {correlation['symbol']} {correlation['direction']} - {correlation['matched_count']} msgs",
                "follow_up_1d",
            ),
        )
        conn.commit()
    LOG.info("oportunidade correlata criada: %s", opp_id)
    return {"ok": True, "id": opp_id, "correlation": correlation}
