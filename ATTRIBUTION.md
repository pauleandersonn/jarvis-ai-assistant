# Atribuições e Créditos — JARVIS Premium Edition

Este projeto integra trechos adaptados do **Mark XLIX**, projeto de [FatihMakes](https://github.com/FatihMakes/Mark-XLIX), sob licença **CC BY-NC 4.0** (Creative Commons Atribuição-NãoComercial 4.0 Internacional).

## Componentes adaptados

| Componente | Arquivo original | Arquivo no JARVIS | Modificações |
|---|---|---|---|
| LLM client (Ollama/OpenAI wrapper) | `core/llm_client.py` | `Brain/llm_client.py` | Adicionado provider "freeai" como default (webscout.FreeAI, sem key). Adicionada delegação via env var `JARVIS_LLM_PROVIDER`. Preservada 100% da API Ollama + OpenAI-compatible. |
| System prompt | `core/prompt.txt` | `Brain/prompt.txt` (referência) | Copiado integralmente. Regras de roteamento de tools, language detection, system alerts, startup briefing, proactive check estão sendo mescladas no `JARVIS_SYSTEM` (em `Brain/brain.py`). |

## Pendentes (próximas integrações)

- `memory/memory_manager.py` — schema de memória (identity/preferences/projects/relationships/wishes/notes)
- `actions/reminder.py` — sistema de lembretes via schtasks
- `actions/open_app.py` — abrir apps via OS (50+ aliases cross-platform)

## Licença

Mark XLIX © FatihMakes. Distribuído sob CC BY-NC 4.0.
Texto legal: https://creativecommons.org/licenses/by-nc/4.0/

JARVIS Premium © @pauleandersonn. MIT para o código próprio; CC BY-NC 4.0 aplica-se às partes adaptadas do Mark XLIX.