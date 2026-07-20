---
name: Decisões Globais
description: Log de decisões cross-project
type: project
updated: 2026-07-20
---

# Decisões Globais

Este arquivo registra decisões importantes que afetam múltiplos projetos ou o setup geral do JARVIS.

## 2026-07-16

- **Stack principal**: Python 3.14 + FastAPI (dashboard) + FreeAI via webscout (LLM sem API key).
- **TTS**: Windows SAPI5 com render para WAV + abertura via player padrão (evita bug do `Speak()` direto no uvicorn worker).
- **Web search**: implementação própria em `Brain/researcher.py` (DDG + BeautifulSoup + FreeAI synthesis).
- **Memória persistente**: pasta `Memory/Projects/` + índice em `Memory/MEMORY.md`.
- **Identidade**: JARVIS como sistema operacional pessoal, operando em PT-BR.
- **Idioma de resposta**: forçado em PT-BR via prepend de instrução (FreeAI ignora `system_prompt`).

## Próximas decisões a tomar

- Migrar para uma LLM melhor (Claude / GPT / Ollama local)? — pendente
- Adicionar integração com IDE / Git? — pendente
- Adicionar agente MCP para automação real? — pendente