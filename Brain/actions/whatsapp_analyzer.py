"""WhatsApp Analyzer — detecta oportunidades de negócio via LLM.

Função principal:
  analyze_conversation(text, vertical="auto") -> dict

Vertical pode ser:
  - "fotografia"      (trabalhos fotográficos, ensaios, eventos)
  - "filmagem"        (v...[truncated] ----

Detecta:
  - Intenção de negócio (cliente perguntando, indicando orçamento, etc)
  - Serviços mencionados (cobertura de evento, edição, etc)
  - Verticais aplicáveis
  - Próximo passo sugerido (resposta proativa, follow-up, etc)

Baseado no sketch em Memory/Projects/whatsapp-jarvis-sketch.md (20/07).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

LOG = logging.getLogger("jarvis.actions.whatsapp_analyzer")

# Carrega prompt-base do prompt.txt do Brain (já existe)
_PROMPT_PATH = Path(__file__).parent.parent / "prompt.txt"

# Prompt especializado pra análise de oportunidades
ANALYZER_PROMPT = """Você é um assistente especializado em detectar oportunidades de negócio em conversas de WhatsApp.

Foco: identificar se a mensagem contém um pedido real, orçamento mencionado,
prazo, ou interesse em contratar serviços — mesmo que indiretamente.

Verticais que você conhece:
  • fotografia       → ensaios, eventos, produtos, retratos, casamentos
  • filmagem         → vídeos institucionais, weddings, cobertura de cultos
  • tecnol...[truncated]

Regras:
  1. Se a conversa é genérica (cumprimento, pergunta casual), retorne "vertical_match": []
  2. Se houver orçamento (R$, valor, "quanto custa"), mencione em "orcamento_estimado"
  3. Se houver prazo ("pra amanhã", "próximo mês"), mencione em "prazo_mencionado"
  4. Seja conservador: só marque como "lead_quente" se houver pedido explícito
  5. Responda APENAS JSON, sem markdown, sem texto adicional

