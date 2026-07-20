"""Telegram Opportunity Analyzer — classifica mensagens com LLM.

Detecta oportunidades de negócio / soluções com IA em mensagens do Telegram.

Categorias:
  - lead_comercial       -> pessoa perguntando sobre serviço ou produto
  - problema_cliente     -> cliente insatisfeito ou com dúvida técnica
  - discussao_tecnica    -> conversa que pode virar ideia de produto/serviço
  - ideia_produto        -> feature request, sugestão, caso de uso
  - sinal_correlato      -> discussão sobre mercado/trade que se conecta a sinais
  - conversa_casual      -> sem valor comercial (não classifica como oportunidade)

Saída: dict com category, score (0-1), lead_quente, summary, next_action, etc.

Baseado no sketch whatsapp-jarvis-sketch.md (20/07) — agora expandido
pra Telegram (grupos + privados, com correlação com sinais de trade).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

LOG = logging.getLogger("jarvis.actions.telegram_analyzer")

ANALYZER_PROMPT = """Você é um assistente especializado em detectar oportunidades de negócio e soluções de IA em mensagens do Telegram.

Contexto: Paulo é empreendedor em Manaus-AM, trabalha com:
  • Day-trade binário (sinais M5)
  • Marketing digital (Meta Ads, Pollar Agência)
  • Fotografia e filmagem (PauleAnderson Filmes)
  • Bots Telegram/WhatsApp (Finanças, Trade)
  • Soluções com IA (claude/openai/ollama)

Sua tarefa: classificar a mensagem abaixo em UMA das categorias:

CATEGORIAS:
  • lead_comercial    - pessoa perguntando sobre serviço/produto ou orçamento
  • problema_cliente  - cliente insatisfeito ou com dúvida técnica resolvível
  • discussao_tecnica - conversa que pode virar ideia de produto/serviço
  • ideia_produto     - feature request, sugestão, caso de uso novo
  • sinal_correlato   - análise/discussão de mercado que se conecta a sinais
  - conversa_casual   - sem valor comercial (saudação, piada, off-topic)

SCORE (0 a 1): qualidade da oportunidade
  0.9-1.0 = lead quente, orçamento claro, ação imediata
  0.7-0.9 = oportunidade real, precisa follow-up
  0.4-0.7 = vale acompanhar
  <0.4    = marginal

LEAD_QUENTE: true se houver pedido explícito ou orçamento mencionado.

NEXT_ACTION:
  - "responder"       = responder na própria conversa
  - "follow_up_1d"    = agendar follow-up amanhã
  - "follow_up_7d"    = agendar follow-up em 7 dias
  - "arquivar"        = sem ação

Regras:
  1. Se a mensagem for cumprimento ou conversa casual, retorne
     category="conversa_casual", score=0.1, lead_quente=false
  2. Se houver R$ ou "quanto custa", é lead_comercial
  3. Se houver reclamação, é problema_cliente
  4. Se falar de feature nova ou "seria bom se tivesse", é ideia_produto
  5. Responda APENAS JSON, sem markdown

