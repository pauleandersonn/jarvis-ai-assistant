"""Storage de oportunidades detectadas no Telegram.

Schema:
  telegram_opportunities (
    id TEXT PRIMARY KEY,
    chat_id INTEGER,           -- id numérico do chat/grupo no Telegram
    chat_title TEXT,           -- 'João da Silva' ou 'Grupo Trade Signals'
    chat_type TEXT,            -- 'private' | 'group' | 'channel' | 'supergroup'
    sender_name TEXT,          -- quem mandou a mensagem
    sender_id INTEGER,         -- id do remetente
    message_id INTEGER,        -- id da msg dentro do chat
    message_text TEXT,         -- texto (até 4000 chars)
    analysis_json TEXT,        -- análise completa do LLM
    category TEXT,             -- 'lead_comercial' | 'problema_cliente' | 'discussao_tecnica' | 'ideia_produto' | 'sinal_correlato'
    score REAL,                -- 0..1, qualidade da oportunidade
    lead_quente INTEGER,       -- 0/1: follow-up imediato?
    summary TEXT,              -- 1 linha
    next_action TEXT,          -- 'responder' | 'arquivar' | 'agendar' | 'follow_up_1d' | 'follow_up_7d'
    orcamento_estimado TEXT,   -- 'R$ 1500' ou NULL
    prazo_mencionado TEXT,     -- 'próximo sábado' ou NULL
    trade_signal_id TEXT,      -- FK pra telegram_trade_signals.id (se correlato)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'novo',-- 'novo'|'contatado'|'convertido'|'perdido'|'arquivado'
    contacted_at TIMESTAMP,
    notes TEXT
  )

Funções expostas:
  add_opportunity(...)
  list_opportunities(filters...)
  update_status(id, status, notes)
  link_to_signal(opp_id, signal_id)
  get_top_opportunities(limit)
  get_stats()
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

LOG = logging.getLogger("jarvis.integrations.telegram_opportunities")

DB_PATH = Path(os.environ.get("JARVIS_DATA_DIR", "./data")) / "telegram_opportunities.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Cria tabelas se não existirem. Idempotente."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telegram_opportunities (
                id TEXT PRIMARY KEY,
                chat_id INTEGER,
                chat_title TEXT,
                chat_type TEXT,
                sender_name TEXT,
                sender_id INTEGER,
                message_id INTEGER,
                message_text TEXT,
                analysis_json TEXT,
                category TEXT,
                score REAL,
                lead_quente INTEGER DEFAULT 0,
                summary TEXT,
                next_action TEXT,
                orcamento_estimado TEXT,
                prazo_mencionado TEXT,
                trade_signal_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'novo',
                contacted_at TIMESTAMP,
                notes TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_category ON telegram_opportunities(category)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_status ON telegram_opportunities(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_quente ON telegram_opportunities(lead_quente)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_score ON telegram_opportunities(score DESC)
        """)


def add_opportunity(
    *,
    chat_id: int,
    chat_title: str,
    chat_type: str,
    sender_name: str,
    sender_id: int,
    message_id: int,
    message_text: str,
    analysis: dict,
    trade_signal_id: Optional[str] = None,
) -> dict:
    """Insere oportunidade detectada."""
    init_db()
    opp_id = str(uuid.uuid4())[:8]
    category = analysis.get("category", "indefinido")
    score = float(analysis.get("score", 0.5))
    lead_quente = bool(analysis.get("lead_quente", False))
    summary = (analysis.get("summary") or "")[:200]
    next_action = analysis.get("next_action", "arquivar")
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO telegram_opportunities (
                id, chat_id, chat_title, chat_type, sender_name, sender_id,
                message_id, message_text, analysis_json, category, score,
                lead_quente, summary, next_action, orcamento_estimado,
                prazo_mencionado, trade_signal_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opp_id, chat_id, chat_title, chat_type, sender_name, sender_id,
                message_id, message_text[:4000], json.dumps(analysis, ensure_ascii=False),
                category, score, int(lead_quente), summary, next_action,
                analysis.get("orcamento_estimado"), analysis.get("prazo_mencionado"),
                trade_signal_id,
            ),
        )
        conn.commit()
    LOG.info("oportunidade Telegram %s adicionada: %s (chat=%s)", opp_id, category, chat_id)
    return {"ok": True, "id": opp_id, "category": category, "score": score}


def list_opportunities(
    category: Optional[str] = None,
    status: Optional[str] = None,
    min_score: float = 0.0,
    only_hot: bool = False,
    limit: int = 50,
) -> list[dict]:
    """Lista oportunidades com filtros. Mais recentes primeiro."""
    init_db()
    sql = "SELECT * FROM telegram_opportunities WHERE score >= ?"
    params: list = [min_score]
    if category:
        sql += " AND category = ?"
        params.append(category)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if only_hot:
        sql += " AND lead_quente = 1"
    sql += " ORDER BY lead_quente DESC, score DESC, created_at DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def update_status(
    opp_id: str,
    status: str,
    notes: Optional[str] = None,
) -> bool:
    """Atualiza status. Marca contacted_at se for contatado."""
    if status not in ("novo", "contatado", "convertido", "perdido", "arquivado"):
        return False
    init_db()
    with _connect() as conn:
        if status == "contatado":
            cursor = conn.execute(
                "UPDATE telegram_opportunities SET status=?, notes=?, contacted_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, notes, opp_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE telegram_opportunities SET status=?, notes=? WHERE id=?",
                (status, notes, opp_id),
            )
        conn.commit()
        return cursor.rowcount > 0


def link_to_signal(opp_id: str, signal_id: str) -> bool:
    """Liga uma oportunidade a um sinal de trade (correlação)."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE telegram_opportunities SET trade_signal_id=? WHERE id=?",
            (signal_id, opp_id),
        )
        conn.commit()
        return cur.rowcount > 0


def get_top_opportunities(limit: int = 5) -> list[dict]:
    """Top N oportunidades pra briefing diário — só as hot+novas."""
    return list_opportunities(
        status="novo", only_hot=True, min_score=0.7, limit=limit
    )


def get_stats() -> dict:
    """Estatísticas agregadas — usado pelo dashboard."""
    init_db()
    with _connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as n FROM telegram_opportunities"
        ).fetchone()["n"]
        hot = conn.execute(
            "SELECT COUNT(*) as n FROM telegram_opportunities WHERE lead_quente=1 AND status='novo'"
        ).fetchone()["n"]
        by_category = conn.execute(
            "SELECT category, COUNT(*) as n FROM telegram_opportunities "
            "GROUP BY category ORDER BY n DESC LIMIT 10"
        ).fetchall()
        by_status = conn.execute(
            "SELECT status, COUNT(*) as n FROM telegram_opportunities "
            "GROUP BY status"
        ).fetchall()
        converted = conn.execute(
            "SELECT COUNT(*) as n FROM telegram_opportunities WHERE status='convertido'"
        ).fetchone()["n"]
        avg_score = conn.execute(
            "SELECT AVG(score) as s FROM telegram_opportunities"
        ).fetchone()["s"] or 0
    return {
        "total": total,
        "hot_leads_pendentes": hot,
        "convertidos": converted,
        "taxa_conversao": round(converted / total * 100, 1) if total else 0,
        "score_medio": round(avg_score, 2),
        "by_category": {r["category"]: r["n"] for r in by_category},
        "by_status": {r["status"]: r["n"] for r in by_status},
    }