Formato OBRIGATÓRIO de resposta:
{
  "intencao": "pergunta|orcamento|pedido|reclamacao|conversa_casual",
  "lead_quente": true|false,
  "vertical_match": ["fotografia", "filmagem", ...],
  "orcamento_estimado": "R$ XXXX" | null,
  "prazo_mencionado": "string" | null,
  "palavras_chave": ["keyword1", "keyword2"],
  "sentimento": "positivo|neutro|negativo",
  "resumo_1_linha": "string curta (max 80 chars)",
  "acao_sugerida": "responder|arquivar|follow_up|ignorar",
  "prioridade": 1|2|3|4|5
}
"""


def _get_llm_client():
    """Import lazy do LLM client do JARVIS (pra não quebrar imports)."""
    try:
        sys_path = str(Path(__file__).parent.parent.parent)
        if sys_path not in os.sys.path:
            os.sys.path.insert(0, sys_path)
        from Brain.llm_client import get_default_client
        return get_default_client()
    except ImportError:
        return None


def analyze_conversation(
    messages: list[str],
    vertical: str = "auto",
    context: Optional[str] = None,
) -> dict:
    """Analisa uma conversa (lista de mensagens) e retorna oportunidades detectadas.

    Args:
        messages: lista de mensagens (ordenadas, mais antiga primeiro)
        vertical: filtro de vertical ou "auto" pra detectar todas
        context: contexto adicional (nome do chat, descrição, etc)

    Returns:
        dict {"ok": bool, "analysis": {...}, "raw": str, "tokens_used": int}
    """
    if not messages:
        return {"ok": False, "error": "messages vazio"}

    # Junta as mensagens em uma transcrição (quem fala é implícito pela ordem)
    conversation = "\n".join(f"- {m}" for m in messages)

    # Monta prompt final
    vertical_hint = (
        f"\nFoco vertical: {vertical}"
        if vertical != "auto"
        else "\nFoco vertical: detectar em todas as verticais aplicáveis"
    )
    context_hint = f"\nContexto do chat: {context}" if context else ""

    user_prompt = (
        f"Analise a conversa abaixo e retorne JSON conforme as regras.{vertical_hint}{context_hint}\n\n"
        f"Conversa:\n{conversation}"
    )

    # Tenta LLM via interface sync do JARVIS; cai pra heurística se não tiver provedor
    try:
        from Brain.llm_client import complete as llm_complete
        has_provider = any([
            os.environ.get("OPENROUTER_API_KEY"),
            os.environ.get("ANTHROPIC_API_KEY"),
            os.environ.get("HERMES_PROXY_URL"),
        ])
        if not has_provider:
            return _heuristic_fallback(text, vertical)
        combined = (
            f"{user_prompt}\n\nResponda APENAS com JSON válido conforme o formato especificado."
        )
        raw = llm_complete(combined, system=ANALYZER_PROMPT, max_tokens=800)
        raw = raw.strip()
        raw_clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        analysis = json.loads(raw_clean)
        return {
            "ok": True,
            "analysis": analysis,
            "raw": raw,
            "tokens_used": len(raw_clean.split()) * 1.3,
        }
    except json.JSONDecodeError:
        LOG.warning("LLM retornou JSON inválido, usando heurística")
        return _heuristic_fallback(text, vertical)
    except Exception as exc:
        LOG.warning("LLM falhou (%s), usando heurística", exc)
        return _heuristic_fallback(text, vertical)


def _heuristic_fallback(text: str, vertical: str = "auto") -> dict:
    """Fallback sem LLM: classifica com keywords + heurística."""
    text_lower = text.lower()
    # Detecções
    tem_preco = bool(re.search(r"r\$\s*\d|quanto custa|preço|valor|orçamento|orcamento", text_lower))
    tem_problema = any(w in text_lower for w in [
        "não funciona", "nao funciona", "bug", "erro", "reclamação", "reclamacao",
        "cancelar", "reembolso", "péssimo", "pessimo",
    ])
    tem_fotografia = any(w in text_lower for w in [
        "fotografia", "foto", "casamento", "ensaio", "fotógrafo", "fotografo",
        "book", "evento",
    ])
    tem_video = any(w in text_lower for w in [
        "vídeo", "video", "filmagem", "filmagem", "drone", "institucional",
    ])
    tem_ia = any(w in text_lower for w in [
        "inteligência artificial", "ia ", "bot", "automação", "automacao",
        "agente", "llm",
    ])
    # Categoria
    if tem_problema:
        category = "problema_cliente"
        score = 0.75
        lead_quente = True
    elif tem_preco and (tem_fotografia or tem_video or tem_ia):
        category = "lead_comercial"
        score = 0.85
        lead_quente = True
    elif tem_fotografia or tem_video:
        category = "lead_comercial"
        score = 0.65
        lead_quente = False
    elif tem_ia:
        category = "discussao_tecnica"
        score = 0.55
        lead_quente = False
    elif tem_preco:
        category = "lead_comercial"
        score = 0.7
        lead_quente = True
    else:
        category = "conversa_casual"
        score = 0.3
        lead_quente = False

    return {
        "ok": True,
        "analysis": {
            "category": category,
            "score": score,
            "lead_quente": lead_quente,
            "summary": text[:100].strip(),
            "next_action": "responder" if lead_quente else "follow_up_7d",
            "orcamento_estimado": "mencionado" if tem_preco else None,
            "prazo_mencionado": None,
            "confianca": 0.6,
            "method": "heuristic_fallback",
            "vertical_sugerida": (
                "fotografia" if tem_fotografia
                else "filmagem" if tem_video
                else "tecnologia" if tem_ia
                else "auto"
            ),
        },
        "tokens_used": 0,
        "skipped_llm": True,
    }


# ---- Convenience: estatísticas rápidas (sem LLM) ----

TRIGGER_WORDS = {
    "fotografia": [
        "foto", "fotografo", "fotógrafo", "ensaio", "retrato",
        "casamento", "casal", "gestante", "aniversário", "aniversario",
        "cobertura fotografica", "book",
    ],
    "filmagem": [
        "video", "vídeo", "filmagem", "filmagem de", "editor de video",
        "casamento", "evento", "cobertura", "institucional", "making of",
        "reels", "stories", "youtube",
    ],
    "tecnologia": [
        "site", "website", "app", "aplicativo", "sistema", "automacao",
        "automação", "bot", "integração", "api", "landing page",
    ],
    "comunicacao_ministerial": [
        "culto", "pregação", "pregacao", "ministério", "ministerio",
        "igreja", "pastor", "pastora", "louvor", "devocional",
        "ebd", "escola biblica", "escola bíblica",
    ],
}


def quick_keyword_scan(text: str) -> dict:
    """Scan local (sem LLM) — detecta verticais por palavras-chave.

    Útil pra triagem rápida ANTES de chamar LLM (economiza tokens).
    """
    text_lower = text.lower()
    matches = {}
    for vertical, keywords in TRIGGER_WORDS.items():
        hits = [kw for kw in keywords if kw in text_lower]
        if hits:
            matches[vertical] = hits
    return {
        "vertical_match": list(matches.keys()),
        "palavras_chave": [kw for v in matches.values() for kw in v],
        "method": "keyword_scan",
    }
