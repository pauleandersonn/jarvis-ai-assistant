"""Storage de oportunidades detectadas — SQLite leve.

Schema:
  opportunities (
    id TEXT PRIMARY KEY,
    chat_phone TEXT,        -- '+5591987654321'
    chat_name TEXT,         -- 'João da Silva'
    vertical TEXT,          -- 'fotografia' | 'filmagem' | etc
    summary TEXT,           -- resumo em 1 linha
    intent TEXT,            -- pergunta|orcamento|pedido|etc
    priority INTEGER,       -- 1 (máxima) a 5
    orcamento_estimado TEXT,-- 'R$ 1500' ou NULL
    prazo_mencionado TEXT,  -- 'próximo sábado' ou NULL
    mensagem_id TEXT,       -- wamid do WhatsApp
    raw_message TEXT,       -- texto original
    analysis_json TEXT,     -- JSON completo da análise LLM
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'novo'  -- novo|contatado|convertido|perdido
  )

Funções:
  add_opportunity(...)     -> dict (com id gerado)
  list_opportunities(...)  -> lista de dicts
  update_status(id, status)-> bool
  get_stats()              -> dict com totais por vertical
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

LOG = logging.getLogger("jarvis.integrations.opportunities")

# DB local (relativa ao JARVIS cwd — padrão em Data/)
DB_PATH = Path(os.environ.get("JARVIS_DATA_DIR", "./data")) / "opportunities.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Cria tabela se não existir. Idempotente."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id TEXT PRIMARY KEY,
                chat_phone TEXT,
                chat_name TEXT,
                vertical TEXT,
                summary TEXT,
                intent TEXT,
                priority INTEGER,
                orcamento_estimado TEXT,
                prazo_mencionado TEXT,
                mensagem_id TEXT,
                raw_message TEXT,
                analysis_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'novo'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vertical ON opportunities(vertical)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_priority ON opportunities(priority)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON opportunities(status)")


def add_opportunity(
    *,
    chat_phone: str,
    chat_name: str,
    analysis: dict,
    raw_message: str,
    mensagem_id: Optional[str] = None,
) -> dict:
    """Insere uma oportunidade no DB.

    Args:
        chat_phone: '+55...'
        chat_name: nome do contato (se conhecido)
        analysis: dict retornado por LLM (precisa ter 'vertical_match', etc)
        raw_message: texto original da mensagem do WhatsApp
        mensagem_id: wamid (id único do WhatsApp)
    """
    init_db()
    opp_id = str(uuid.uuid4())[:8]
    vertical = (
        analysis.get("vertical_match", [None])[0]
        if analysis.get("vertical_match")
        else "indefinido"
    )
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO opportunities (
                id, chat_phone, chat_name, vertical, summary, intent,
                priority, orcamento_estimado, prazo_mencionado,
                mensagem_id, raw_message, analysis_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opp_id,
                chat_phone,
                chat_name,
                vertical,
                analysis.get("resumo_1_linha", "")[:200],
                analysis.get("intencao", "desconhecida"),
                analysis.get("prioridade", 3),
                analysis.get("orcamento_estimado"),
                analysis.get("prazo_mencionado"),
                mensagem_id,
                raw_message[:4000],
                json.dumps(analysis, ensure_ascii=False),
            ),
        )
        conn.commit()
    LOG.info("oportunidade %s adicionada: %s [%s]", opp_id, vertical, chat_phone)
    return {"ok": True, "id": opp_id, "vertical": vertical}


def list_opportunities(
    vertical: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Lista oportunidades com filtros opcionais."""
    init_db()
    sql = "SELECT * FROM opportunities WHERE 1=1"
    params = []
    if vertical:
        sql += " AND vertical = ?"
        params.append(vertical)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY priority ASC, created_at DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def update_status(opp_id: str, status: str) -> bool:
    """Marca oportunidade como novo/contatado/convertido/perdido."""
    if status not in ("novo", "contatado", "convertido", "perdido"):
        return False
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE opportunities SET status = ? WHERE id = ?", (status, opp_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_stats() -> dict:
    """Estatísticas agregadas por vertical + status."""
    init_db()
    with _connect() as conn:
        by_vertical = conn.execute(
            "SELECT vertical, COUNT(*) as n FROM opportunities GROUP BY vertical"
        ).fetchall()
        by_status = conn.execute(
            "SELECT status, COUNT(*) as n FROM opportunities GROUP BY status"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) as n FROM opportunities").fetchone()
        hot_leads = conn.execute(
            "SELECT COUNT(*) as n FROM opportunities WHERE priority <= 2"
        ).fetchone()
    return {
        "total": total["n"],
        "hot_leads": hot_leads["n"],
        "by_vertical": {r["vertical"]: r["n"] for r in by_vertical},
        "by_status": {r["status"]: r["n"] for r in by_status},
    }
