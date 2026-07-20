"""Church Radar Store — SQLite storage de contas, oportunidades e conteúdo gerado.

3 tabelas:
  - monitored_accounts: contas de igrejas no IG/FB que o JARVIS monitora
  - radar_items: oportunidades detectadas (visitantes, pedidos oração, crises)
  - generated_content: devocionais/posts gerados pelo JARVIS

DB: ./data/church_radar.db
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

MANAUS_TZ = timezone(timedelta(hours=-4))
DB_PATH = Path(os.environ.get("JARVIS_DATA_DIR", "./data")) / "church_radar.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS monitored_accounts (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,           -- 'instagram' | 'facebook'
                handle TEXT NOT NULL,             -- @lagoinhamanaus
                church_name TEXT,
                denomination TEXT,                -- 'evangelica' | 'catolica' | 'pentecostal' | etc
                city TEXT,
                state TEXT,
                notes TEXT,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP,
                last_scanned_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS radar_items (
                id TEXT PRIMARY KEY,
                account_id TEXT,
                platform TEXT,
                source TEXT,                      -- 'comment', 'dm', 'post', 'ad'
                source_id TEXT,                   -- ID do post/comment no Meta
                author_name TEXT,
                author_handle TEXT,
                raw_text TEXT,
                themes_json TEXT,                 -- ["sermao", "oracao"]
                opportunities_json TEXT,          -- ["visitante_engajado", "pedido_oracao"]
                urgency TEXT,                     -- 'alta' | 'media' | 'baixa'
                suggested_action TEXT,
                score REAL,
                status TEXT DEFAULT 'novo',       -- 'novo' | 'acionado' | 'resolvido' | 'arquivado'
                contacted_at TIMESTAMP,
                notes TEXT,
                detected_at TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES monitored_accounts(id)
            );

            CREATE TABLE IF NOT EXISTS generated_content (
                id TEXT PRIMARY KEY,
                kind TEXT,                        -- 'devocional' | 'post_instagram' | 'post_facebook' | 'post_reels'
                theme TEXT,
                title TEXT,
                content_json TEXT,                -- dict com verse/reflection/prayer/share_text OU copy/hashtags/cta
                used_in_post_id TEXT,             -- se foi postado, linka ao post
                created_at TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_radar_account ON radar_items(account_id);
            CREATE INDEX IF NOT EXISTS idx_radar_status ON radar_items(status);
            CREATE INDEX IF NOT EXISTS idx_radar_urgency ON radar_items(urgency);
            CREATE INDEX IF NOT EXISTS idx_radar_detected ON radar_items(detected_at);
            CREATE INDEX IF NOT EXISTS idx_content_kind ON generated_content(kind);
            CREATE INDEX IF NOT EXISTS idx_content_theme ON generated_content(theme);
        """)


def add_account(platform: str, handle: str, church_name: str = "",
                denomination: str = "", city: str = "", state: str = "",
                notes: str = "") -> dict:
    init_db()
    acc_id = str(uuid.uuid4())[:8]
    now = datetime.now(MANAUS_TZ).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO monitored_accounts (
                id, platform, handle, church_name, denomination, city, state, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (acc_id, platform, handle, church_name, denomination, city, state, notes, now),
        )
        conn.commit()
    return {"id": acc_id, "handle": handle, "platform": platform, "created_at": now}


def list_accounts(active_only: bool = True) -> list[dict]:
    init_db()
    sql = "SELECT * FROM monitored_accounts"
    params = []
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY church_name, handle"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_account(acc_id: str) -> Optional[dict]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM monitored_accounts WHERE id = ?", (acc_id,)).fetchone()
        return dict(row) if row else None


def update_last_scanned(acc_id: str) -> None:
    init_db()
    now = datetime.now(MANAUS_TZ).isoformat()
    with _connect() as conn:
        conn.execute(
            "UPDATE monitored_accounts SET last_scanned_at = ? WHERE id = ?",
            (now, acc_id),
        )
        conn.commit()


