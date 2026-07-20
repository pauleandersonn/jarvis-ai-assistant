# PC Runbook — 20/07/2026

**Pra que serve:** Quando Paulo sentar no PC, ele precisa que o JARVIS
conte exatamente o que fazer pra retomar as 3 frentes que ficaram pausadas.

**Como o JARVIS encontra:** Pergunte "O que eu preciso fazer hoje?" ou
"O que tá pendente no PC?" — esta nota deve aparecer na busca do brain.

---

## Frente 1: Bot Finanças 24/7 no Fly.io (PRIORIDADE ALTA)

**Onde:** `C:\Users\paule\Documents\PROGRAMAÇÃO\financas_bot\`

**Por quê parado:** Postgres Basic de $38/mês cancelado, app `luap-financas-bot`
criada em GRU (São Paulo), volume `finance_data` (1GB) já montado em `/data`.
Tudo commitado (`0faaa25`), mas os 4 secrets não foram setados porque
Paulo não tava no PC pra colar token Telegram novo.

**O que fazer:**

1. **Revogar token Telegram antigo** (incidente 17/07)
   - Abre `@BotFather` no Telegram
   - `/mybots` → `@fiannacas_paul_gaby_bot` → `/revoke`
   - Anota o token novo

2. **Abrir PowerShell** na pasta do bot:
   ```powershell
   cd "C:\Users\paule\Documents\PROGRAMAÇÃO\financas_bot"
   notepad setup-rapido.ps1
   ```
   - Colar o token novo no lugar de `PLACEHOLDER`
   - Salvar

3. **Rodar o script:**
   ```powershell
   .\setup-rapido.ps1
   ```
   - Ele faz: `fly secrets set DATABASE_URL TELEGRAM_BOT_TOKEN TELEGRAM_BOT_USERNAME HEALTHCHECK_TOKEN`
   - Pede confirmação 1x (digita `y`)

4. **Deploy:**
   ```powershell
   fly deploy
   ```

5. **Upload do banco pro volume:**
   ```powershell
   fly ssh sftp shell
   ```
   - Dentro do SSH: `cd /data && put finance.db`
   - Exit (Ctrl+D)

6. **Setar webhook Telegram:**
   ```powershell
   curl -F "url=https://luap-financas-bot.fly.dev/webhook/telegram" `
        "https://api.telegram.org/bot<TOKEN_NOVO>/setWebhook"
   ```

7. **Testar:**
   ```powershell
   curl https://luap-financas-bot.fly.dev/health
   ```
   - Esperado: `{"status":"healthy",...}`

8. **Testar no Telegram:** manda `/start` pro `@fiannacas_paul_gaby_bot`

**Backup do banco:** `finance.db.bak.20260720-prefly` (13 tabelas, 54 transactions, 8 users)
**Custo:** $0/mês (SQLite + volume 1GB)

---

## Frente 2: Ativar WebhookNotifier no day-trade-bot

**Onde:** `C:\Users\paule\Documents\PROGRAMAÇÃO\day-trade-bot\.env`

**Estado atual:** WebhookNotifier já foi implementado e commitado (`fa9bfe1`).
JARVIS já recebe sinais (4 eventos no buffer). Falta **ativar no main loop**.

**O que fazer:**

1. **Criar `.env`** (copia do `.env.example`):
   ```powershell
   cd "C:\Users\paule\Documents\PROGRAMAÇÃO\day-trade-bot"
   copy .env.example .env
   notepad .env
   ```

2. **Colar o token compartilhado** (mesma string do JARVIS):
   ```
   JARVIS_WEBHOOK_TOKEN=trade-webhook-secret-Tule0D_chRqA7gpymQMx1qao_vCpj0TXwAfXyEcD1As
   ```
   - Esse token já tá em `C:\Users\paule\Projects\jarvis-ai-assistant\.env`

3. **Ligar WebhookNotifier no main.py:**
   - Abre `src\daytrade_bot\engine\main.py`
   - Troca `TelegramNotifier` ou `NullNotifier` por `WebhookNotifier.from_env()`
   - (Ou passa pelo CLI: `--notifier webhook` se eu adicionar flag)

4. **Rodar backtest:**
   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m daytrade_bot.engine.main --broker paper --candles 1000
   ```

5. **Conferir no JARVIS:** http://localhost:8788 → drawer → aba **Trade**
   - Cards coloridos aparecem (verde=CALL, vermelho=PUT)
   - Toast azul no canto superior direito quando chega sinal

**Bug antigo resolvido:** HTTP 500 era causado pelo PYTHONPATH do shell apontando
pro hermes-venv (pydantic_core binário incompatível com Python 3.14). Pra
subir o dashboard certo:
```powershell
cd "C:\Users\paule\Projects\jarvis-ai-assistant"
$env:PYTHONPATH = ""
& "C:\Users\paule\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" -u dashboard.py
```

---

## Frente 3: Limpezas opcionais (sem pressa)

- **JARVIS duplicata:** `C:\Users\paule\Documents\PROGRAMAÇÃO\jarvis-ai-assistant\`
  é versão antiga (sem MCP). Pode deletar. Só usa `C:\Users\paule\Projects\jarvis-ai-assistant\`
- **day-trade-bot sem remote:** tá só local. Se quiser publicar, criar remote no GitHub
- **cloudflared/ngrok locais:** rodar só pra túnel, com Fly tá resolvido

---

## Resumo executivo (quando Paulo perguntar "o que eu preciso fazer?")

> **3 frentes pausadas, todas com script pronto:**
>
> 1. **Bot Finanças Fly** — `setup-rapido.ps1` + 7 passos manuais (~15min)
> 2. **WebhookNotifier no day-trade-bot** — colar token em `.env`, trocar `NullNotifier` por `WebhookNotifier.from_env()` (~5min)
> 3. **Limpezas opcionais** — sem urgência
>
> **Custo total:** $0/mês
> **Risco:** Token Telegram ainda exposto do incidente 17/07 — revogar ANTES do deploy Fly