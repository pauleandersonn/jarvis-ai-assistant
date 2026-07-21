"""
Finance webhook receiver — receives events from financas_bot.

Sender: financas_bot (src/integrations/jarvis_webhook.py) posts JSON
        events whenever a financial event of interest happens:
        - transaction.confirmed (new transação confirmada)
        - transaction.cancelled
        - budget.exceeded
        - opportunity.detected (ex: assinatura prestes a vencer)

Receiver: this module. Mounted on dashboard.py under
        /api/integrations/webhook/finance-event with bearer auth
        (JARVIS_DASHBOARD_FINANCE_WEBHOOK_TOKEN), ring buffer of 50
        events, WebSocket broadcast for live UI, and a /recent
        endpoint for cold-start backfill.

Pattern reference: cross-service-webhook-shared-secret skill,
verified 2026-07-20 on day-trade-bot -> JARVIS.
"""
from __future__ import annotations

import logging
import os
import time as _t
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

LOG = logging.getLogger("jarvis.integrations.finance_webhook")

# Ring buffer (most recent first on read, append on write).
FINANCE_EVENT_BUFFER: list[dict] = []
FINANCE_EVENT_BUFFER_MAX = 50


class FinanceWebhookPayload(BaseModel):
    """Schema do evento enviado pelo financas_bot.

    Campos mínimos exigidos: event_type, occurred_at, source="financas_bot".
    Campos extras são preservados no dict de saída (flexibilidade).
    """

    event_type: str = Field(..., description="transaction.confirmed | transaction.cancelled | budget.exceeded | opportunity.detected | custom")
    occurred_at: str = Field(..., description="ISO 8601 UTC, ex: 2026-07-20T22:30:00Z")
    source: str = Field(default="financas_bot")
    user_id: Optional[int] = None
    transaction_id: Optional[int] = None
    amount_brl: Optional[float] = None
    category: Optional[str] = None
    description: Optional[str] = None
    tx_type: Optional[str] = None  # "expense" | "income"
    confidence: Optional[float] = None
    extra: Optional[dict] = None  # payload extra (sem schema rígido)


def _validate_finance_token(authorization: Optional[str]) -> bool:
    """Bearer token check. Fail-closed if env not set."""
    expected = os.environ.get("JARVIS_DASHBOARD_FINANCE_WEBHOOK_TOKEN")
    if not expected:
        return False
    if not authorization:
        return False
    token = authorization
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    return len(token) == len(expected) and all(a == b for a, b in zip(token, expected))


def _append_ring_buffer(entry: dict) -> int:
    """Append to ring buffer; return new length."""
    FINANCE_EVENT_BUFFER.append(entry)
    if len(FINANCE_EVENT_BUFFER) > FINANCE_EVENT_BUFFER_MAX:
        del FINANCE_EVENT_BUFFER[: len(FINANCE_EVENT_BUFFER) - FINANCE_EVENT_BUFFER_MAX]
    return len(FINANCE_EVENT_BUFFER)


def _is_rate_limited(client_ip: str, max_per_min: int = 120) -> bool:
    """Per-IP rate limit. Returns True if over limit."""
    now = _t.time()
    if not hasattr(_is_rate_limited, "_rl"):
        _is_rate_limited._rl = {}
    rl = _is_rate_limited._rl
    bucket = rl.setdefault(client_ip, [])
    bucket[:] = [ts for ts in bucket if now - ts < 60]
    if len(bucket) >= max_per_min:
        return True
    bucket.append(now)
    return False


# ========= FastAPI handlers (mounted in dashboard.py) =========

async def post_finance_webhook(payload: FinanceWebhookPayload, request: Request) -> JSONResponse:
    """POST /api/integrations/webhook/finance-event

    Auth: Authorization: Bearer <JARVIS_DASHBOARD_FINANCE_WEBHOOK_TOKEN>
    Returns:
        200: {"ok": true, "id": "...", "buffered": N}
        401: missing/invalid Authorization
        429: rate limit exceeded (per-IP, 120/min default)
        503: webhook not configured (env unset → fail-closed)
    """
    auth = request.headers.get("authorization")
    if not os.environ.get("JARVIS_DASHBOARD_FINANCE_WEBHOOK_TOKEN"):
        return JSONResponse(
            {"ok": False, "error": "finance webhook disabled (set JARVIS_DASHBOARD_FINANCE_WEBHOOK_TOKEN)"},
            status_code=503,
        )
    if not _validate_finance_token(auth):
        return JSONResponse(
            {"ok": False, "error": "invalid or missing Authorization header"},
            status_code=401,
        )

    # Per-IP rate limit
    client_ip = request.client.host if request.client else "unknown"
    if _is_rate_limited(client_ip):
        LOG.warning("finance webhook rate-limit hit from %s", client_ip)
        return JSONResponse(
            {"ok": False, "error": "rate limit exceeded", "limit": 120, "window_seconds": 60},
            status_code=429,
        )

    entry_id = str(uuid.uuid4())
    # received_at uses UTC ISO with Z suffix (browser parses unambiguously)
    entry = {
        "id": entry_id,
        "received_at": datetime.utcnow().isoformat() + "Z",
        **payload.model_dump(),
    }
    new_len = _append_ring_buffer(entry)
    LOG.info(
        "finance webhook: %s from user=%s amount=R$%s (buffer=%d)",
        payload.event_type, payload.user_id, payload.amount_brl, new_len,
    )

    # Broadcast via WebSocket (best-effort; dead clients pruned automatically)
    try:
        from Brain.integrations.finance_webhook import ws_manager  # late import to avoid cycles
    except Exception:
        ws_manager = None
    if ws_manager is not None:
        try:
            await ws_manager.broadcast({"type": "finance_event", "data": entry})
        except Exception as exc:  # noqa: BLE001
            LOG.warning("ws broadcast failed (finance): %s", exc)

    return JSONResponse(
        {"ok": True, "id": entry_id, "buffered": new_len},
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


async def get_finance_recent(limit: int = 20) -> JSONResponse:
    """GET /api/integrations/finance/recent — backfill for late clients."""
    limit = max(1, min(int(limit), FINANCE_EVENT_BUFFER_MAX))
    recent = FINANCE_EVENT_BUFFER[-limit:][::-1]  # most recent first
    return JSONResponse(
        {"count": len(recent), "events": recent},
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


async def get_finance_stats() -> JSONResponse:
    """GET /api/integrations/finance/stats — buffer stats."""
    by_type: dict[str, int] = {}
    total_amount = 0.0
    for e in FINANCE_EVENT_BUFFER:
        t = e.get("event_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        amt = e.get("amount_brl")
        if isinstance(amt, (int, float)):
            total_amount += amt
    return JSONResponse(
        {
            "buffer_size": len(FINANCE_EVENT_BUFFER),
            "buffer_cap": FINANCE_EVENT_BUFFER_MAX,
            "by_event_type": by_type,
            "total_amount_brl_buffered": round(total_amount, 2),
            "webhook_enabled": bool(os.environ.get("JARVIS_DASHBOARD_FINANCE_WEBHOOK_TOKEN")),
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


# Will be set by dashboard.py at import time to avoid circular import.
ws_manager = None