def add_radar_item(account_id: str = "", platform: str = "", source: str = "",
                   source_id: str = "", author_name: str = "", author_handle: str = "",
                   raw_text: str = "", themes: list[str] = None,
                   opportunities: list[str] = None, urgency: str = "baixa",
                   suggested_action: str = "arquivar", score: float = 0.0,
                   notes: str = "") -> dict:
    init_db()
    item_id = str(uuid.uuid4())[:8]
    now = datetime.now(MANAUS_TZ).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO radar_items (
                id, account_id, platform, source, source_id, author_name, author_handle,
                raw_text, themes_json, opportunities_json, urgency, suggested_action,
                score, status, notes, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'novo', ?, ?)""",
            (
                item_id, account_id, platform, source, source_id,
                author_name, author_handle, raw_text,
                json.dumps(themes or [], ensure_ascii=False),
                json.dumps(opportunities or [], ensure_ascii=False),
                urgency, suggested_action, score, notes, now,
            ),
        )
        conn.commit()
    return {"id": item_id, "detected_at": now}


def list_radar_items(status: str = "", urgency: str = "", account_id: str = "",
                     limit: int = 50) -> list[dict]:
    init_db()
    sql = "SELECT * FROM radar_items WHERE 1=1"
    params = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if urgency:
        sql += " AND urgency = ?"
        params.append(urgency)
    if account_id:
        sql += " AND account_id = ?"
        params.append(account_id)
    sql += " ORDER BY detected_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        # Decodifica JSONs
        for r in rows:
            r["themes"] = json.loads(r.pop("themes_json", "[]") or "[]")
            r["opportunities"] = json.loads(r.pop("opportunities_json", "[]") or "[]")
        return rows


def update_radar_status(item_id: str, status: str, notes: str = "") -> bool:
    init_db()
    now = datetime.now(MANAUS_TZ).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE radar_items SET status = ?, contacted_at = ?, notes = ? WHERE id = ?",
            (status, now, notes, item_id),
        )
        conn.commit()
        return cur.rowcount > 0


def add_generated_content(kind: str, theme: str, title: str,
                          content: dict, used_in_post_id: str = "") -> dict:
    init_db()
    content_id = str(uuid.uuid4())[:8]
    now = datetime.now(MANAUS_TZ).isoformat()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO generated_content (
                id, kind, theme, title, content_json, used_in_post_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                content_id, kind, theme, title,
                json.dumps(content, ensure_ascii=False),
                used_in_post_id, now,
            ),
        )
        conn.commit()
    return {"id": content_id, "created_at": now}


def list_generated_content(kind: str = "", theme: str = "",
                            limit: int = 50) -> list[dict]:
    init_db()
    sql = "SELECT * FROM generated_content WHERE 1=1"
    params = []
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if theme:
        sql += " AND theme LIKE ?"
        params.append(f"%{theme}%")
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for r in rows:
            r["content"] = json.loads(r.pop("content_json", "{}") or "{}")
        return rows


def get_stats() -> dict:
    init_db()
    with _connect() as conn:
        accounts = conn.execute("SELECT COUNT(*) AS c FROM monitored_accounts WHERE active = 1").fetchone()["c"]
        items_total = conn.execute("SELECT COUNT(*) AS c FROM radar_items").fetchone()["c"]
        items_new = conn.execute("SELECT COUNT(*) AS c FROM radar_items WHERE status='novo'").fetchone()["c"]
        items_high = conn.execute("SELECT COUNT(*) AS c FROM radar_items WHERE urgency='alta' AND status='novo'").fetchone()["c"]
        # Conta oportunidades (parseia JSON em Python — robusto)
        by_opp = {}
        rows = conn.execute("SELECT opportunities_json FROM radar_items WHERE opportunities_json IS NOT NULL AND opportunities_json != '[]'").fetchall()
        for row in rows:
            try:
                opps = json.loads(row["opportunities_json"])
                for o in opps:
                    by_opp[o] = by_opp.get(o, 0) + 1
            except (json.JSONDecodeError, TypeError):
                continue
        by_opp = dict(sorted(by_opp.items(), key=lambda x: -x[1])[:10])
        content_total = conn.execute("SELECT COUNT(*) AS c FROM generated_content").fetchone()["c"]
        return {
            "accounts_monitored": accounts,
            "items_total": items_total,
            "items_new": items_new,
            "items_high_urgency": items_high,
            "items_by_opportunity": by_opp,
            "content_generated_total": content_total,
        }
