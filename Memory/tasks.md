---
name: Tarefas Globais Pendentes
description: Tarefas que não pertencem a um projeto específico
type: project
updated: 2026-07-20
---

# Tarefas Globais

Tarefas que não cabem em um único projeto.

## Pendentes

- [ ] **Bot Finanças 24/7 no Fly.io** — `setup-rapido.ps1` pronto em `C:\Users\paule\Documents\PROGRAMAÇÃO\financas_bot\`. Falta revogar token Telegram antigo + colar 4 secrets + `fly deploy` (~15min) — detalhes em `pc-runbook-2026-07-20.md`
- [ ] **Ativar WebhookNotifier no day-trade-bot** — colar token compartilhado em `.env`, trocar `NullNotifier` por `WebhookNotifier.from_env()` no `main.py` (~5min) — detalhes em `pc-runbook-2026-07-20.md`
- [ ] Configurar uma LLM melhor que FreeAI (quando decidir qual)
- [ ] Documentar a arquitetura do JARVIS num README
- [ ] Adicionar Wake Word ("Jarvis" pra ativar)

## Em progresso

*(nenhuma)*

## Concluídas recentemente

- [x] day-trade-bot ↔ JARVIS via webhook (story 2.0) — 4 sinais no buffer, aba Trade + toast push funcionando
- [x] Clonar e limpar projeto original (AnubhavChaturvedi)
- [x] Implementar brain, TTS, weather, image gen
- [x] Criar dashboard FastAPI com UI premium
- [x] Adicionar web research com auto-detecção
- [x] Criar memória persistente dos projetos