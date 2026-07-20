# WhatsApp no JARVIS — Sketch + Análise de Oportunidades

**Data:** 2026-07-20 (segunda)
**Status:** Pincelado — conversa inicial entre Paulo e JARVIS

---

## TL;DR

Adicionar WhatsApp como canal **bidirecional** do JARVIS:
- **Inbound:** Paulo manda áudio/texto/foto do Zap → JARVIS processa → responde com insight (voz ou texto)
- **Outbound:** JARVIS dispara alertas pro Zap de Paulo (sinais de trade, eventos Calendar, lembretes, briefings matinais)

**Por que isso muda o jogo:** JARVIS deixa de ser só "dashboard sentado no PC" e vira **assistente que te acompanha onde você estiver** — exatamente quando você tá na rua fazendo ensaio fotográfico, gravando, ou no culto.

---

## Stack técnico — 2 caminhos

### Caminho A: WhatsApp Business API (OFICIAL) ✅ recomendado

**Provider:** Meta Cloud API (gratuito pra 1000 conversas/mês no tier inicial)

**Arquitetura:**
```
WhatsApp Cloud API
        ↓ webhook (HTTPS)
JARVIS (FastAPI no Fly.io, mesmo host do financas_bot)
        ↓
Brain/actions/whatsapp.py
        ↓
Memória + Gmail/Calendar já existentes
        ↓
Resposta via Cloud API (text/voice/template)
```

**Vantagens:**
- Oficial Meta, sem risco de ban
- Webhook HTTPS, igual aos outros sistemas
- Free tier generoso (1000 conversas/mês)
- Funciona com número comercial
- Suporta texto, áudio, imagem, vídeo, documento, localização, contato

**Desvantagens:**
- Precisa de **Meta Business Account** + número dedicado (não pode ser o pessoal)
- Setup inicial do Business Manager demora 1-3 dias (aprovação Meta)
- Templates de mensagem precisam aprovação prévia pra iniciar conversa (pro outbound)

### Caminho B: Baileys / whatsmeow (NÃO OFICIAL) ⚠️ arriscado

**Provider:** bibliotecas open-source que emulam o protocolo do WhatsApp Web

**Arquitetura:**
```
WhatsApp Web (via lib)
        ↓ polling / event listener
JARVIS local (:8788)
        ↓
Brain/actions/whatsapp_unofficial.py
```

**Vantagens:**
- Funciona com **seu número pessoal** direto
- Zero custo de setup, imediato
- Mais flexível (sem limite de templates)

**Desvantagens:**
- ❌ Risco real de ban do Meta (eles bloqueiam)
- ❌ Quebra a cada update do WhatsApp (lib fica atrasada)
- ❌ Viola ToS do WhatsApp
- ❌ Não escala

**Recomendação:** **Caminho A** pra produção. Caminho B só pra MVP descartável/testes.

---

## Onde encaixa no JARVIS atual

### O que JÁ EXISTE (reaproveitar):
- ✅ FastAPI server (dashboard.py, :8788)
- ✅ Brain com ações (gmail.py, gcalendar.py, mcp_server.py)
- ✅ WebSocket push (notificações ao vivo no dashboard)
- ✅ Memory persistente (Projects/ + tasks.md)
- ✅ Voice confirm (voz pt-BR-AntonioNeural)
- ✅ Token management (OAuth Google, Telegram já tem padrão)
- ✅ Deploy Fly.io (template do financas_bot pronto)

### O que PRECISA construir:
1. **Integração WhatsApp Cloud API** (`Brain/actions/whatsapp.py`)
   - Webhook handler pra mensagens recebidas
   - Cliente de envio (texto + áudio)
2. **Módulo Brain/WhatsAppBrain** — decide se msg é comando / pergunta / voz / foto
3. **Number provisioning** — setup do Meta Business Manager
4. **Template messages** — pelo menos 3 pra outbound:
   - `daily_briefing` — resumo matinal
   - `trade_signal` — alerta de sinal
   - `event_reminder` — lembrete de compromisso
5. **Storage** — histórico de conversas (SQLite, mesmo padrão do financas_bot)

---

## Análise de oportunidades por vertical

### 📸 1. Fotografia

**Oportunidade concreta:** Briefing matinal automático antes de cada ensaio.

**Fluxo do dia:**
```
07:00  JARVIS (Zap): "Bom dia! Hoje tem ensaio externo às 14h. 
       Previsão Manaus: 31°C, 70% chance de chuva às 15h. 
       Sugestão: fazer externas antes das 14h. Tem cliente VIP?"
       
07:05  Paulo (Zap, áudio): "Sim, casamento Ana e Carlos. Quero
       pôr do sol no início."

07:06  JARVIS: "Anotado! Lembrete: golden hour hoje às 18:23. 
       Posso criar lembrete Calendar?"
```

**Oportunidades de monetização:**
- Briefing diário premium (R$ 29/mês) — prevê luz, chuva, calendário,黄金時刻
- Lembrete automático pra golden hour / blue hour (notificação 15min antes)
- Sugestões de location baseado no estilo do ensaio + horário
- **Pitch pra clientes finais:** "Fotógrafo com IA = briefing inteligente diário"

