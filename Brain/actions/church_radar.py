"""Church Radar — detecta oportunidades ministeriais a partir de mídias sociais.

Monitora contas de igrejas no Instagram/Facebook e detecta:
  - Posts com alto engajamento (modelo de sucesso)
  - Temas recorrentes (sermões, eventos, campanhas)
  - Oportunidades pastorais (visitantes engajados, pedidos de oração)
  - Crises ministeriais (reclamações, problemas)
  - Tendências de comunicação cristã

Output: dict com category, urgency, summary, suggested_action, opportunities[].

Baseado no sketch whatsapp-jarvis-sketch.md (20/07) — vertical ministerial
(R$ 115.000/mês potencial — conservador, vide sketch §Comunicação Ministerial).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

LOG = logging.getLogger("jarvis.actions.church_radar")

# Keywords ministeriais
MINISTERIAL_TRIGGERS = {
    "sermao": [
        "pregação", "pregacao", "sermão", "sermao", "ministração", "ministracao",
        "palavra", "culto", "pregou", "pregando", "pregador", "pastor",
        "estudo bíblico", "estudo biblico", "devocional", "devocional",
    ],
    "evento": [
        "evento", "congresso", "conferência", "conferencia", "encontro",
        "retiro", "acampamento", "celebração", "celebracao", "festa",
        "culto da família", "culto da familia", "culto jovem", "culto kids",
    ],
    "oracao": [
        "oração", "oracao", "intercessão", "intercessao", "pedido de oração",
        "pedido de oracao", "orar", "reze", "reze por", "clama",
        "ministração de cura", "ministracao de cura", "libertação", "libertacao",
    ],
    "evangelismo": [
        "evangelismo", "evangelizar", "missões", "missoes", "missionário",
        "missionario", "plantar igreja", "igreja nova", "ganhar almas",
    ],
    "comunidade": [
        "comunidade", "grupo pequeno", "célula", "celula", "discipulado",
        "discipulador", "integração", "integracao", "visitante", "novo convert",
        "novo convertido", "batismo",
    ],
    "familia": [
        "casamento", "família", "familia", "filhos", "criança", "crianca",
        "adolescente", "jovem", "namoro", "noivado",
    ],
    "louvor": [
        "louvor", "adoração", "adoracao", "música", "musica", "ministração",
        "ministracao", "cantor", "ministério de louvor", "ministerio de louvor",
        "worship", "cantores", "banda",
    ],
}

# Indicadores de oportunidade pastoral (visitantes, pedidos)
OPPORTUNITY_SIGNALS = {
    "visitante_engajado": [
        "primeira vez", "nos visitou", "nos visitaram", "estaremos de volta",
        "adorei o culto", "amei o culto", "fui pela primeira vez",
        "indicação", "indicacao", "amiga indicou", "amigo indicou",
    ],
    "pedido_oracao": [
        "pode orar", "preciso de oração", "preciso de oracao",
        "estou passando por", "estou enfrentando", "oração por",
        "oracao por", "intercedam",
    ],
    "crise_ministerial": [
        "reclamação", "reclamacao", "decepcionado", "não gostei", "nao gostei",
        "saí da igreja", "sai da igreja", "não concordo", "nao concordo",
        "problema com", "escândalo", "escandalo", "denúncia", "denuncia",
    ],
    "doacao": [
        "doação", "doacao", "oferta", "dízimo", "dizimo", "contribua",
        "vakinha", "arrecadação", "arrecadacao", "pix",
    ],
}


def classify_post(text: str) -> dict:
    """Classifica post de rede social de igreja.

    Returns:
        {
          "themes": ["sermao", "oracao"],
          "opportunities": ["visitante_engajado"],
          "urgency": "alta" | "media" | "baixa",
          "suggested_action": "responder_visita" | "orar_agora" | "arquivar",
          "score": 0.0-1.0
        }
    """
    if not text or not text.strip():
        return {"themes": [], "opportunities": [], "urgency": "baixa", "score": 0.0}

    text_lower = text.lower()
    # IMPORTANTE: usar \b pra evitar matches ruins
    themes = []
    for theme, keywords in MINISTERIAL_TRIGGERS.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                themes.append(theme)
                break

    opportunities = []
    urgency = "baixa"
    for opp, keywords in OPPORTUNITY_SIGNALS.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                opportunities.append(opp)
                if opp == "crise_ministerial":
                    urgency = "alta"
                elif opp in ("visitante_engajado", "pedido_oracao") and urgency != "alta":
                    urgency = "media"
                break

    # Score baseado em densidade de sinais ministeriais
    word_count = max(len(text.split()), 1)
    density = (len(themes) + len(opportunities) * 1.5) / word_count
    score = min(1.0, 0.3 + density * 5)

    # Sugestão de ação
    suggested_action = "arquivar"
    if "crise_ministerial" in opportunities:
        suggested_action = "responder_pastor"
    elif "visitante_engajado" in opportunities:
        suggested_action = "responder_visita"
    elif "pedido_oracao" in opportunities:
        suggested_action = "orar_agora"
    elif themes:
        suggested_action = "engajar_post"

    return {
        "themes": themes,
        "opportunities": opportunities,
        "urgency": urgency,
        "suggested_action": suggested_action,
        "score": round(score, 2),
    }


def generate_devotional_text(theme: str, book: str = "", chapter: int = 0,
                              verse: int = 0) -> dict:
    """Gera devocional curto sobre tema + versículo (template pronto, sem LLM).

    Args:
        theme: tema (ex: "ansiedade", "família", "fé")
        book: livro bíblico (ex: "Filipenses")
        chapter: capítulo
        verse: versículo

    Returns:
        {
          "title": "...",
          "verse": "...",
          "reflection": "...",
          "prayer": "...",
          "share_text": "..."
        }
    """
    # Versículos por tema (mapeamento básico — pode crescer)
    VERSES = {
        "ansiedade": ("Filipenses", 4, 6, "Não andeis ansiosos por coisa alguma; antes, as vossas petições sejam em tudo conhecidas diante de Deus, pela oração com ação de graças."),
        "família": ("Josué", 24, 15, "Eu e a minha casa serviremos ao Senhor."),
        "fé": ("Hebreus", 11, 1, "Ora, a fé é a certeza daquilo que esperamos e a prova das coisas que não vemos."),
        "amor": ("1 Coríntios", 13, 4, "O amor é paciente, o amor é bondoso. Não inveja, não se vangloria, não se orgulha."),
        "esperança": ("Romanos", 15, 13, "O Deus da esperança vos encha de todo o gozo e paz em crença, para que abundeis em esperança pelo poder do Espírito Santo."),
        "perdão": ("Efésios", 4, 32, "Antes, sede uns para com os outros benignos, misericordiosos, perdoando-vos uns aos outros."),
        "coragem": ("Josué", 1, 9, "Sê forte e corajoso; não pasmes, nem te espantes, porque o Senhor, teu Deus, é contigo, por onde quer que andares."),
        "gratidão": ("1 Tessalonicenses", 5, 18, "Em tudo dai graças, porque esta é a vontade de Deus em Cristo Jesus para convosco."),
        "sabedoria": ("Tiago", 1, 5, "Se algum de vós tem falta de sabedoria, peça-a a Deus, que a todos dá liberalmente."),
        "paciência": ("Tiago", 1, 2, "Meus irmãos, tende por motivo de grande gozo o passardes por diversas provações."),
    }
    theme_norm = theme.lower().strip()
    if not book and theme_norm in VERSES:
        book, chapter, verse, verse_text = VERSES[theme_norm]
    elif book:
        # Versículo customizado: Paulo fornece, sem texto
        verse_text = f"({book} {chapter}:{verse})"
    else:
        # Tema não mapeado, genérico
        book, chapter, verse, verse_text = "Salmos", 23, 1, "O Senhor é o meu pastor; nada me faltará."

    title = f"Devocional: {theme.capitalize()}"
    if book:
        title += f" — {book} {chapter}:{verse}"

    # Reflexão template (3 frases genéricas, podem crescer com LLM)
    reflection = (
        f"Hoje o convite é refletir sobre {theme}. "
        f"A palavra em {book} {chapter}:{verse} nos lembra que Deus está presente em cada detalhe. "
        f"Reserve um momento do dia pra meditar neste versículo e permitir que o Espírito Santo fale ao seu coração."
    )
    prayer = (
        f"Senhor, obrigado(a) por falar comigo através de {book} {chapter}:{verse}. "
        f"Ajuda-me a viver {theme} no meu dia a dia. Em nome de Jesus, amém."
    )
    share_text = (
        f"📖 {title}\n\n"
        f"\"{verse_text}\"\n\n"
        f"{reflection}\n\n"
        f"🙏 {prayer}"
    )

    return {
        "title": title,
        "verse": verse_text,
        "verse_ref": f"{book} {chapter}:{verse}",
        "reflection": reflection,
        "prayer": prayer,
        "share_text": share_text,
    }


def generate_church_post_suggestion(theme: str, format: str = "instagram") -> dict:
    """Gera sugestão de post para rede social de igreja.

    Args:
        theme: tema do post (ex: "domingo", "jejum", "festa junina")
        format: "instagram", "facebook", "stories", "reels"

    Returns:
        dict com copy + hashtags + CTA
    """
    format_lower = format.lower()
    # Templates por formato
    if format_lower == "reels":
        copy = (
            f"🎬 [ROTEIRO DE REELS — 30s]\n\n"
            f"Cena 1 (3s): Pergunta provocativa sobre {theme}\n"
            f"Cena 2 (10s): Versículo-chave (legenda na tela)\n"
            f"Cena 3 (10s): Reflexão rápida (voz em off + texto)\n"
            f"Cena 4 (7s): CTA — 'Salva esse vídeo e compartilha com alguém'\n\n"
            f"🎵 Trilha: worship instrumental ou lo-fi gospel"
        )
    elif format_lower == "stories":
        copy = (
            f"📱 [STORIES — sequência de 3 telas]\n\n"
            f"Tela 1: Pergunta sobre {theme} (com enquete 'sim/não')\n"
            f"Tela 2: Citação bíblica + reflexão curta\n"
            f"Tela 3: CTA 'Marca aqui quem precisa ouvir isso' + link do culto"
        )
    else:  # instagram/facebook padrão
        copy = (
            f"📝 [POST CARROSSEL — {theme}]\n\n"
            f"Slide 1 (capa): Pergunta impactante sobre {theme}\n"
            f"Slide 2-4: 3 versículos com reflexão curta\n"
            f"Slide 5: Aplicação prática pro dia\n"
            f"Slide 6: CTA 'Salva e marca alguém' + 'Comenta AMÉM 🙏'\n\n"
            f"🎨 Identidade visual: cores da igreja, tipografia consistente"
        )

    # Hashtags ministeriais
    base_tags = [
        "#fé", "#deus", "#jesus", "#igreja", "#palavradedeus",
        "#gospel", "#cristão", "#cristao", "#bíblia", "#biblia",
    ]
    theme_tags_map = {
        "domingo": ["#domingodedeus", "#culto", "#louvor"],
        "jejum": ["#jejum", "#oração", "#oracao", "#conversão", "#conversao"],
        "jovem": ["#geração", "#geracao", "#jovens", "#deusnosencontro"],
        "família": ["#família", "#familia", "#casalcristao"],
        "evangelismo": ["#evangelismo", "#missões", "#missoes", "#igrejaplantada"],
    }
    extra = theme_tags_map.get(theme.lower(), [])
    hashtags = " ".join(base_tags + extra)

    cta_map = {
        "instagram": "💬 Comenta 'AMÉM' se essa palavra tocou você!\n📩 Salva pra reler durante a semana\n📢 Marca 3 pessoas que precisam ouvir isso",
        "facebook": "🙏 Se essa palavra abençoou você, escreva 'ALELUIA' nos comentários!\n📤 Compartilhe com alguém que precisa dessa mensagem hoje",
        "stories": "🎯 Enquete + reação: 'Qual versículo tocou mais?'",
        "reels": "💾 Salva esse vídeo!\n🔁 Compartilha com quem precisa ouvir",
    }
    cta = cta_map.get(format_lower, cta_map["instagram"])

    return {
        "theme": theme,
        "format": format_lower,
        "copy": copy,
        "hashtags": hashtags,
        "cta": cta,
    }


def quick_scan(text: str) -> dict:
    """Wrapper rápido pra scan de post único."""
    classification = classify_post(text)
    return {
        "input_chars": len(text),
        **classification,
    }
