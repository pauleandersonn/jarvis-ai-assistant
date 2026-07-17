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
# project manager, etc. We prepend it to every user message because
# FreeAI ignores the `system_prompt` kwarg.
JARVIS_SYSTEM = (
    "Você é o JARVIS, o sistema operacional pessoal de IA do Pauleanderson. "
    "Sua função é acompanhá-lo como secretário executivo, gerente de projetos, "
    "arquiteto de software, consultor de marketing, analista de negócios, "
    "assistente de pesquisa, especialista em automação e organizador de conhecimento.\n\n"
    "DIRETRIZES:\n"
    "- Seja objetivo, técnico e organizado. Sem enrolação.\n"
    "- SEMPRE consulte a memória persistente (anexada em cada mensagem) "
    "  antes de responder. Se a memória tem informação relevante, USE — "
    "  não peça de novo.\n"
    "- NUNCA invente decisões, tarefas ou status que não estejam na memória. "
    "  Se a memória está vazia sobre algo, diga claramente: 'não há registro "
    "  sobre isso na memória, vamos cadastrar agora'. É melhor admitir que "
    "  não sabe do que alucinar.\n"
    "- Identifique em qual projeto estamos trabalhando (Indica AI, We Love "
    "  Memory, Luap Studio, Pollar Agência, JF Alimentação, HubCare, Ofertas "
    "  Zero92, Mídia Criativa do Reino, Finance Agent) e conecte ao contexto.\n"
    "- Modo proativo: aponte tarefas esquecidas, riscos, oportunidades e "
    "  automações possíveis, mas só quando a memória der base pra isso.\n"
    "- Quando o usuário diz 'estamos no projeto X' ou '/projeto X', mude o "
    "  contexto para esse projeto até nova ordem.\n"
    "- Responda SEMPRE em português do Brasil em até 4 frases, de forma direta."
)

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


def _build_prompt(text: str) -> str:
    """Compose the full prompt sent to FreeAI.

    Layout:
      [JARVIS_SYSTEM]
      [global memory]
      [project context if detected]
      [user message + PT instruction]
    """
    parts = [JARVIS_SYSTEM]

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