Formato de resposta OBRIGATÓRIO:
{
  "category": "lead_comercial|problema_cliente|discussao_tecnica|ideia_produto|sinal_correlato|conversa_casual",
  "score": 0.0,
  "lead_quente": false,
  "summary": "1 linha resumo (max 100 chars)",
  "next_action": "responder|follow_up_1d|follow_up_7d|arquivar",
  "orcamento_estimado": "R$ XXXX" | null,
  "prazo_mencionado": "string" | null,
  "palavras_chave": ["keyword1", "keyword2"],
  "sentimento": "positivo|neutro|negativo",
  "confianca": 0.0
}
"""


def _get_llm_client():
    try:
        sys_path = str(Path(__file__).parent.parent.parent)
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from Brain.llm_client import get_default_client
        return get_default_client()
    except ImportError:
        return None


# Triagem rápida sem LLM — economiza tokens
TRIGGER_WORDS = {
    "lead_comercial": [
        "quanto custa", "orçamento", "orcamento", "preço", "preco",
        "valor", "contratar", "proposta", "fechou", "fechar",
        "freelance", "prestador", "agência", "agencia",
        "você faz", "voce faz", "trabalha com",
    ],
    "problema_cliente": [
        "não funciona", "nao funciona", "bug", "erro", "problema",
        "reclamação", "reclamacao", "decepcionado", "ruim", "péssimo",
        "pessimo", "cancelar", "reembolso", "devolução", "devolucao",
        "suporte", "ajuda", "dúvida", "duvida",
    ],
    "ideia_produto": [
        "seria bom", "faltou", "faltando", "poderia ter", "preciso de",
        "preciso que", "feature", "ideia", "sugestão", "sugestao",
        "wishlist", "próxima versão", "proxima versao",
    ],
    "sinal_correlato": [
        "win", "loss", "gale", "entrada", "sinal", "call", "put",
        "eur/usd", "gbp", "usd", "otc", "binary", "binárias",
        "binarias", "trader", "trade", "operação", "operacao",
        "expiração", "expiracao", "candle",
    ],
}


def quick_keyword_scan(text: str) -> dict:
    """Triagem rápida sem LLM — retorna categoria provável + score base.

    Hierarquia (avalia em ordem, primeira que vence):
      1. problema_cliente (negativo forte)
      2. lead_comercial (orçamento/preço)
      3. ideia_produto (feature request)
      4. sinal_correlato (trade)
      5. discussao_tecnica (default)
    """
    text_lower = text.lower()
    # 1. Problema cliente
    if any(re.search(rf"\b{re.escape(w)}\b", text_lower) for w in [
        "não funciona", "nao funciona", "bug", "erro", "reclamação", "reclamacao",
        "decepcionado", "cancelar", "reembolso", "péssimo", "pessimo",
        "suporte", "ajuda com erro", "deu erro",
    ]):
        return {
            "category": "problema_cliente",
            "score": 0.75,
            "method": "keyword_scan",
        }
    # 2. Lead comercial (preço + algo que indique serviço)
    if re.search(r"r\$\s*\d|quanto custa|preço|valor|orçamento|orcamento|contratar|fechar|proposta", text_lower):
        return {
            "category": "lead_comercial",
            "score": 0.85,
            "method": "keyword_scan",
            "palavras_chave": ["preço"],
        }
    # 3. Ideia produto (feature request)
    if any(re.search(rf"\b{re.escape(w)}\b", text_lower) for w in [
        "seria bom", "faltou", "poderia ter", "preciso de", "feature", "ideia",
        "sugestão", "sugestao", "wishlist", "próxima versão",
    ]):
        return {
            "category": "ideia_produto",
            "score": 0.65,
            "method": "keyword_scan",
        }
    # 4. Sinal correlato (trade) - palavras mais específicas
    # (excluir palavras genéricas como "bot", "call", "put" que aparecem em outros contextos)
    # IMPORTANTE: usar \b (boundary) pra evitar "gale" match em "galera"
    has_signal_specific = any(re.search(rf"\b{re.escape(w)}\b", text_lower) for w in [
        "win", "loss", "gale", "entrada", "sinal", "eur/usd", "gbp/usd",
        "otc", "binary", "binarias", "candle", "expiração", "expiracao",
        "martingale", "martin gale",
    ])
    has_signal_currency = (
        re.search(r"\b(eur|gbp|usd|jpy|aud|cad)\b", text_lower)
        and any(re.search(rf"\b{re.escape(w)}\b", text_lower) for w in
                ["compra", "venda", "entrada", "sinal"])
    )
    if has_signal_specific or has_signal_currency:
        return {
            "category": "sinal_correlato",
            "score": 0.6,
            "method": "keyword_scan",
        }
    # 5. Conversa casual
    return {"category": "conversa_casual", "score": 0.1, "method": "keyword_scan"}


def analyze_message(
    text: str,
    chat_context: Optional[str] = None,
    sender_name: Optional[str] = None,
    vertical: str = "auto",
) -> dict:
    """Analisa uma mensagem com LLM e retorna classificação.

    Args:
        text: conteúdo da mensagem (até 4000 chars)
        chat_context: contexto do chat (nome do grupo, etc)
        sender_name: nome do remetente (pra contexto)
        vertical: filtro de vertical ou "auto"

    Returns:
        dict {"ok": bool, "analysis": {...}, "tokens_used": int}
    """
    if not text or not text.strip():
        return {"ok": False, "error": "texto vazio"}

    # 1) Triagem rápida (sempre roda)
    quick = quick_keyword_scan(text)
    if quick["category"] == "conversa_casual":
        # Provavelmente não vale o custo de chamar LLM
        return {
            "ok": True,
            "analysis": {
                **quick,
                "lead_quente": False,
                "summary": text[:80],
                "next_action": "arquivar",
                "confianca": 0.3,
                "orcamento_estimado": None,
                "prazo_mencionado": None,
                "sentimento": "neutro",
            },
            "tokens_used": 0,
            "skipped_llm": True,
        }

    # 2) Tenta LLM, mas se não tiver provedor configurado usa heurística avançada
    try:
        from Brain.llm_client import complete as llm_complete
        # Só tenta LLM se pelo menos 1 provedor tiver env var
        has_provider = any([
            os.environ.get("OPENROUTER_API_KEY"),
            os.environ.get("ANTHROPIC_API_KEY"),
            os.environ.get("HERMES_PROXY_URL"),
        ])
        if not has_provider:
            return _heuristic_fallback(text, quick)

        user_prompt = (
            f"Classifique a mensagem abaixo.\n"
            f"Remetente: {sender_name or 'desconhecido'}\n"
            f"Contexto do chat: {chat_context or 'privado'}\n"
            f"Vertical: {vertical}\n\n"
            f"Mensagem:\n{text[:3500]}\n\nResponda APENAS com JSON válido conforme o formato especificado."
        )
        raw = llm_complete(user_prompt, system=ANALYZER_PROMPT, max_tokens=600)
        raw = raw.strip()
        raw_clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        analysis = json.loads(raw_clean)
        return {
            "ok": True,
            "analysis": analysis,
            "tokens_used": len(raw_clean.split()) * 1.3,
        }
    except json.JSONDecodeError:
        # LLM retornou lixo — cai pra heurística
        LOG.warning("LLM retornou JSON inválido, usando heurística")
        return _heuristic_fallback(text, quick)
    except Exception as exc:
        LOG.warning("LLM falhou (%s), usando heurística", exc)
        return _heuristic_fallback(text, quick)


def _heuristic_fallback(text: str, quick: dict) -> dict:
    """Fallback sem LLM: usa keywords + heurística pra classificar.

    Útil quando:
      - Nenhum provedor LLM configurado
      - LLM retornou JSON inválido
      - Rate limit / outage

    Categorias cobertas: lead_comercial, problema_cliente, ideia_produto,
    sinal_correlato, discussao_tecnica.
    """
    text_lower = text.lower()
    # Refinar: detectar orçamento, prazo, claim de lead_quente
    tem_preco = bool(re.search(r"r\$\s*\d|quanto custa|preço|valor|orçamento", text_lower))
    tem_problema = any(w in text_lower for w in [
        "não funciona", "nao funciona", "bug", "erro", "reclama",
        "cancelar", "reembolso", "péssimo", "pessimo",
    ])
    tem_prazo = bool(re.search(
        r"\b(amanhã|amanha|hoje|essa semana|próxima semana|proxima semana|neste mês|neste mes|próximo mês)\b",
        text_lower,
    ))
    tem_feature = any(w in text_lower for w in [
        "seria bom", "faltou", "poderia ter", "preciso de", "ideia", "feature",
    ])
    tem_sinal = any(w in text_lower for w in [
        "win", "loss", "gale", "entrada", "sinal", "call", "put",
        "eur/usd", "gbp", "otc", "binary", "trade", "candle",
    ])
    lead_quente = tem_preco or tem_problema
    summary = text[:80].strip()
    next_action = "responder" if lead_quente else "follow_up_1d"
    return {
        "ok": True,
        "analysis": {
            "category": quick["category"],
            "score": max(quick["score"], 0.7 if lead_quente else 0.5),
            "lead_quente": lead_quente,
            "summary": summary,
            "next_action": next_action,
            "orcamento_estimado": "mencionado" if tem_preco else None,
            "prazo_mencionado": "mencionado" if tem_prazo else None,
            "palavras_chave": quick.get("palavras_chave", []),
            "sentimento": "negativo" if tem_problema else "neutro",
            "confianca": 0.6,
            "method": "heuristic_fallback",
        },
        "tokens_used": 0,
        "skipped_llm": True,
    }


def generate_daily_brief(opportunities: list[dict]) -> str:
    """Gera texto TTS-friendly resumindo as top oportunidades do dia.

    Pensado pra briefing matinal via Telegram bot.
    """
    if not opportunities:
        return "Sem oportunidades novas no Telegram hoje. Tudo tranquilo."

    n = len(opportunities)
    header = f"Tem {n} oportunidades novas no Telegram hoje."
    lines = [header, ""]
    for i, opp in enumerate(opportunities[:5], 1):
        cat_label = {
            "lead_comercial": "Lead comercial",
            "problema_cliente": "Problema de cliente",
            "discussao_tecnica": "Discussão técnica",
            "ideia_produto": "Ideia de produto",
            "sinal_correlato": "Sinal correlato",
        }.get(opp["category"], opp["category"])
        sender = opp.get("sender_name") or "?"
        chat = opp.get("chat_title") or "privado"
        summary = opp.get("summary", "")[:80]
        quente = " QUENTE" if opp.get("lead_quente") else ""
        lines.append(
            f"{i}. {cat_label}{quente} — {sender} ({chat}): {summary}"
        )
    lines.append("")
    lines.append(f"Acesse /api/integrations/telegram/opportunities pra detalhes.")
    return "\n".join(lines)