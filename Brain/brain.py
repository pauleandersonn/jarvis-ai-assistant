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
from webscout import FreeAI  # noqa: F401  -- kept for legacy fallback in llm_client

from Brain.llm_client import complete as llm_complete, LLMUnavailable
from Brain.integrations_router import route_integration_question

from Brain.memory import (
    detect_project,
    get_global_context,
    get_project_context,
    list_projects,
)
from Brain.hermes_bridge import (
    get_hermes_context,
    append_journal,
    invalidate_cache as _hermes_invalidate,
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
INTEGRAÇÕES ATIVAS (use a memória `integrations.md` para detalhes)
═══════════════════════════════════════════════
• Gmail conectado em `pauleandersongomes@gmail.com` — você PODE ler inbox, ler emails individuais, ENVIAR emails (sempre confirme antes de enviar).
• Google Calendar conectado — você PODE listar eventos, criar eventos (sempre confirme antes), deletar.
• Sempre que o usuário pedir algo sobre email ou agenda, USE as ferramentas (não diga que "não tem acesso"). Os endpoints estão no `integrations.md` que é carregado em cada conversa.
• Quando agir via voz, prefira os endpoints `*_summary` que retornam string TTS-friendly. Para o dashboard por texto, prefira os endpoints completos (`/api/email/search`, `/api/calendar/list`).

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
    """Compat wrapper (legacy name). Real logic now in Brain/llm_client.py.

    Provider precedence: OpenRouter > Anthropic > Hermes-proxy > FreeAI.
    Set the appropriate env var to activate; FreeAI is always the fallback.
    """
    try:
        return llm_complete(text, max_tokens=1500)
    except LLMUnavailable as exc:
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
      [HERMES context — shared memory from ~/.hermes/memories/, cached 5min]
      [global memory]
      [project context if detected]
      [user message + PT instruction]
    """
    parts = [JARVIS_SYSTEM]

    # Injeta localizacao detectada (resolve "nao tenho acesso a localizacao")
    loc_block = _weather_hint_block()
    if loc_block:
        parts.append(loc_block)

    # Modo 1: injetar contexto do Hermes (memoria compartilhada). Cache 5min
    # controlado internamente por hermes_bridge.get_hermes_context(). Passa
    # a lista de projetos pra que o bridge re-sincronize o indice ~/.hermes.
    try:
        hermes_ctx = get_hermes_context(jarvis_projects=list_projects())
        if hermes_ctx:
            parts.append(hermes_ctx)
    except Exception as exc:  # noqa: BLE001
        print(f"[yellow]hermes_bridge failed: {exc}[/yellow]")

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
    # Detecta o projeto uma vez pra (a) carregar contexto, (b) taggear o journal.
    slug = detect_project(text)

    try:
        from Brain.researcher import research, needs_web_search
        use_web = needs_web_search(text)
    except Exception as exc:  # noqa: BLE001
        print(f"[yellow]researcher not available: {exc}[/yellow]")
        use_web = False

    answer: str
    # Modo 0: integracoes (email/calendar/status) -- bypass LLM.
    # Quando a pergunta e sobre algo que temos endpoint interno, chama direto
    # e retorna a string TTS-friendly. Evita o LLM alucinar ("nao tenho
    # acesso") quando a verdade e outra.
    try:
        direct_answer = route_integration_question(text)
        if direct_answer is not None:
            _append_history(text, direct_answer)
            try:
                append_journal(text, direct_answer, project_slug=slug)
            except Exception:
                pass
            return direct_answer
    except Exception as exc:  # noqa: BLE001
        print(f"[yellow]integrations router falhou, fallback LLM: {exc}[/yellow]")

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
            # Modo 4: escreve no journal do Hermes (best-effort, nao bloqueia).
            try:
                append_journal(text, answer, project_slug=slug)
            except Exception:
                pass
            return answer
        except Exception as exc:  # noqa: BLE001
            print(f"[red]web research failed, falling back: {exc}[/red]")

    prompt = _build_prompt(text)
    response = _ask_freeai(prompt)
    _append_history(text, str(response))
    # Modo 4: loga tudo no journal compartilhado.
    try:
        append_journal(text, str(response), project_slug=slug)
    except Exception:
        pass
    return str(response)