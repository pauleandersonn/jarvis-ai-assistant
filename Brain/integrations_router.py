"""Router for integration questions — bypass LLM for known intents.

If the user asks about email/calendar/etc, call the dashboard endpoint
directly instead of going through the (often confused) LLM. Returns a
TTS-friendly string ready to be spoken.

Patterns matched (case-insensitive, fuzzy):
  - email/inbox -> /api/email/inbox-summary
  - calendar/agenda -> /api/calendar/agenda-summary
  - "enviar email"/"mandar email" -> info only (writes still need brain)
  - create event/agendar compromisso -> info only

The HTTP call is local to the same dashboard process. If the dashboard
is on a different host (tunnel), pass host/port via env:
  JARVIS_DASHBOARD_HOST (default 127.0.0.1)
  JARVIS_DASHBOARD_PORT (default 8788)
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

LOG = logging.getLogger("jarvis.router")


def _dashboard_url(path: str) -> str:
    host = os.environ.get("JARVIS_DASHBOARD_HOST", "127.0.0.1")
    port = os.environ.get("JARVIS_DASHBOARD_PORT", "8788")
    return f"http://{host}:{port}{path}"


def _post(path: str, payload: dict, timeout: float = 15.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _dashboard_url(path), method="POST",
        headers={"Content-Type": "application/json"},
    )
    req.data = data
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def route_integration_question(text: str) -> str | None:
    """Return a TTS-friendly answer if `text` matches an integration intent,
    otherwise None (caller should fall through to LLM)."""
    if not text:
        return None
    t = text.lower().strip()

    # ---- WRITE requests (info only -- user must speak to activate) ----
    # Detected FIRST so it beats read-intent keywords like "agenda".
    # Quando o user pede pra criar evento/lembrete/enviar email, retornamos
    # uma string dizendo que precisa confirmar por voz no dashboard. A ação
    # real vem via MCP (jarvis_create_event etc).
    create_event_kw = ("criar evento", "cria evento", "criar compromisso",
                       "agendar evento", "agendar compromisso", "marcar evento",
                       "marcar compromisso", "novo evento", "novo compromisso",
                       "adicionar evento", "adicionar compromisso",
                       "quero criar um evento", "quero agendar", "preciso criar")
    if any(k in t for k in create_event_kw):
        return ("Posso criar, senhor. Fale pelo microfone do dashboard Jarvis: "
                "JARVIS, criar evento [resumo] de [data hora] ate [data hora]. "
                "Vou pedir confirmação por voz antes de criar.")

    create_reminder_kw = ("criar lembrete", "cria lembrete", "novo lembrete",
                          "me lembrar", "me lembra", "definir lembrete",
                          "configurar lembrete", "setar lembrete")
    if any(k in t for k in create_reminder_kw):
        return ("Posso criar lembrete, senhor. Fale pelo microfone: JARVIS, lembrete "
                "[mensagem] em [minutos] minutos. Vou pedir confirmação por voz.")

    send_email_kw = ("enviar email", "enviar e-mail", "manda email", "manda e-mail",
                     "mandar email", "mandar e-mail", "responder email", "responde email",
                     "enviar um email", "mandar um email", "manda um email")
    if any(k in t for k in send_email_kw):
        return ("Posso enviar, senhor. Fale pelo microfone: JARVIS, enviar email "
                "para [endereço] assunto [assunto] mensagem [corpo]. "
                "Vou pedir confirmação por voz antes de enviar.")

    # ---- READ: inbox ----
    inbox_keywords = ("inbox", "caixa de entrada", "meus emails", "meus e-mails",
                      "email não lido", "e-mail não lido", "email nao lido",
                      "emails não lidos", "e-mails não lidos",
                      "tenho email", "tenho e-mail", "chegou email", "chegou e-mail",
                      "lista email", "lista e-mail", "ler inbox", "ler email",
                      "ler e-mail")
    if any(k in t for k in inbox_keywords):
        # Detect how many
        max_results = 5
        if "todos" in t or "tudo" in t or "10" in t or "dez" in t:
            max_results = 10
        try:
            r = _post("/api/email/inbox-summary", {"query": "is:unread", "max_results": max_results})
        except Exception as e:
            LOG.warning("inbox route falhou: %s", e)
            return None
        if r.get("ok") and r.get("summary"):
            return r["summary"]
        return "Sua inbox está vazia, senhor. Nenhum email não lido no momento."

    # ---- READ: agenda ----
    agenda_keywords = ("agenda", "compromisso", "compromissos", "reunião", "reuniao",
                       "evento", "eventos", "o que tenho hoje", "o que tenho amanhã",
                       "o que tenho amanha", "tenho agenda", "próximo evento",
                       "proximo evento", "calendário", "calendario")
    if any(k in t for k in agenda_keywords):
        try:
            r = _post("/api/calendar/agenda-summary", {})
        except Exception as e:
            LOG.warning("agenda route falhou: %s", e)
            return None
        if r.get("ok") and r.get("summary"):
            return r["summary"]
        return "Sua agenda está livre, senhor. Sem compromissos próximos."

    # ---- READ: integrations status ----
    integ_keywords = ("integração", "integracao", "o que está conectado",
                      "o que esta conectado", "quais conexões", "quais conexoes",
                      "google conectado", "gmail conectado", "calendar conectado")
    if any(k in t for k in integ_keywords):
        try:
            req = urllib.request.Request(_dashboard_url("/api/integrations"), method="GET")
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            services = data.get("services", data.get("integrations", []))
            if not services:
                return ("Estou conectado ao seu Gmail e Google Calendar, senhor. "
                        "Posso ler emails, listar agenda, criar eventos e enviar mensagens. "
                        "Mais alguma coisa?")
            lines = ["Estou conectado a " + str(len(services)) + " serviços:"]
            for s in services[:5]:
                name = s.get("name", s.get("title", ""))
                if name:
                    lines.append(f"- {name}")
            lines.append("Posso ler emails, listar agenda, criar eventos e enviar mensagens.")
            return " ".join(lines)
        except Exception as e:
            LOG.warning("integrations route falhou: %s", e)

    # ---- WRITE requests (info only) ----
    # (moved to TOP of function so it beats read-intent keywords)

    return None


# Self-test
if __name__ == "__main__":
    tests = [
        "JARVIS, o que tenho na minha inbox?",
        "tem email não lido?",
        "leia meu inbox",
        "JARVIS, o que tenho de agenda hoje?",
        "tenho compromisso amanhã?",
        "JARVIS, quais conexões você tem?",
        "JARVIS, qual a previsão do tempo amanhã?",  # NO match — should return None
    ]
    for q in tests:
        r = route_integration_question(q)
        if r:
            print(f"  [ROUTED] {q!r} -> {r[:80]}")
        else:
            print(f"  [PASSTHROUGH] {q!r}")