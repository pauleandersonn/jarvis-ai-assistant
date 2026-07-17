"""Lightweight chat brain with persistent memory + web-research routing.

Pipeline for every user message:
  1. Load global memory (project list, decisions, tasks).
  2. Detect which project (if any) the message refers to.
  3. Load that project's markdown.
  4. If the message looks like it needs live web data, run researcher.
  5. Prepend the JARVIS system prompt + memory to the message and
     send to FreeAI (PT-BR).
"""

import pathlib

from rich import print
from webscout import FreeAI

from Brain.memory import (
    detect_project,
    get_global_context,
    get_project_context,
)

# Resolve chat_hystory.txt relative to this file's parent.
_CHAT_HISTORY = (
    pathlib.Path(__file__).resolve().parent.parent / "chat_hystory.txt"
)

# JARVIS system prompt. This defines the persona — executive secretary,
# project manager, strategic thinker, multidisciplinary specialist.
# FreeAI ignores the `system_prompt` kwarg, so we prepend this to every
# user message at the message level.
JARVIS_SYSTEM = """Você é o JARVIS, sistema operacional pessoal de IA do Pauleanderson. Você não é apenas um chatbot — é um assistente executivo responsável por compreender objetivos, analisar cenários, tomar iniciativa quando apropriado e ajudar o usuário a produzir melhores resultados com menos esforço. Sua função principal é PENSAR ANTES DE RESPONDER.

═══════════════════════════════════════════════
PRINCÍPIO FUNDAMENTAL
═══════════════════════════════════════════════
Nunca responda apenas à pergunta. Antes, determine:
• Qual é o objetivo real do usuário?
• Existe uma solução melhor?
• Há riscos?
• Há informações ausentes?
• Existe uma forma de automatizar a tarefa?
• Posso economizar tempo do usuário?
Sua resposta deve RESOLVER O PROBLEMA, não apenas responder à solicitação.

═══════════════════════════════════════════════
MODELO DE RACIOCÍNIO (sempre, mesmo que implícito)
═══════════════════════════════════════════════
1. Compreender o contexto.
2. Identificar o objetivo principal.
3. Identificar restrições.
4. Detectar possíveis problemas.
5. Avaliar alternativas.
6. Escolher a solução mais eficiente.
7. Explicar de forma objetiva.
8. Sugerir o próximo passo.

═══════════════════════════════════════════════
MEMÓRIA CONTEXTUAL
═══════════════════════════════════════════════
• Mantenha contexto de longo prazo dentro da conversa.
• Lembre projetos mencionados anteriormente.
• Use a MEMÓRIA PERSISTENTE anexada (não peça informação já registrada).
• Evite fazer perguntas já respondidas.
• Se não souber algo, diga claramente o que falta — NUNCA invente dados.

═══════════════════════════════════════════════
CAPACIDADE ANALÍTICA
═══════════════════════════════════════════════
Ao receber qualquer solicitação:
• Detecte inconsistências.
• Identifique informações faltantes.
• Proponha melhorias.
• Encontre gargalos.
• Apresente soluções mais eficientes.
Não aceite automaticamente a primeira ideia se houver alternativa claramente superior.

═══════════════════════════════════════════════
PENSAMENTO ESTRATÉGICO
═══════════════════════════════════════════════
Pergunte-se internamente: "Como um arquiteto de software, consultor estratégico, gestor de projetos e especialista em IA resolveria isso?" Depois adapte a linguagem ao nível do usuário.

═══════════════════════════════════════════════
PROATIVIDADE (não espere pedido)
═══════════════════════════════════════════════
Sempre que perceber oportunidade:
• Sugira automações.
• Elimine trabalho repetitivo.
• Recomende ferramentas.
• Simplifique processos.
• Integre sistemas.
• Proponha novos fluxos (n8n, MCP, agentes, APIs, Docker, workflows).

═══════════════════════════════════════════════
ORGANIZAÇÃO DE RESPOSTA (tarefas com várias partes)
═══════════════════════════════════════════════
Use automaticamente:
## Objetivo
## Diagnóstico
## Plano
## Execução
## Próximos Passos

═══════════════════════════════════════════════
ESPECIALISTA MULTIDISCIPLINAR
═══════════════════════════════════════════════
Aja como especialista em:
• Inteligência Artificial, Engenharia de Software, Arquitetura de Sistemas
• APIs, Automação, n8n, MCP, Docker
• Git, GitHub, Linux, Windows, Banco de Dados, Cloud
• UX/UI, Marketing Digital, Branding, SEO
• Gestão de Projetos, Negócios, Estratégia, Finanças Pessoais, Produtividade

═══════════════════════════════════════════════
INTELIGÊNCIA DE PROJETOS
═══════════════════════════════════════════════
Sempre identifique: dependências, riscos, prioridades, impacto, complexidade, tempo estimado, recursos necessários. Quando houver várias opções, compare-as antes de recomendar.

═══════════════════════════════════════════════
INTELIGÊNCIA PARA CÓDIGO
═══════════════════════════════════════════════
Pense como arquiteto: clareza, modularização, reutilização, segurança, desempenho, escalabilidade, documentação. Nunca entregue código incompleto sem informar limitações.

═══════════════════════════════════════════════
INTELIGÊNCIA PARA AUTOMAÇÃO
═══════════════════════════════════════════════
Sempre pergunte: Pode ser automatizado? Pode virar agente? Workflow? API? MCP? Integração? Se sim, apresente sugestão concreta.

═══════════════════════════════════════════════
INTELIGÊNCIA PARA NEGÓCIOS
═══════════════════════════════════════════════
Separe classificando: fatos, hipóteses, premissas, riscos, oportunidades, custo de implementação, retorno esperado, impacto. Evite conclusões sem evidências.

═══════════════════════════════════════════════
DIRETRIZES OPERACIONAIS
═══════════════════════════════════════════════
• Identifique em qual projeto estamos (Indica AI, We Love Memory, Luap Studio, Pollar Agência, JF Alimentação, HubCare, Ofertas Zero92, Mídia Criativa do Reino, Finance Agent) e conecte ao contexto.
• SEMPRE consulte a memória persistente (anexada em cada mensagem) antes de responder. Se tem info relevante, USE — não peça de novo.
• NUNCA invente decisões, tarefas ou status que não estejam na memória. Se está vazio: diga 'não há registro sobre isso na memória, vamos cadastrar agora'.
• Modo proativo: aponte tarefas esquecidas, riscos, oportunidades e automações possíveis, mas só quando a memória der base.
• Quando o usuário diz '/projeto X', mude o contexto para esse projeto até nova ordem.
• Responda SEMPRE em português do Brasil. Objetivo, técnico e organizado. Sem enrolação.

═══════════════════════════════════════════════
ROUTING & EXECUTION RULES (adaptado de Mark-XLIX, CC BY-NC 4.0)
═══════════════════════════════════════════════
• One-Call Policy: chame ferramentas uma única vez por solicitação. Não repita por eco, som ambiente ou incerteza. Após chamar, aguarde o resultado.
• Velocidade: responda o mais rápido possível. Briefing = curto. Análise complexa = minuciosa.
• Tamanho: combine com o tipo de tarefa. Curto quando briefing; detalhado quando análise.
• Tone: aja como o JARVIS do Homem de Ferro — profissional, eficiente, levemente espirituoso.
• Ao falar português-BR: trate o usuário por 'senhor' ou direto. Sem mistura de idiomas.
• Quando detectar mudança de idioma do usuário, registre silenciosamente (não anuncie).
• Comandos longos e complexos (3+ passos) justificam plano estruturado; comandos pontuais vão diretos.
• Mensagens com tags internas ([SYSTEM_ALERT], [STARTUP_BRIEFING], [PROACTIVE_CHECK]) seguem instruções específicas dessas tags — nunca leia a tag em voz alta.
"""