**Complexidade:** Baixa (já temos calendar + weather)

---

### 🎥 2. Filmagem

**Oportunidade concreta:** Storyboard automático + checklist técnico por cena.

**Fluxo:**
```
Paulo (Zap, áudio 30s): "Vou gravar um mini-doc de 3 minutos 
sobre o festival. Tenho 4 entrevistas marcadas amanhã 9h, 11h, 
14h, 16h. Quero algo mais intimista, handheld."

JARVIS: "Storyboard gerado:
🎬 Cena 1 — Abertura (9h00): plano geral do festival chegando
🎬 Cena 2 — Entrevista 1 (9h30): close + plano médio
🎬 Cena 3 — B-roll público (10h30): handheld em movimento
...
⚠️  Backup de bateria a cada 2h
⚠️  Cartão SD 128GB (8h de filmagem 4K = ~64GB)

Quer que eu transforme em checklist no Notion?"
```

**Oportunidades de monetização:**
- Storyboard-as-a-Service (R$ 49/mês) — gera storyboard completo a partir de briefing de áudio
- Checklist técnico automático (bateria, áudio, iluminação, backup)
- Sugestões de equipamento baseado no tipo de gravação
- Cronograma otimizado (combinar GPS + tempo + golden hour)
- **Pitch pra produtoras pequenas:** "Diretor com IA que planeja tudo"

**Complexidade:** Média (precisa LLM bom pra interpretar áudio + gerar plano)

---

### 💻 3. Tecnologia / Desenvolvimento

**Oportunidade concreta:** JARVIS vira hub de voz pra devs — code review, deploy alerts, debugging.

**Fluxo:**
```
JARVIS (Zap): "🔔 Build #384 falhou no JARVIS-gcal v3. 
       Erro: TypeError: 'NoneType' object is not iterable 
       em dashboard.py linha 412.
       
Quer que eu faça git diff da última alteração e sugira fix?"

Paulo (Zap): "sim, faz"

JARVIS: "Último commit afetou dashboard.py:
       a52e399e feat(dashboard): integra day-trade-bot
       
       Suspeita: a função loadTradeRecent assume events[] 
       sempre presente. Em bot recente, pode vir vazio.
       
       Fix sugerido:
       [code snippet de 5 linhas]
       
       Quer que eu commite e push?"
```

**Oportunidades de monetização:**
- JARVIS DevOps (R$ 99/mês) — GitHub + CI/CD + alerts no Zap
- Code review em áudio (manda print do erro, JARIS explica em pt-BR)
- **Pitch pra devs solo e startups pequenas:** "Tenha um SRE no Zap"

**Complexidade:** Alta (precisa GitHub Actions integration, parsing de logs, code understanding)

---

### ⛪ 4. Comunicação Ministerial / Igreja

**Oportunidade concreta:** **Esse é o caso MAIS forte e ÚNICO de Paulo.** A Lagoinha Manaus (e igrejas em geral) têm um padrão que se encaixa PERFEITAMENTE no JARVIS+Zap:

**Fluxo do ministro:**
```
07:00  JARVIS (Zap): "Bom dia, Paulo. 
       📅 Hoje (Ter 21/07):
       • 19h Lagoinha (já no Calendar)
       • 1 evento da semana ainda sem descrição
       
       ☁️ Previsão: 28°C, sem chuva (ótimo pra culto ao ar livre)
       
       📖 Sugestão de estudo: Romanos 8 (tema: esperança na tribulação)
       🎵 Sugestão de louvor: 'Tua Graça Me Basta' (tom G) — 
       encaixa no devocional de hoje"

08:00  (enquanto dirige pro trabalho)
JARVIS: "🎵 Áudio 2min: meditação em Romanos 8:28 
       'E sabemos que todas as coisas contribuem 
       juntamente para o bem...'"
```

**Oportunidades de monetização (ESSE É O OURO):**
- **Devocional diário personalizado por áudio** (R$ 19/mês)
  - Lê versículo do dia + comentário curto em pt-BR com voz grave
  - Pra quem tem rotina corrida (ministerial, médico, advogado)
- **Briefing ministerial semanal** (R$ 39/mês)
  - Plano de pregação sugerido
  - Louvores compatíveis (com letra e tom)
  - Estudos bíblicos temáticos
- **App pra igreja local** (R$ 199/mês)
  - Cada membro recebe devocional personalizado
  - Avisos de culto, eventos, escala
  - **Diferencial:** outras igrejas pagam R$ 500+ pra empresa fazer isso
- **Curso online** — "Como criar um assistente ministerial com IA"
  - R$ 497 por aluno
  - Público: pastores, líderes de Ministério Infantil, MCs gospel
  - Concorrência: ZERO (ninguém tá fazendo isso)

