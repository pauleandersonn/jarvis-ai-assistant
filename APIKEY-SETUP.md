# JARVIS AI Assistant - Setup da API Key (OpenAI-Compat)

Use uma API key de **OpenAI** (ou qualquer provedor OpenAI-compat) para trocar
o cerebro padrao (freeai / webscout) por um modelo de maior qualidade.

## 1. Qualquer metodo (mesmo efeito)

| Metodo | Como | Persiste em reboot? | Vaza em git? |
|---|---|---|---|
| **A) Script PowerShell (recomendado)** | `.\Windows_Set-OpenAIKey.ps1` (pede a chave de forma segura) | sim (setx) | nao |
| **B) Variavel de ambiente `setx`** | `setx JARVIS_OPENAI_API_KEY "sk-..."` | sim | nao |
| **C) Arquivo `.env`** | Copie `.env.example` para `.env` e preencha | sim (enquanto o arquivo existir) | nao (`.env` esta no .gitignore) |
| **D) Bloco em `config/api_keys.json`** | Edite o campo `openai_api_key` | sim | depende de gitignore (ja coberto com `!config/api_keys.json`) |

**Precedencia**: env var > `config/api_keys.json` > `.env` > default (freeai).

## 2. Onde obter uma chave

- **OpenAI**: https://platform.openai.com/api-keys (cria, copia `sk-...`)
- **Groq** (mais rapido, free tier generoso): https://console.groq.com/keys
- **OpenRouter** (acessa varios modelos): https://openrouter.ai/settings/keys
- **DeepSeek**: https://platform.deepseek.com/api_keys
- **Together**: https://api.together.xyz/settings/api-keys

## 3. Escolher provedor

```powershell
# OpenAI
setx JARVIS_LLM_PROVIDER openai_cloud
setx JARVIS_OPENAI_BASE_URL "https://api.openai.com/v1"
setx JARVIS_OPENAI_MODEL "gpt-4o-mini"      # ou gpt-4o, o1-mini, etc.

# Groq
setx JARVIS_LLM_PROVIDER openai_cloud
setx JARVIS_OPENAI_BASE_URL "https://api.groq.com/openai/v1"
setx JARVIS_OPENAI_MODEL "llama-3.1-70b-versatile"
setx JARVIS_OPENAI_API_KEY "gsk_..."

# OpenRouter
setx JARVIS_LLM_PROVIDER openai_cloud
setx JARVIS_OPENAI_BASE_URL "https://openrouter.ai/api/v1"
setx JARVIS_OPENAI_MODEL "anthropic/claude-3.5-sonnet"
setx JARVIS_OPENAI_API_KEY "sk-or-..."
```

## 4. Teste rapido

```powershell
.\Windows_Set-OpenAIKey.ps1 -ApiKey "sk-..."
```

Vai:
1. Definir a env var (sessao + setx para persistencia)
2. Atualizar `.env` (NUNCA commitar)
3. Bater em `https://api.openai.com/v1/models` para confirmar que a chave e' valida
4. Imprimir mascara: `sk-abc...xyz`

## 5. Reverter para o modo sem-chave

Basta nao definir `JARVIS_OPENAI_API_KEY` (ou muda-la para string vazia). O
JARVIS automaticamente cai no provider `freeai` (webscout, sem chave).

## 6. Seguranca

- A chave **NUNCA** e' logada em texto claro - use `_safe_mask_key()` se for
  mostrar em log (`sk-ab...1234`).
- `.env`, `.env.*`, `*.key`, `*.pem`, `config/secrets.json` estao no
  `.gitignore`.
- O `config/api_keys.json` template (com string vazia) e' commitado,
  intencionalmente. Ao inserir uma chave real la, **remova o arquivo do
  historico** antes de publicar.

## 7. Verificar no boot

O endpoint `/api/greeting` retorna o status atual da chave:

```json
{
  "text": "Boa tarde...",
  "llm":  "Cerebro: gpt-4o-mini (online, via https://api.openai.com/v1)."
}
```

- `online` = chave valida (200 OK em /models)
- `offline` = chave ausente, rejeitada ou rede com erro

Aparece embaixo do orbe no dashboard, sem ser falado via TTS.