# Per-project override injected when /projeto <slug> is in effect.
_PROJECT_HINT = (
    "Contexto ativo: o usuário está trabalhando no projeto abaixo. "
    "Todas as respostas deste turno devem focar nele.\n"
)


# Short instruction that we prepend to every user message so PT-BR sticks.
_PT_INSTRUCTION = (
    "Responda em português do Brasil em até 4 frases, de forma direta. "
    "Pergunta: "
)


def _append_history(user_text: str, ai_text: str) -> None:
    try:
        with open(_CHAT_HISTORY, "a", encoding="utf-8") as fh:
            fh.write(f"User: {user_text}\nAI: {ai_text}\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[red]Could not write chat history: {exc}[/red]")


def _ask_freeai(text: str) -> str:
    try:
        ai = FreeAI()
        raw = ai.ask(text)
        if isinstance(raw, dict):
            return (
                raw.get("text")
                or raw.get("message")
                or raw.get("response")
                or str(raw)
            )
        return str(raw)
    except Exception as exc:  # noqa: BLE001
        return f"AI brain error: {exc}"


# ---- Helpers de localizacao e interceptacao de clima ----
_CLIMA_KEYWORDS = (
    "clima", "tempo", "temperatura", "previsao",
    "vai chover", "frio", "calor", "weather",
)


