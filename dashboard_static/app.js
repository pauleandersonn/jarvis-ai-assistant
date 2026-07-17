// ───────── State ─────────
const state = {
  ws: null,
  statusInterval: null,
  chatInterval: null,
  recognition: null,
  micListening: false,
  continuousMode: false,
  drawerOpen: false,
  activeTab: "chat",
  activeAssistant: "general",
  currentState: "idle",
  lastAnswer: "",
  historyCount: 0,
  speechTimer: null,
  finalTranscriptTimer: null,
  projects: [],
  activeProject: null,
};

const STATE_LABELS = {
  idle: "Pronto para ouvir",
  listening: "Ouvindo",
  thinking: "Pensando",
  speaking: "Respondendo",
};

// ───────── Helpers ─────────
function setState(s) {
  state.currentState = s;
  document.body.classList.remove("state-idle", "state-listening", "state-thinking", "state-speaking");
  document.body.classList.add("state-" + s);
  const label = STATE_LABELS[s] || "";
  document.getElementById("orb-status").textContent = label;
  document.getElementById("state-label").textContent = label;
  // Show interrupt button while speaking.
  const interrupt = document.getElementById("interrupt-btn");
  if (interrupt) {
    interrupt.classList.toggle("visible", s === "speaking");
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function postJson(url, payload, btn) {
  if (btn) {
    btn.disabled = true;
    const original = btn.textContent;
    btn.dataset.label = original;
    btn.textContent = "…";
  }
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return await r.json();
  } catch (err) {
    console.error("POST", url, err);
    return null;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = btn.dataset.label || btn.textContent;
    }
  }
}

function updateClock() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  document.getElementById("topbar-time").textContent =
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

