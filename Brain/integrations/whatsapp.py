"""WhatsApp Meta Cloud API — cliente de baixo nível.

Refs:
  - https://developers.facebook.com/docs/whatsapp/cloud-api
  - Setup: https://developers.facebook.com/docs/development/create-an-app

Env vars obrigatórias (NÃO commitá-las — só .env.example):
  WHATSAPP_PHONE_NUMBER_ID   -> id do número de telefone (formato "123456789012345")
  WHATSAPP_BUSINESS_ACCOUNT_ID  -> id da conta business (WABA)
  WHATSAPP_ACCESS_TOKEN      -> token permanente de System User (long-lived)
  WHATSAPP_VERIFY_TOKEN      -> string aleatória que você define (webhook challenge)
  WHATSAPP_WEBHOOK_URL       -> URL pública onde Meta vai POSTar (ex: ngrok)

Free tier Meta:
  - 1000 conversas/mês grátis (service conversations)
  - Primeiro 1000 service conversations = free
  - Rate limit: 80 msg/segundo

Funções expostas:
  - send_text_message(to_phone, body)              -> envia texto simples
  - send_template_message(to_phone, template, ...) -> envia template aprovado
  - mark_as_read(message_id)                      -> marca azulinho
  - verify_webhook(challenge, verify_token)        -> handshake do webhook
  - extract_message(payload)                      -> extrai msg útil do payload

Toda chamada retorna dict {"ok": bool, "..."}.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

LOG = logging.getLogger("jarvis.integrations.whatsapp")

# ---- Configuração via env (todas required, exceto verify) ----
PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
BUSINESS_ID = os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "jarvis-whatsapp-verify-2026")

API_VERSION = "v22.0"  # Graph API version (estável em 07/2026)
BASE_URL = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}"


def is_configured() -> bool:
    """Retorna True se as 3 credenciais essenciais estão presentes."""
    return bool(PHONE_NUMBER_ID and ACCESS_TOKEN and BUSINESS_ID)


def _request(method: str, url: str, payload: Optional[dict] = None) -> dict:
    """Wrapper urllib.request (sem dependência externa) pra POST/GET na Meta API."""
    if not is_configured():
        return {"ok": False, "error": "WhatsApp não configurado (env vars faltando)"}

    data = None
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "JARVIS/1.0 (WhatsApp Cloud)",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", errors="replace")
            return {"ok": True, "status": r.status, "body": json.loads(body) if body else {}}
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")
        LOG.error("WhatsApp %s %s -> HTTP %s: %s", method, url, e.code, body_txt[:200])
        return {
            "ok": False,
            "status": e.code,
            "error": body_txt,
            "error_code": json.loads(body_txt).get("error", {}).get("code") if body_txt else None,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        LOG.error("WhatsApp %s %s -> network: %s", method, url, e)
        return {"ok": False, "error": f"network: {e}"}


# ---- Mensagens: enviar texto/template ----

# Template de sinal (formato Pauleanderson/Pollar — usado pelo @luaptrade_bot)
# Variáveis:
#   {symbol}    -> "EUR/USD"
#   {time}      -> "12:50" (hora do sinal em Manaus TZ)
#   {direction} -> "COMPRA" (CALL) ou "VENDA" (PUT)
#   {direction_arrow} -> "⬆️" (CALL) ou "⬇️" (PUT)
#   {expiry}    -> "5min" (default M5)
#   {gale_info} -> "⏱ Martin Gale 1 - 5 Minutos Depois" ou "" se gale desativado
SIGNAL_TEMPLATE = """🚨 ATENÇÃO  🚨
🕛 Expiração: {expiry} ⏳
 ➖➖➖➖➖➖➖➖➖➖
💰👇🏼 OPERAÇÃO (Hora, Moeda, Sinal)