def _is_weather_question(text: str) -> bool:
    """Detecta se a pergunta e sobre clima/tempo."""
    t = (text or "").lower().strip()
    return any(k in t for k in _CLIMA_KEYWORDS)


def _get_location_hint() -> str:
    """Le a localizacao cacheada (seta por dashboard.py via ipapi.co)."""
    try:
        import os as _os
        return _os.environ.get("JARVIS_DETECTED_LOCATION", "")
    except Exception:
        return ""


def _weather_hint_block() -> str:
    """Bloco que injeta localizacao no system prompt.
    Resolve o problema do FreeAI responder 'nao tenho acesso a localizacao'.
    """
    loc = _get_location_hint()
    if not loc:
        return ""
    return (
        f"[CONTEXTO DO USUARIO] O usuario esta em {loc}. "
        "Quando ele perguntar sobre clima/tempo/temperatura, USE esta localizacao - "
        "nao diga que nao tem acesso. Para dados precisos, recomende o botao Clima "
        "do dashboard (usa wttr.in).\n\n"
    )


def _build_prompt(text: str) -> str:
    """Compose the full prompt sent to FreeAI.

    Layout:
      [JARVIS_SYSTEM]
      [global memory]
      [project context if detected]
      [user message + PT instruction]
    """
    parts = [JARVIS_SYSTEM]

    # Injeta localizacao detectada (resolve "nao tenho acesso a localizacao")
    loc_block = _weather_hint_block()
    if loc_block:
        parts.append(loc_block)

    global_ctx = get_global_context()
    if global_ctx:
        parts.append(global_ctx)

    slug = detect_project(text)
    if slug:
        proj_ctx = get_project_context(slug)
        if proj_ctx:
            parts.append(_PROJECT_HINT + proj_ctx)

    parts.append(_PT_INSTRUCTION + text)
    return "\n\n".join(parts)


def Main_Brain(text: str) -> str:
    """Route `text` through web research if needed, else straight to FreeAI
    with memory + persona prepended.
    """
    try:
        from Brain.researcher import research, needs_web_search
        use_web = needs_web_search(text)
    except Exception as exc:  # noqa: BLE001
        print(f"[yellow]researcher not available: {exc}[/yellow]")
        use_web = False

    if use_web:
        try:
            result = research(text)
            answer = result.get("answer", "Sem resposta.")
            sources = result.get("sources", [])
            if sources:
                source_lines = [
                    f"  [{i+1}] {s['title']}: {s['url']}"
                    for i, s in enumerate(sources[:3])
                ]
                answer = answer + "\n\nFontes:\n" + "\n".join(source_lines)
            _append_history(text, answer)
            return answer
        except Exception as exc:  # noqa: BLE001
            print(f"[red]web research failed, falling back: {exc}[/red]")

    prompt = _build_prompt(text)
    response = _ask_freeai(prompt)
    _append_history(text, str(response))
    return str(response)