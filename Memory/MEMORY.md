---
name: JARVIS Memory Index
description: Persistent memory of projects, decisions and pending tasks for Pauleanderson
type: project
updated: 2026-07-20
---

# JARVIS — Memória Persistente

Esta é a memória de longo prazo do JARVIS (assistente pessoal do Pauleanderson).
Tudo que é conversado, decidido ou cadastrado aqui fica disponível em futuras sessões.

## Projetos ativos

Cada projeto tem um arquivo próprio em `./Projects/<slug>.md`.

| # | Projeto | Slug | Status |
|---|---|---|---|
| 1 | Indica AI | indica-ai | Ativo |
| 2 | We Love Memory | we-love-memory | Ativo |
| 3 | Luap Studio | luap-studio | Ativo |
| 4 | Pollar Agência |ollar | Ativo |
| 5 | JF Alimentação | jf-alimentacao | Ativo |
| 6 | HubCare | hubcare | Ativo |
| 7 | Ofertas Zero92 | ofertas-zero92 | Ativo |
| 8 | Mídia Criativa do Reino | midia-criativa-do-reino | Ativo |
| 9 | Finance Agent | finance-agent | Ativo |

## Índice de seções

- `jarvis-persona.md` — constituição cognitiva do JARVIS (prompt expandido, raciocínio, especialidade, limites)
- `integrations.md` — serviços externos conectados (Gmail, Calendar, OAuth tokens, endpoints)
- `Projects/` — um arquivo `.md` por projeto (objetivo, tarefas, decisões, próximos passos)
- `decisions.md` — log de decisões importantes (cross-project)
- `tasks.md` — tarefas pendentes globais

## Como o JARVIS usa

1. Ao receber qualquer pergunta, o JARVIS lê esta memória.
2. Se a pergunta menciona um projeto (direta ou indiretamente), carrega o arquivo do projeto.
3. Respostas incorporam o contexto encontrado aqui.
4. Quando algo novo surge, JARVIS atualiza o arquivo apropriado.
5. **Antes de responder**, JARVIS consulta `jarvis-persona.md` para alinhar tom, raciocínio e formato.

## Última atualização
2026-07-20 — Gmail + Google Calendar integrados (integrations.md criado).