{symbol} {time}, {direction} {direction_arrow}
 ➖➖➖➖➖➖➖➖➖➖
 ⚠️ Em caso de LOSS: 
{gale_info}"""


def format_signal(
    symbol: str,
    time_str: str,
    direction: str,  # "CALL" | "PUT"
    expiry: str = "5min",
    gale_available: bool = True,
) -> str:
    """Formata uma mensagem de sinal usando o template Pauleanderson.

    Args:
        symbol: "EUR/USD" (formato com barra) ou "EURUSD-OTC" (auto-converte)
        time_str: "12:50" (já em Manaus TZ)
        direction: "CALL" -> COMPRA ⬆️ | "PUT" -> VENDA ⬇️
        expiry: "5min", "M5", "1h", etc
        gale_available: se True, adiciona "Martin Gale 1 - 5 Minutos Depois"
    """
    # Auto-converte formato OTC (EURUSD-OTC) pra com barra (EUR/USD)
    if "-" in symbol and "/" not in symbol:
        base = symbol.split("-")[0]
        if len(base) == 6:
            symbol = f"{base[:3]}/{base[3:]}"

    if direction.upper() == "CALL":
        direction_label = "COMPRA"
        arrow = "⬆️"
    elif direction.upper() == "PUT":
        direction_label = "VENDA"
        arrow = "⬇️"
    else:
        direction_label = direction.upper()
        arrow = ""

    gale_info = " \n ⏱ Martin Gale 1 - 5 Minutos Depois" if gale_available else ""

    return SIGNAL_TEMPLATE.format(
        symbol=symbol,
        time=time_str,
        direction=direction_label,
        direction_arrow=arrow,
        expiry=expiry,
        gale_info=gale_info,
    ).strip()


def send_signal_message(
    to_phone: str,
    symbol: str,
    time_str: str,
    direction: str,
    expiry: str = "5min",
    gale_available: bool = True,
    preview_only: bool = False,
) -> dict:
    """Envia um sinal formatado pro WhatsApp de um contato.

    Args:
        to_phone: '+5591987654321' (E.164)
        symbol, time_str, direction, expiry, gale_available: ver format_signal
        preview_only: se True, só retorna o texto formatado sem enviar (debug)

    Returns:
        {"ok": True, "preview": "texto formatado", "sent": bool}
        ou {"ok": False, "error": "..."}
    """
    body = format_signal(symbol, time_str, direction, expiry, gale_available)
    if preview_only or not is_configured():
        return {"ok": True, "preview": body, "sent": False, "preview_only": True}
    result = send_text_message(to_phone, body)
    result["preview"] = body
    return result


def send_text_message(to_phone: str, body: str, preview_url: bool = False) -> dict:
    """Envia mensagem de texto 1:1.

    Args:
        to_phone: número no formato E.164 (ex: '+5591987654321')
        body: até 4096 chars
        preview_url: se True, primeiro link do body vira preview (default False)
    """
    if not body:
        return {"ok": False, "error": "body vazio"}
    if len(body) > 4096:
        return {"ok": False, "error": f"body muito longo: {len(body)} chars (max 4096)"}

    url = f"{BASE_URL}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone.lstrip("+"),
        "type": "text",
        "text": {"preview_url": preview_url, "body": body},
    }
    return _request("POST", url, payload)


def send_template_message(
    to_phone: str,
    template_name: str,
    language_code: str = "pt_BR",
    components: Optional[list] = None,
) -> dict:
    """Envia mensagem usando template aprovado pela Meta.

    Necessário pra iniciar conversa (fora da janela de 24h).
    Templates precisam ser criados no Meta Business Manager > WhatsApp > Templates.
    """
    url = f"{BASE_URL}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone.lstrip("+"),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": components or [],
        },
    }
    return _request("POST", url, payload)


def mark_as_read(message_id: str) -> dict:
    """Marca mensagem como lida (azulinho). Algumas marcas usam isso pra UX."""
    return _request("POST", f"{BASE_URL}/messages", {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    })


# ---- Webhook: handshake + extração ----

def verify_webhook(mode: str, token: str, challenge: str) -> Optional[str]:
    """Verifica handshake inicial do webhook (GET request da Meta).

    Meta faz:  GET /webhook?hub.mode=subscribe&hub.verify_token=XXX&hub.challenge=YYY
    Se verify_token bater, retorna challenge.

    Returns:
        challenge string se OK, None se falhou.
    """
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge
    return None


def extract_message(payload: dict) -> Optional[dict]:
    """Extrai primeira mensagem útil do payload do webhook.

    Formato esperado do payload (simplificado):
    {
      "object": "whatsapp_business_account",
      "entry": [
        {
          "id": BUSINESS_ID,
          "changes": [
            {"value": {"messages": [{"from": "...", "text": {"body": "..."}, "id": "..."}]}}
          ]
        }
      ]
    }

    Returns:
        dict {"from": "+55...", "body": "texto", "message_id": "wamid...", "timestamp": int}
        ou None se não houver mensagem.
    """
    try:
        entry = payload.get("entry", [])
        if not entry:
            return None
        changes = entry[0].get("changes", [])
        if not changes:
            return None
        msgs = changes[0].get("value", {}).get("messages", [])
        if not msgs:
            return None
        msg = msgs[0]
        return {
            "from": msg.get("from", ""),
            "body": msg.get("text", {}).get("body", ""),
            "message_id": msg.get("id", ""),
            "timestamp": msg.get("timestamp", ""),
            "profile_name": changes[0].get("value", {}).get("contacts", [{}])[0]
            .get("profile", {}).get("name", "?"),
        }
    except (KeyError, IndexError, TypeError) as exc:
        LOG.warning("extract_message falhou: %s", exc)
        return None


# ---- Convenience: testar credenciais ----

def health_check() -> dict:
    """Verifica se token + phone_number_id estão válidos via GET /<phone_number_id>.

    Returns:
        dict com ok, phone_number, verified_name, status_code
    """
    if not is_configured():
        return {"ok": False, "error": "env vars faltando"}
    return _request("GET", f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}")
