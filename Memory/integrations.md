---
name: JARVIS Integrations
description: Serviços externos conectados ao JARVIS via API (Gmail, Calendar, etc.)
type: integrations
updated: 2026-07-20
---

# JARVIS — Integrações Externas

Serviços conectados ao JARVIS via OAuth/API. Cada integração expõe endpoints HTTP no dashboard (porta 8788) e funções Python em `Brain/actions/`.

## Gmail (pauleandersongomes@gmail.com)

**Status:** Conectado 2026-07-20, OAuth2 Desktop app, refresh token salvo.

**Endpoint base:** `/api/email/*`

| Endpoint | Função | Cuidado? |
|---|---|---|
| `POST /api/email/search` | Buscar emails por query Gmail (`is:unread`, `from:X`, `newer_than:Nd`) | Não |
| `POST /api/email/inbox-summary` | Resumo TTS-friendly da inbox | Não |
| `POST /api/email/send` | Enviar email | **SIM — confirma com o usuário antes** |

**Funções Python:** `Brain/actions/gmail.py`
- `search_emails(query, max_results) -> dict`
- `get_email(msg_id) -> dict`
- `send_email(to, subject, body, html=False, from_alias=None) -> dict`
- `summarize_inbox(query, max_results) -> str` (TTS-friendly)
- `summarize_email(msg_id) -> str`

**Como usar:**
- Por voz: "JARVIS, o que tem na minha inbox?" → o brain deve chamar `/api/email/inbox-summary` e falar o summary
- Por texto: pedir "resuma os emails não lidos"
- Por voz enviando: "JARVIS, manda email pra X dizendo Y" → CONFIRMAR antes de chamar `/api/email/send`

**Exemplos de query Gmail:**
- `is:unread` — só não lidos
- `is:unread newer_than:2d` — não lidos das últimas 48h
- `from:linkedin` — só do LinkedIn
- `subject:boleto` — só com "boleto" no assunto
- `has:attachment` — só com anexo

## Google Calendar (pauleandersongomes@gmail.com)

**Status:** Conectado 2026-07-20, Calendar API v3, OAuth compartilhado com Gmail.

**Endpoint base:** `/api/calendar/*`

| Endpoint | Função | Cuidado? |
|---|---|---|
| `POST /api/calendar/list` | Listar eventos entre `start` e `end` (ISO 8601) | Não |
| `POST /api/calendar/create` | Criar evento | **SIM — confirma antes** |
| `POST /api/calendar/delete` | Deletar evento por ID | **SIM — confirma antes** |
| `POST /api/calendar/agenda-summary` | Resumo TTS-friendly da agenda | Não |

**Funções Python:** `Brain/actions/gcalendar.py`
- `list_events(start=None, end=None, max_results=25) -> dict`
- `create_event(summary, start_iso, end_iso, location, description, attendees) -> dict`
- `delete_event(event_id) -> dict`
- `summarize_agenda(start=None, end=None, max_events=5) -> str` (TTS-friendly, com "hoje às X", "amanhã às Y", etc.)

**Timezone:** o calendário usa horário local do Paulo (Manaus = UTC-4). Envie `start_iso`/`end_iso` com offset (`-03:00` se for horário de Brasília, `-04:00` pra Manaus).

**Como usar:**
- Por voz: "JARVIS, o que tenho na agenda amanhã?" → `/api/calendar/agenda-summary` com end=amanhã+1
- "JARVIS, agenda reunião com Renato amanhã às 14h" → `/api/calendar/create` (CONFIRMAR antes)
- "JARVIS, cancela o evento das 15h" → listar, achar ID, `/api/calendar/delete` (CONFIRMAR antes)

## Skill subjacente

Tudo passa pela skill `productivity/google-workspace` em `~/AppData/Local/hermes/skills/`. Ela cuida do OAuth token + refresh automático.

**Comandos úteis pra debug:**
```bash
python ~/AppData/Local/hermes/skills/productivity/google-workspace/scripts/setup.py --check
python ~/AppData/Local/hermes/skills/productivity/google-workspace/scripts/google_api.py gmail search "is:unread"
python ~/AppData/Local/hermes/skills/productivity/google-workspace/scripts/google_api.py calendar list
```

## Última atualização
2026-07-20 — Gmail + Google Calendar integrados via OAuth2.