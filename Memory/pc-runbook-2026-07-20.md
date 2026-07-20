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

**Estado atual (20/07):** ✅ WebhookNotifier JÁ foi implementado (`fa9bfe1`),
testado E2E (buffer JARVIS: 5→20 sinais em 1 backtest), `--notify webhook`
já tá wired no main.py. **Telegram NÃO tá funcionando** (token revogado
no incidente 17/07 — HTTP 401 Unauthorized).

**Backlog de execução:**

1. **Webhook (FUNCIONANDO — opcional)**
   - Token compartilhado já tá no `.env`
   - Roda: `.\.venv\Scripts\python.exe -m daytrade_bot.engine.main --broker paper --candles 1000 --notify webhook`
   - Ver no JARVIS: drawer → aba Trade → 12+ cards aparecem

2. **Telegram (✅ FUNCIONANDO — token regenerado 20/07 18h)**
   - Token novo: `8721601546:[REDACTED]` (validado via `getMe` retorna `@luaptrade_bot`)
   - `getChat(919764574)` confirma acesso ao chat privado Paulo
   - Smoke test LIVE `--notify telegram --candles 200` → 1 WIN (+R$ 8.50)
   - Mensagem de teste enviada (msg_id 560)
   - Se quebrar de novo: mesma receita, `@BotFather → /mybots → /revoke`

3. **Wire-up final no main loop** (próximo passo depois que Paulo validar)
   - Abre `src\daytrade_bot\engine\main.py` na linha ~88
   - Troca `notifier = NullNotifier()` por lógica que escolhe baseado em env var:
     ```python
     notifier_mode = os.environ.get('DAYTRADE_NOTIFIER', 'webhook')
     if notifier_mode == 'telegram':
         notifier = TelegramNotifier.from_env()
     elif notifier_mode == 'webhook':
         notifier = WebhookNotifier.from_env()
     ```
   - Ou mais simples: adicionar `--notify both` (telegram + webhook ao mesmo tempo)

4. **Rodar backtest real (já funciona):**
   ```powershell
   cd "C:\Users\paule\Documents\PROGRAMAÇÃO\day-trade-bot"
   .\.venv\Scripts\Activate.ps1
   python -m daytrade_bot.engine.main --broker paper --candles 1000 --notify webhook
   ```

5. **Conferir no JARVIS:** http://localhost:8788 → drawer → aba **Trade**
   - Cards coloridos aparecem (verde=CALL, vermelho=PUT)
   - Toast azul no canto superior direito quando chega sinal
   - Buffer ring tem 50 slots (deque maxlen=50, descarta antigos)

**Bug antigo resolvido:** HTTP 500 era causado pelo PYTHONPATH do shell apontando
pro hermes-venv (pydantic_core binário incompatível com Python 3.14). Pra
subir o dashboard certo:
```powershell
cd "C:\Users\paule\Projects\jarvis-ai-assistant"
$env:PYTHONPATH = ""
& "C:\Users\paule\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" -u dashboard.py
```

**Bug NOVO resolvido (20/07):** `.env` não era carregado pelo main.py (só
TelegramNotifier/WebhookNotifier liam `os.environ` direto). Adicionado
`load_dotenv()` no main.py — agora `--notify telegram/webhook` funciona
via CLI sem precisar setar env no shell.

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
---

## Frente 4: Camada de Oportunidades IA (Telegram + WhatsApp) ✅ CONCLUÍDA 20/07 18h

**Onde:** `C:\Users\paule\Projects\jarvis-ai-assistant\Brain\integrations\` + `Brain/actions\`

### O que foi feito (commit 06db3c99)

- **WhatsApp Meta Cloud API** (`Brain/integrations/whatsapp.py`)
  - Cliente HTTP completo: `health_check`, `verify_webhook`, `send_text_message`, `send_signal_message`
  - Formato de sinal Pauleanderson M5 com/sem gale
- **WhatsApp Analyzer** (`Brain/actions/whatsapp_analyzer.py`)
  - LLM classifica em: fotografia, filmagem, tecnologia, comunicação ministerial
  - **Fallback heurístico** (roda offline sem API key!)
  - Detecta orçamento (R$), reclamação, feature request
- **Telegram Opportunities Store** (`Brain/integrations/telegram_opportunities_store.py`)
  - SQLite `telegram_opportunities.db` com CRUD + stats
  - Filtros: categoria, status, score mínimo, hot leads
  - Status: novo → contatado → convertido/perdido
- **Telegram Analyzer** (`Brain/actions/telegram_analyzer.py`)
  - 5 categorias: lead_comercial, problema_cliente, ideia_produto, sinal_correlato, conversa_casual
  - Triagem rápida com `\b` (evita "gale" match em "galera")
  - Fallback heurístico (offline)
- **Telegram Signal Linker** (`Brain/actions/telegram_signal_linker.py`)
  - DB de sinais de trade com correlação 15min window
  - Detecta: "pessoal falou de EUR enquanto saía sinal CALL"
- **WhataApp opportunities store** (`Brain/integrations/opportunities_store.py`)
  - Armazenamento genérico (não-Telegram) pra mensagens WhatsApp

### 12 endpoints NOVOS no dashboard.py

- `GET/POST /api/integrations/whatsapp/health`
- `POST /api/integrations/whatsapp/webhook` (Meta verify)
- `POST /api/integrations/whatsapp/analyze`
- `POST /api/integrations/whatsapp/signal` (formato M5 Pauleanderson)
- `POST /api/integrations/telegram/inbound` (recebe + classifica)
- `GET /api/integrations/telegram/opportunities` (lista)
- `GET /api/integrations/telegram/opportunities/stats` (agregados)
- `GET /api/integrations/telegram/opportunities/top` (briefing)
- `GET /api/integrations/telegram/opportunities/brief` (TTS pt-BR)
- `POST /api/integrations/telegram/opportunities/{id}/status`
- `POST /api/integrations/telegram/signal`
- `GET /api/integrations/telegram/signals/recent`

### Testes E2E (rodaram)

11 oportunidades detectadas com 5 hot leads, 4 categorias distintas:
- `lead_comercial`: Maria (Grupo Marketing): "quanto custa pra fazer um video?"
- `problema_cliente`: Joao (Suporte): "bot parou, deu erro geral"
- `ideia_produto`: Carla (Devs): "seria bom se tivesse auto-gale"
- `sinal_correlato`: Pedro (Grupo Trade): "perdi no EUR/USD"

### Próximos passos

1. Wire python-telegram-bot no JARVIS pra escutar grupos reais (polling ou webhook)
2. Criar cron que envia `/api/integrations/telegram/opportunities/brief` pro `@luap_pc_bot` às 18h
3. Quando bot Finanças estiver no Fly, ligar as 2 pontas via webhook
4. Configurar Meta Cloud API (whatsapp) com chip Vivo + Meta Business Manager (~3-7 dias)