// ───────── WebSocket: live logs ─────────
function connectLogs() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${window.location.host}/ws/logs`;
  state.ws = new WebSocket(url);

  state.ws.onopen = () => {
    document.getElementById("sys-pill").classList.remove("offline");
    document.querySelector("#sys-pill .status-label").textContent = "Online";
  };
  state.ws.onclose = () => {
    document.getElementById("sys-pill").classList.add("offline");
    document.querySelector("#sys-pill .status-label").textContent = "Reconectando…";
    setTimeout(connectLogs, 3000);
  };
  state.ws.onerror = () => {
    document.getElementById("sys-pill").classList.add("offline");
  };
  state.ws.onmessage = (evt) => {
    const logs = document.getElementById("logs");
    if (!logs) return;
    logs.textContent += (logs.textContent ? "\n" : "") + evt.data;
    const lines = logs.textContent.split("\n");
    if (lines.length > 200) logs.textContent = lines.slice(-200).join("\n");
    logs.scrollTop = logs.scrollHeight;
  };
}

// ───────── Status / System polling ─────────
async function refreshSystem() {
  try {
    const r = await fetch("/api/system");
    const s = await r.json();

    // CPU
    document.getElementById("cpu-value").textContent = `${Math.round(s.cpu_percent)}%`;
    document.getElementById("cpu-bar").style.width = `${s.cpu_percent}%`;
    document.getElementById("cpu-bar").classList.toggle("high", s.cpu_percent > 80);

    // RAM
    document.getElementById("ram-value").textContent =
      `${Math.round(s.ram_percent)}% · ${s.ram_used_gb}GB`;
    document.getElementById("ram-bar").style.width = `${s.ram_percent}%`;
    document.getElementById("ram-bar").classList.toggle("high", s.ram_percent > 80);

    // Internet
    document.getElementById("internet-value").innerHTML =
      s.internet_ok
        ? '<span style="color: var(--green)">● Online</span>'
        : '<span style="color: var(--red)">● Offline</span>';

    // Disk
    document.getElementById("disk-value").textContent = `${s.disk_free_gb}GB livre`;

    // Session uptime
    document.getElementById("session-uptime").textContent =
      formatUptime(s.process_uptime_seconds);
    document.getElementById("boot-at").textContent = s.boot_at.split(" ")[1] || "—";
  } catch (err) {
    console.error("refreshSystem:", err);
  }
}

async function refreshIntegrations() {
  try {
    const r = await fetch("/api/integrations");
    const data = await r.json();
    const list = document.getElementById("integration-list");
    list.innerHTML = "";
    for (const it of data.items) {
      const div = document.createElement("div");
      div.className = "integration";
      const online = it.available && it.connected;
      div.innerHTML = `
        <span class="integration-name">${escapeHtml(it.name)}</span>
        <span class="integration-status ${online ? "online" : "offline"}">
          <span class="dot"></span>${online ? "OK" : "—"}
        </span>`;
      list.appendChild(div);
    }
  } catch (err) {
    console.error("refreshIntegrations:", err);
  }
}

function formatUptime(seconds) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

// ───────── Chat history polling ─────────
async function refreshChat() {
  try {
    const r = await fetch("/api/chat?limit=50");
    const data = await r.json();
    const list = document.getElementById("chat-list");
    state.historyCount = (data.messages || []).length;
    document.getElementById("history-count").textContent = state.historyCount;

    if (!data.messages || data.messages.length === 0) {
      list.innerHTML = '<div class="empty">Nenhuma conversa ainda.</div>';
      return;
    }
    list.innerHTML = "";
    for (const m of data.messages) {
      if (m.user) {
        const u = document.createElement("div");
        u.className = "chat-bubble user";
        u.innerHTML = `<div class="who">Você</div>${escapeHtml(m.user)}`;
        list.appendChild(u);
      }
      if (m.ai) {
        const a = document.createElement("div");
        a.className = "chat-bubble ai";
        a.innerHTML = `<div class="who">JARVIS</div>${escapeHtml(m.ai)}`;
        list.appendChild(a);
      }
    }
    list.scrollTop = list.scrollHeight;
  } catch (err) {
    console.error("refreshChat:", err);
  }
}

// ───────── Voice: TTS ─────────
async function speak() {
  const text = document.getElementById("tts-input").value.trim();
  if (!text) return;
  setState("speaking");
  const btn = (typeof event !== "undefined" && event && event.target) || null;
  const data = await postJson("/api/speak", { text }, btn);
  // Server returns the actual WAV duration in seconds — use it.
  const duration = data && data.duration_seconds ? data.duration_seconds : 0;
  const fallback = Math.min(Math.max(text.split(/\s+/).length / 2.5 + 1, 1.5), 30);
  const seconds = duration > 0 ? duration : fallback;
  clearTimeout(state.speechTimer);
  state.speechTimer = setTimeout(() => setState("idle"), seconds * 1000);
  document.getElementById("tts-input").value = "";
}

function interruptSpeech() {
  // The Python TTS is hard to interrupt mid-stream from JS, so we just
  // reset the visual state. The user can also use Stop on log/sound panel.
  clearTimeout(state.speechTimer);
  setState("idle");
}

// ───────── Brain ─────────
async function ask() {
  let text = document.getElementById("ask-input").value.trim();
  if (!text) return;

  // Handle slash commands before sending to the brain.
  if (text.startsWith("/projeto ")) {
    const slug = text.substring("/projeto ".length).trim();
    state.activeProject = slug;
    document.getElementById("active-project-label").textContent =
      `Contexto: ${slug}`;
    renderProjectList();
    document.getElementById("ask-input").value = "";
    // Echo in chat so the user has a record.
    const list = document.getElementById("chat-list");
    const u = document.createElement("div");
    u.className = "chat-bubble user";
    u.innerHTML = `<div class="who">Sistema</div>Contexto alterado para <b>${escapeHtml(slug)}</b>.`;
    list.appendChild(u);
    list.scrollTop = list.scrollHeight;
    return;
  }

  // Immediate user feedback in the chat.
  const list = document.getElementById("chat-list");
  const u = document.createElement("div");
  u.className = "chat-bubble user";
  u.innerHTML = `<div class="who">Você</div>${escapeHtml(text)}`;
  if (list.firstChild && list.firstChild.className === "empty") list.innerHTML = "";
  list.appendChild(u);
  list.scrollTop = list.scrollHeight;

  setState("thinking");
  const btn = (typeof event !== "undefined" && event && event.target) || null;
  await postJson("/api/ask", { text }, btn);
  document.getElementById("ask-input").value = "";

  setTimeout(refreshChatAndSpeak, 5000);
}

async function refreshChatAndSpeak() {
  await refreshChat();
  try {
    const r = await fetch("/api/chat?limit=1");
    const data = await r.json();
    if (data.messages && data.messages[0] && data.messages[0].ai) {
      const lastAi = data.messages[0].ai;
      // Strip "Fontes:\n..." footer from the spoken text — sources are
      // useful on screen but awkward to read aloud.
      const spoken = lastAi.split("\n\nFontes:\n")[0].trim();
      state.lastAnswer = spoken;
      setState("speaking");
      // Ask the backend to render the WAV and tell us its real duration.
      try {
        const sr = await fetch("/api/speak", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: spoken }),
        });
        const sj = await sr.json();
        const duration = sj && sj.duration_seconds ? sj.duration_seconds : 0;
        const fallback = Math.min(Math.max(spoken.split(/\s+/).length / 2.5 + 1, 2), 40);
        const seconds = duration > 0 ? duration : fallback;
        clearTimeout(state.speechTimer);
        state.speechTimer = setTimeout(() => {
          setState("idle");
          if (state.continuousMode) startMic();
        }, seconds * 1000);
        return;
      } catch (e) {
        console.error("speak during chat:", e);
      }
    }
    setState("idle");
  } catch (err) {
    console.error(err);
    setState("idle");
  }
}

// ───────── Weather ─────────
async function checkWeather() {
  const city = document.getElementById("weather-input").value.trim();
  if (!city) return;
  const btn = (typeof event !== "undefined" && event && event.target) || null;
  const result = document.getElementById("weather-result");
  result.className = "info-block active";
  result.textContent = "Buscando…";
  await postJson("/api/weather", { city }, btn);
  setTimeout(async () => {
    const r = await fetch("/api/chat?limit=1").then(r => r.json());
    if (r.messages && r.messages[0] && r.messages[0].ai) {
      result.textContent = r.messages[0].ai;
    }
  }, 4000);
}

// ───────── Research ─────────
async function research() {
  const text = document.getElementById("research-input").value.trim();
  if (!text) return;
  const btn = (typeof event !== "undefined" && event && event.target) || null;
  const result = document.getElementById("research-result");
  result.className = "research-result active";
  result.textContent = `Pesquisando "${text}"… (10-30s)`;
  await postJson("/api/ask", { text }, btn);
  setTimeout(async () => {
    const r = await fetch("/api/chat?limit=1").then(r => r.json());
    if (r.messages && r.messages[0] && r.messages[0].ai) {
      const full = r.messages[0].ai;
      const parts = full.split("\n\nFontes:\n");
      const answer = parts[0];
      let sourcesHtml = "";
      if (parts[1]) {
        const links = parts[1].split("\n").map(line => {
          const m = line.match(/\[(\d+)\]\s+(.+?):\s+(https?:\/\/\S+)/);
          if (!m) return "";
          return `<a href="${escapeHtml(m[3])}" target="_blank" rel="noopener">[${m[1]}] ${escapeHtml(m[2])}</a>`;
        }).filter(Boolean).join("");
        sourcesHtml = `<div class="sources">${links}</div>`;
      }
      result.innerHTML = escapeHtml(answer) + sourcesHtml;
    }
  }, 12000);
  document.getElementById("research-input").value = "";
}

// ───────── Image ─────────
async function generateImage() {
  const prompt = document.getElementById("image-input").value.trim();
  if (!prompt) return;
  const btn = (typeof event !== "undefined" && event && event.target) || null;
  const result = document.getElementById("image-result");
  result.textContent = "Gerando imagem…";
  await postJson("/api/image", { prompt }, btn);
  result.textContent = "Pedido enviado. Veja em TextToImage/Generated/ na pasta do projeto.";
  document.getElementById("image-input").value = "";
}

// ───────── Volume / Brightness ─────────
async function setVolume() {
  const v = parseInt(document.getElementById("volume-slider").value, 10);
  await postJson("/api/volume", { level: v });
}
async function setBrightness() {
  const v = parseInt(document.getElementById("brightness-slider").value, 10);
  await postJson("/api/brightness", { level: v });
}

// ───────── Chat controls ─────────
async function clearChat() {
  if (!confirm("Limpar histórico de conversas?")) return;
  await fetch("/api/clear-chat", { method: "POST" });
  refreshChat();
}

// ───────── Speech recognition (Web Speech API) ─────────
function initSpeechRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    const hint = document.getElementById("voice-hint");
    if (hint) hint.textContent = "Reconhecimento de voz não suportado neste navegador. Use Chrome ou Edge.";
    const btn = document.getElementById("mic-btn");
    if (btn) btn.disabled = true;
    return null;
  }

  const recognition = new SR();
  recognition.lang = "pt-BR";
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    state.micListening = true;
    setState("listening");
    const input = document.getElementById("ask-input");
    if (input) input.placeholder = "Fale agora…";
  };

  recognition.onresult = (event) => {
    let interim = "", final = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const t = event.results[i][0].transcript;
      if (event.results[i].isFinal) final += t;
      else interim += t;
    }
    const input = document.getElementById("ask-input");
    if (input) input.value = (final || interim).trim();

    if (final.trim()) {
      clearTimeout(state.finalTranscriptTimer);
      state.finalTranscriptTimer = setTimeout(() => {
        if (state.micListening) {
          try { recognition.stop(); } catch (e) {}
        }
        ask();
      }, 1500);
    }
  };

  recognition.onerror = (e) => {
    console.error("recognition error:", e.error);
    setState("idle");
    state.micListening = false;
  };

  recognition.onend = () => {
    state.micListening = false;
    const input = document.getElementById("ask-input");
    if (input) input.placeholder = "Fale com o JARVIS ou digite aqui…";
    if (state.currentState === "listening") setState("idle");
  };

  return recognition;
}

function startMic() {
  if (!state.recognition) {
    state.recognition = initSpeechRecognition();
    if (!state.recognition) return;
  }
  if (state.micListening) return;
  const input = document.getElementById("ask-input");
  if (input) input.value = "";
  try {
    state.recognition.start();
  } catch (e) {
    console.error("start:", e);
  }
}

function stopMic() {
  if (state.recognition && state.micListening) {
    try { state.recognition.stop(); } catch (e) {}
  }
}

function toggleMic() {
  if (!state.recognition) {
    state.recognition = initSpeechRecognition();
    if (!state.recognition) return;
  }
  if (state.micListening) {
    stopMic();
  } else {
    startMic();
  }
}

// ───────── Drawer ─────────
function toggleDrawer() {
  state.drawerOpen = !state.drawerOpen;
  document.getElementById("drawer").classList.toggle("open", state.drawerOpen);
  document.getElementById("drawer-toggle").classList.toggle("open", state.drawerOpen);
}

function switchTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".drawer-tab").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  document.querySelectorAll(".drawer-panel").forEach(p => {
    p.classList.toggle("active", p.id === "panel-" + tab);
  });
  if (tab === "projects") refreshProjects();
}

// ───────── Projects (memory) ─────────
async function refreshProjects() {
  try {
    const r = await fetch("/api/memory/projects");
    const data = await r.json();
    state.projects = data.projects || [];
    renderProjectList();
  } catch (err) {
    console.error("refreshProjects:", err);
  }
}

function renderProjectList() {
  const list = document.getElementById("projects-list");
  if (!state.projects.length) {
    list.innerHTML = '<div class="loading-mini">Nenhum projeto encontrado.</div>';
    return;
  }
  list.innerHTML = "";
  for (const p of state.projects) {
    const btn = document.createElement("button");
    btn.className = "project-item" + (state.activeProject === p.slug ? " active" : "");
    btn.textContent = p.name;
    btn.onclick = () => selectProject(p.slug);
    list.appendChild(btn);
  }
}

async function selectProject(slug) {
  state.activeProject = slug;
  renderProjectList();
  document.getElementById("active-project-label").textContent =
    `Contexto: ${slug}`;
  try {
    const r = await fetch(`/api/memory/project/${encodeURIComponent(slug)}`);
    const data = await r.json();
    const detail = document.getElementById("projects-detail");
    if (data.content) {
      // Render as preformatted text — markdown rendering would need
      // a library; keeping it simple here.
      detail.textContent = data.content;
    } else {
      detail.textContent = "(vazio)";
    }
  } catch (err) {
    console.error("selectProject:", err);
  }
}

async function addToActiveProject() {
  if (!state.activeProject) {
    alert("Selecione um projeto primeiro.");
    return;
  }
  const section = document.getElementById("proj-section").value.trim();
  const addition = document.getElementById("proj-addition").value.trim();
  if (!section || !addition) return;

  await postJson("/api/memory/project/update", {
    slug: state.activeProject,
    section,
    addition: `- ${addition}  _(${new Date().toLocaleString("pt-BR")})_`,
  });
  document.getElementById("proj-section").value = "";
  document.getElementById("proj-addition").value = "";
  selectProject(state.activeProject); // refresh detail
}

// ───────── Assistants (left sidebar) ─────────
function switchAssistant(name) {
  state.activeAssistant = name;
  document.querySelectorAll(".assistant").forEach(b => {
    b.classList.toggle("active", b.dataset.assistant === name);
  });
  // Show feedback via state label
  const labels = {
    general: "Assistente Geral",
    finance: "Modo Finanças",
    automation: "Modo Automação",
    search: "Modo Pesquisa",
    marketing: "Modo Marketing",
    code: "Modo Programação",
    church: "Modo Igreja",
  };
  const hint = document.getElementById("voice-hint");
  if (hint) hint.textContent = labels[name] || labels.general;
}

// ───────── Slider sync ─────────
function bindSlider(id, labelId) {
  const s = document.getElementById(id);
  const l = document.getElementById(labelId);
  if (!s || !l) return;
  s.addEventListener("input", () => { l.textContent = `${s.value}%`; });
}

// ───────── Boot ─────────
document.addEventListener("DOMContentLoaded", () => {
  // Sliders
  bindSlider("volume-slider", "volume-label");
  bindSlider("brightness-slider", "brightness-label");

  // Tabs
  document.querySelectorAll(".drawer-tab").forEach(b => {
    b.addEventListener("click", () => switchTab(b.dataset.tab));
  });

  // Assistants
  document.querySelectorAll(".assistant").forEach(b => {
    b.addEventListener("click", () => switchAssistant(b.dataset.assistant));
  });

  // Enter key on inputs
  const handlers = {
    "ask-input": () => ask(),
    "tts-input": () => speak(),
    "weather-input": () => checkWeather(),
    "research-input": () => research(),
    "image-input": () => generateImage(),
  };
  for (const [id, fn] of Object.entries(handlers)) {
    const el = document.getElementById(id);
    if (el) el.addEventListener("keydown", e => { if (e.key === "Enter") fn(); });
  }
});

connectLogs();
refreshSystem();
refreshIntegrations();
refreshChat();
setState("idle");
updateClock();
setInterval(updateClock, 1000);
setInterval(refreshSystem, 3000);
setInterval(refreshIntegrations, 30000);
setInterval(refreshChat, 5000);