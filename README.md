# J.A.R.V.I.S · Premium Edition 🤖⚡

> Assistente pessoal de IA em PT-BR com dashboard local, voz, memória de projetos, pesquisa web e controle de sistema — **100% offline-friendly**, **sem OpenAI key**, powered by `webscout FreeAI`.

> Fork reimaginado e reconstruído por [@pauleandersonn](https://github.com/pauleandersonn) a partir do projeto original de [AnubhavChaturvedi-GitHub](https://github.com/AnubhavChaturvedi-GitHub/jarvis-ai-assistant).

---

## ✨ O que tem na versão Premium

| Módulo | Status | Descrição |
|---|---|---|
| 🧠 **Brain (LLM)** | ✅ | `webscout.FreeAI` — sem API key, em PT-BR forçado no prompt |
| 🔊 **TTS (voz)** | ✅ | SAPI5 nativo do Windows + WAV renderizado (sem playsound quebrado) |
| 🎙️ **Mic (Web Speech API)** | ✅ | PT-BR contínuo, auto-send 1.5s, modo conversação |
| 💬 **Dashboard FastAPI** | ✅ | UI v2.6 glassmorphism premium em `localhost:8788` |
| 🧠 **Memória persistente** | ✅ | 9 projetos salvos em Markdown, persona de secretário executivo |
| 🔍 **Pesquisa web** | ✅ | DDG + síntese com FreeAI, fontes citadas |
| 🌤️ **Clima** | ✅ | `wttr.in` JSON |
| 🎨 **Geração de imagem** | ✅ | Pollinations.ai (sem key) |
| 🔊 **Volume / 💡 Brilho** | ✅ | pycaw + WMI |
| 🖼️ **System stats** | ✅ | psutil (CPU/RAM/disco/bateria) |
| 🪟 **Automação Windows** | ✅ | pygetwindow, webbrowser, ctypes |

---

## 🚀 Quickstart (Windows)

### 1. Clonar
```powershell
git clone https://github.com/pauleandersonn/jarvis-ai-assistant.git
cd jarvis-ai-assistant
```

### 2. Criar venv e instalar deps
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> ⚠️ **PyAudio** não tem wheel para Python 3.14 ainda. **Solução automática**: o projeto já inclui um shim `pyaudio/__init__.py` baseado em `sounddevice` — funciona out-of-the-box sem VS Build Tools.

### 3. Subir o dashboard
```powershell
$env:JARVIS_DASHBOARD_PORT = 8788
python dashboard.py
```

Abra **http://localhost:8788/** e fale com o JARVIS. 🎙️

---

## 🧠 Arquitetura

```
jarvis-ai-assistant/
├── Brain/
│   ├── brain.py          # cérebro principal — prompt + roteamento
│   ├── memory.py         # leitura/escrita de Memory/*.md
│   └── researcher.py     # busca DDG + síntese com FreeAI
├── TextToSpeech/
│   └── Fast_DF_TTS.py    # SAPI5 com render WAV (evita playsound bug)
├── dashboard.py          # FastAPI server + WebSocket logs
├── dashboard_static/
│   ├── index.html        # UI v2.6
│   ├── style.css         # tokens glassmorphism
│   └── app.js            # state machine + Web Speech API
├── Memory/               # projetos persistentes (markdown)
│   ├── MEMORY.md
│   ├── decisions.md
│   ├── tasks.md
│   └── Projects/
│       ├── indica-ai.md
│       ├── we-love-memory.md
│       └── ...
├── pyaudio/              # shim sobre sounddevice (Py 3.14 friendly)
└── .gitignore
```

---

## 💡 Comandos úteis (no chat)

```
/projeto indica-ai              # ativa contexto do projeto
o que falta decidir?            # JARVIS lê MEMORY.md + decisions.md
pesquise: <termo>               # força modo web search
imagem: <prompt>                # gera imagem com Pollinations
clima                           # wttr.in
volume 70 / brilho 50           # controla Windows
abrir chrome                    # abre app
```

---

## 🎨 UI v2.6 — tokens de design

| Token | Cor |
|---|---|
| `--bg-canvas` | `#05070C` |
| `--primary` | `#5B6CFF` (azul) |
| `--secondary` | `#A855F7` (roxo) |
| `--accent` | `#22D3EE` (ciano) |
| `--pink` | `#EC4899` |
| `--success` | `#10B981` |

Tipografia: **Inter** (body) · **Space Grotesk** (headings) · **JetBrains Mono** (números).

---

## 🛠️ Troubleshooting

| Problema | Solução |
|---|---|
| Dashboard não sobe | Mude a porta: `$env:JARVIS_DASHBOARD_PORT=8800` |
| TTS mudo | SAPI5 exige `pythoncom.CoInitialize` por thread (já tratado) |
| `playsound` trava | Foi removido — usa SAPI5 + `os.startfile(WAV)` |
| Mic não captura | Use Chrome/Edge — Web Speech API não funciona no Firefox |
| PhindSearch quebrado | Substituído por `webscout.FreeAI` |

---

## 📜 Créditos

- **Original**: [AnubhavChaturvedi-GitHub/jarvis-ai-assistant](https://github.com/AnubhavChaturvedi-GitHub/jarvis-ai-assistant)
- **Premium fork, TTS fix, mic, memory, web research, UI v2.6**: [@pauleandersonn](https://github.com/pauleandersonn)
- **LLM**: [webscout](https://github.com/Omar-Aly/webscout) — FreeAI
- **Fonts**: Inter, Space Grotesk, JetBrains Mono (Google Fonts)
- **Ícones**: Material Icons

---

> "Just A Rather Very Intelligent System — só que, agora, em português e com memória." 🇧🇷