**Por que essa vertical é a mais forte:**
- Paulo É o usuário + É o exemplo-vivo (credibilidade)
- Manaus tem ~300 igrejas evangélicas (~20.000 ministros no Amazonas)
- Demanda existe: ministro trabalha 50-60h/semana, tempo de devocional é o primeiro que some
- Concorrência: YouVersion / Bible Gateway (genéricos), Bíblias apps (não fazem devocional em áudio)
- **JARVIS já tem a voz (pt-BR-AntonioNeural grave)** que combina com cultos

**Complexidade:** Média (precisa Bíblia digital + LLM pra gerar devocionais)

---

## 💰 Projeção de receita (12 meses)

| Vertical | Pricing | Clientes/mês alvo | Receita anual |
|---|---|---|---|
| Fotógrafo (briefing diário) | R$ 29/mês | 50 | R$ 17.400 |
| Filmmaker (storyboard) | R$ 49/mês | 20 | R$ 11.760 |
| Dev (JARVIS DevOps) | R$ 99/mês | 10 | R$ 11.880 |
| Ministerial (devocional áudio) | R$ 19/mês | 200 | R$ 45.600 |
| Ministerial (briefing pastoral) | R$ 39/mês | 30 | R$ 14.040 |
| Igreja (app white-label) | R$ 199/mês | 5 | R$ 11.940 |
| Curso online | R$ 497 | 50 vendas | R$ 24.850 |
| **TOTAL ANO 1** | | | **R$ 137.470** |

**Premissas conservadoras.** Se metade do alvo bater → R$ 68k/ano (1 salário mínimo integral mensal extra, ou investimento em equipamento).

---

## MVP em 1 semana — Recomendação

### Semana 1: WhatsApp bidirecional + 1 vertical (a ministerial)

Por quê ministerial primeiro:
- É a que **Paulo já vive** (validação instantânea)
- É a que tem **menos concorrência** (mercado azul)
- É a que combina com a **voz grave** do JARVIS
- É a que gera **case study** rápido pra vender pros outros

**Tarefas:**
1. **Dia 1 (terça):** Setup Meta Business Manager + provisionar número
   - Usar número separado do pessoal
   - Sugestão: chip pré-pago Vivo R$ 15/mês
2. **Dia 2 (quarta):** Implementar webhook WhatsApp Cloud API
   - Brain/actions/whatsapp.py (similar ao gmail.py)
   - Webhook handler em dashboard.py
   - Token persistence (WhatsApp Cloud API token é permanente)
3. **Dia 3 (quinta):** Devocional diário automático
   - Bíblia digital (API gratuita: bible-api.com ou abibliadigital.com.br)
   - LLM gera 200 palavras de reflexão contextual
   - TTS AntonioNeural grave → arquivo .ogg → envia no Zap às 7h
4. **Dia 4 (sexta):** Briefing matinal (calendário + clima + versículo)
   - Mesmo template que Gmail/Calendar já tem
   - Schedule via cron do JARVIS (07:00 Manaus)
5. **Dia 5-7:** Testar com 5 amigos pastores da Lagoinha
   - Feedback real
   - Ajustar voz / tamanho do áudio / horário
6. **Dia 7:** Landing page simples + 1º post vendendo

**Custo de infra adicional:** R$ 0/mês (Cloud API free tier + Fly.io já existente)
**Tempo de dev:** ~25 horas (1 fim de semana + 1 semana à noite)
**ROI esperado:** R$ 1.000/mês no mês 2 (50 ministros × R$ 19)

---

## Próximos passos concretos

Quando Paulo sentar no PC:

1. [ ] **Decidir caminho técnico:** Business API oficial (recomendado) ou Baileys
2. [ ] **Provisionar número** WhatsApp Business (chip separado)
3. [ ] **Setup Meta Business Manager** (1-3 dias aprovação)
4. [ ] **Implementar webhook** (`Brain/actions/whatsapp.py` + rota no dashboard)
5. [ ] **Vertical ministerial primeiro** (devocional diário em áudio)
6. [ ] **Testar com 5 pastores** (rede da Lagoinha Manaus)
7. [ ] **Landing page + 1ª venda** (R$ 19/mês devocional)

---

## Decisões a tomar

- **Número dedicado:** chip pré-pago Vivo ou número fixo?
- **Hospedagem do webhook:** mesmo Fly.io do financas_bot, ou app separado?
- **Modelo de billing:** Asaas / Mercado Pago / Pix manual?
- **Política de privacidade:** LGPD — devocional usa nome do usuário, lembra versículo favorito, etc.

---

## Referências técnicas

- Meta Cloud API docs: https://developers.facebook.com/docs/whatsapp/cloud-api
- bible-api.com (grátis, PT-BR)
- AbíbliaDigital (whatsapp de Bíblia do mercado)
- Voice: já temos `Brain/voice_confirm.py` com Edge TTS AntonioNeural
- Padrão de billing Telegram: `src/billing/` no financas_bot (reaproveitável)

---

## Tags

`#whatsapp` `#mvp-1-semana` `#vertical-ministerial` `#mercado-azul` `#jarvis-v3`