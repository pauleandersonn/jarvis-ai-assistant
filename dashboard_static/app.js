// ───────── State ─────────
// JARVIS_DEBUG = false em produção. Liga no console do navegador:
//   window.JARVIS_DEBUG = true; location.reload();
// para ver logs de mic/reconhecimento durante desenvolvimento.
window.JARVIS_DEBUG = window.JARVIS_DEBUG || false;

// ───────── Mute / voz toggle ─────────
// Permite ao usuário ligar/desligar a voz do JARVIS sem interromper
// o atendimento por texto. Padrão: voz LIGADA (false = mudo desligado).
// Persistência em localStorage para sobreviver a recarregamentos.
const MUTE_STORAGE_KEY = "jarvis.muted";
function muteGet() {
  try {
    const v = localStorage.getItem(MUTE_STORAGE_KEY);
    // Default = false (voz ligada). Só fica mudo se o usuário tiver setado "1" alguma vez.
    return v === "1";
  } catch (e) {
    return false;
  }
}
function muteSet(v) {
  try { localStorage.setItem(MUTE_STORAGE_KEY, v ? "1" : "0"); } catch (e) {}
}
function muteApplyClass() {
  const muted = muteGet();
  document.body.classList.toggle("jarvis-muted", muted);
  // Compat com código legado que checa window.JARVIS_MUTED
  window.JARVIS_MUTED = muted;
  return muted;
}
function muteToggle() {
  const nowMuted = !muteGet();
  muteSet(nowMuted);
  muteApplyClass();
  // Se o usuário acabou de LIGAR a voz (nowMuted=false) e o boot
  // greeting ainda não falou, deixa quieto. Se DESLIGOU, para fala em curso.
  if (nowMuted) ttsStop();
  if (window.JARVIS_DEBUG) console.log("[mute] agora mudo?", nowMuted);
  return nowMuted;
}
// Aplica estado salvo o quanto antes (antes de qualquer fala)
muteApplyClass();

// ───────── Voice hint helpers ─────────
// Mensagem curta mostrada dentro do card central, atualizada durante
// a fase de síntese e durante a reprodução do WAV.
function showVoiceHint(msg) {
  const el = document.getElementById("voice-hint");
  if (el) el.textContent = msg;
}
function hideVoiceHint() {
  const el = document.getElementById("voice-hint");
  if (el) el.textContent = "";
}

// Bind do clique no botão da topbar
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("mute-toggle");
  if (btn) {
    btn.addEventListener("click", () => {
      muteToggle();
    });
    btn.setAttribute("aria-pressed", muteGet() ? "true" : "false");
  }
});
// Se o DOM já estiver pronto (carregamento async), bind direto também
(function bindMuteNow() {
  const btn = document.getElementById("mute-toggle");
  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      const m = muteToggle();
      btn.setAttribute("aria-pressed", m ? "true" : "false");
    });
  }
})();

// ───────── Geração das 24 curvas orgânicas (Layer 2 do orb) ─────────
// Padrão: linhas bezier tangenciais que se cruzam formando "fibras entrelaçadas",
// evocando meridianos de uma esfera 3D. Rotação contínua -15deg → 60s clockwise.
function buildOrbCurves() {
  const svg = document.getElementById("orb-curves");
  if (!svg) return;
  const cx = 210, cy = 210;
  const colors = ["#22D3EE", "#5B6CFF", "#A855F7", "#7C3AED", "#EC4899"];
  const NS = "http://www.w3.org/2000/svg";
  const N = 24;

  for (let i = 0; i < N; i++) {
    // Cada curva é um meridiano: começa em y=10, vai ao outro lado do círculo,
    // passando por um ponto de controle deslocado horizontalmente.
    const angle = (i / N) * Math.PI * 2;
    const wobble = 30 + Math.random() * 60;
    const sideSign = Math.random() < 0.5 ? -1 : 1;

    const startX = cx + Math.cos(angle) * 200;
    const startY = cy + Math.sin(angle) * 200;
    const endX = cx - Math.cos(angle) * 200;
    const endY = cy - Math.sin(angle) * 200;
    // Pontos de controle bezier: empurram a curva para um lado e o outro,
    // criando o efeito de "fibra" passando pelo centro.
    const cp1X = cx + sideSign * (wobble + 80);
    const cp1Y = cy + Math.sin(angle) * 60;
    const cp2X = cx - sideSign * (wobble + 80);
    const cp2Y = cy - Math.sin(angle) * 60;

    const path = document.createElementNS(NS, "path");
    path.setAttribute(
      "d",
      `M ${startX} ${startY} C ${cp1X} ${cp1Y}, ${cp2X} ${cp2Y}, ${endX} ${endY}`
    );
    path.setAttribute("stroke", colors[i % colors.length]);
    path.setAttribute("stroke-width", 0.8 + Math.random() * 0.7);
    path.setAttribute("fill", "none");
    path.setAttribute("opacity", 0.5 + Math.random() * 0.4);
    path.setAttribute("stroke-linecap", "round");
    path.classList.add("orb-curve");
    svg.appendChild(path);
  }
}

// ───────── Particle orbit (Layer 4) ─────────
// Mantém as 6 partículas girando lentamente ao redor do orb pra dar
// sensação de órbita. Complementa o twinkle de brilho já no CSS.
function buildOrbParticles() {
  const wrap = document.querySelector(".orb-particles");
  if (!wrap) return;
  wrap.style.transformOrigin = "50% 50%";
  wrap.classList.add("orb-particles-rotate");
}

const state = {
  ws: null,
  statusInterval: null,
  chatInterval: null,
  recognition: null,
  micListening: false,
  // userWantsMic = true quando o usuário CLICOU pra ligar o mic.
  // Se o engine termina sozinho (no-speech, network), reiniciamos.
  // Se for false (usuário clicou pra parar), não reiniciamos.
  userWantsMic: false,
  micRestartTimer: null,
  finalTranscriptTimer: null,
  continuousMode: false,
  drawerOpen: false,
  activeTab: "chat",
  activeAssistant: "general",
  currentState: "idle",
  lastAnswer: "",
  historyCount: 0,
  speechTimer: null,
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

// Chrome/Edge/Firefox gate audio.play() behind a user gesture. We expose
// an "Ativar audio" button so the user grants permission explicitly
// instead of the browser silently swallowing the first audio.play().
let audioUnlocked = false;

function enableAudio() {
  audioUnlocked = true;
  const label = document.getElementById("enable-audio-label");
  const btn = document.getElementById("enable-audio-btn");
  if (label) label.textContent = "Audio ativo";
  if (btn) btn.classList.add("audio-active");
  try {
    // ~50ms of silence as a valid WAV blob. Play it muted so the browser
    // marks the document as user-activated for future audio.play() calls.
    const silent = new Uint8Array([
      0x52, 0x49, 0x46, 0x46, 0x24, 0x00, 0x00, 0x00, 0x57, 0x41, 0x56, 0x45,
      0x66, 0x6d, 0x74, 0x20, 0x10, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00,
      0x44, 0xac, 0x00, 0x00, 0x88, 0x58, 0x01, 0x00, 0x02, 0x00, 0x10, 0x00,
      0x64, 0x61, 0x74, 0x61, 0x00, 0x00, 0x00, 0x00,
    ]);
    const blob = new Blob([silent], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    const a = new Audio(url);
    a.volume = 0;
    a.muted = true;
    const p = a.play();
    if (p && typeof p.then === "function") {
      p.then(() => URL.revokeObjectURL(url)).catch(() => URL.revokeObjectURL(url));
    } else {
      URL.revokeObjectURL(url);
    }
  } catch (e) {
    console.warn("enableAudio:", e);
  }
  if (window.JARVIS_DEBUG) console.log("[audio] unlocked by user gesture");
}

async function fetchTtsBlob(text) {
  // Server returns raw WAV bytes (Content-Type: audio/wav) + X-Duration-Seconds
  // header. We blob() it client-side and play with HTMLAudioElement.
  const r = await fetch("/api/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error("speak HTTP " + r.status);
  const blob = await r.blob();
  const durHeader = r.headers.get("X-Duration-Seconds");
  const duration = durHeader ? parseFloat(durHeader) : 0;
  return { blob, duration };
}

function playBlob(blob, fallbackSeconds, onEnd) {
  // Play a Blob via HTMLAudioElement. Falls back to timer if browser
  // refuses (no user gesture / autoplay policy).
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.volume = 1.0;
  audio.muted = false;
  audio.preload = "auto";

  const cleanup = () => {
    try { URL.revokeObjectURL(url); } catch (e) { /* noop */ }
    if (state.currentAudio === audio) state.currentAudio = null;
  };

  audio.onended = () => {
    clearTimeout(state.speechTimer);
    cleanup();
    if (typeof onEnd === "function") onEnd();
  };
  audio.onerror = (e) => {
    clearTimeout(state.speechTimer);
    console.error("audio error:", e);
    cleanup();
    if (typeof onEnd === "function") onEnd();
  };

  state.currentAudio = audio;
  const p = audio.play();
  if (p && typeof p.then === "function") {
    p.catch((err) => {
      clearTimeout(state.speechTimer);
      console.error("audio.play() rejected:", err);
      // Autoplay policy: usuario precisa clicar em "Ativar audio".
      const hint = document.getElementById("voice-hint");
      if (hint) {
        hint.textContent =
          "⚠ Clique em 'Ativar audio' (acima do microfone) para liberar o som do navegador.";
      }
      cleanup();
      if (typeof onEnd === "function") onEnd();
    });
  }

  // Safety timer: if onended never fires (corrupted WAV), still finish.
  clearTimeout(state.speechTimer);
  state.speechTimer = setTimeout(() => {
    if (state.currentAudio === audio) {
      try { audio.pause(); } catch (e) { /* noop */ }
    }
    cleanup();
    if (typeof onEnd === "function") onEnd();
  }, (fallbackSeconds + 3) * 1000);
}

async function speak() {
  const text = document.getElementById("tts-input").value.trim();
  if (!text) return;
  document.getElementById("tts-input").value = "";
  await speakArbitrary(text);
}

// =====================================================================
// TTS via speechSynthesis (API nativa do Chrome/Edge)
// Vantagens vs SAPI5 do Windows:
//   - Vozes PT-BR naturais (Microsoft Maria, Google pt-BR)
//   - Sem gerar WAV temporario
//   - Sem /api/speak round-trip (instantaneo)
//   - Funciona offline (vozes Microsoft sao locais)
// =====================================================================

const TTS = {
  voice: null,          // voice PT-BR selecionada
  voicesLoaded: false,
  currentUtterance: null,
};

function ttsSelectVoice() {
  if (!window.speechSynthesis) return null;
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;

  // Prioridade: Google pt-BR > Microsoft Maria > Microsoft Daniel > qualquer pt-BR > qualquer pt
  TTS.voice =
    voices.find(v => v.lang === "pt-BR" && /google/i.test(v.name)) ||
    voices.find(v => v.lang === "pt-BR" && /maria/i.test(v.name)) ||
    voices.find(v => v.lang === "pt-BR" && /female/i.test(v.name)) ||
    voices.find(v => v.lang === "pt-BR") ||
    voices.find(v => v.lang.startsWith("pt")) ||
    voices[0];
  return TTS.voice;
}

// Carrega voices (Chrome carrega async, precisamos esperar)
if (window.speechSynthesis) {
  ttsSelectVoice();
  window.speechSynthesis.onvoiceschanged = () => {
    ttsSelectVoice();
    TTS.voicesLoaded = true;
    if (window.JARVIS_DEBUG) console.log("[tts] voices loaded:", window.speechSynthesis.getVoices().length);
  };
  // Forca carregar inicial tambem (alguns browsers disparam onvoiceschanged ja populado)
  setTimeout(() => { ttsSelectVoice(); TTS.voicesLoaded = true; }, 100);
}

function ttsStop() {
  if (!window.speechSynthesis) return;
  try { window.speechSynthesis.cancel(); } catch (e) {}
  TTS.currentUtterance = null;
}

async function ttsSpeak(text) {
  if (!text) return { ok: false, reason: "empty" };
  if (muteGet()) {
    if (window.JARVIS_DEBUG) console.log("[tts] suprimido (mudo):", text.slice(0, 80));
    return { ok: false, reason: "muted" };
  }

  // Caminho primário: SAPI5 do Windows. O servidor APENAS gera o WAV
  // (audio/wav bytes); a REPRODUÇÃO acontece aqui via HTMLAudioElement.
  // Garante a MESMA voz em Chrome, Edge, Firefox, Opera, sem depender
  // de speechSynthesis (que tem quirks: voices sumindo, utterance truncado,
  // callbacks que nao disparam em texto longo).
  return await ttsSpeakViaBackend(text);
}

// Caminho primário: SAPI5 do Windows via /api/speak.
// Servidor retorna audio/wav em bytes; frontend toca via HTMLAudioElement.
// Suporta qualquer browser moderno (Chrome, Edge, Firefox, Opera).
async function ttsSpeakViaBackend(text) {
  if (muteGet()) {
    if (window.JARVIS_DEBUG) console.log("[tts-backend] suprimido (mudo)");
    return { ok: false, reason: "muted" };
  }

  // Marca estado ANTES de qualquer rede: usuario precisa de feedback
  // imediato enquanto o servidor sintetiza o WAV.
  setState("thinking");
  if (typeof showVoiceHint === "function") {
    showVoiceHint("Gerando voz...");
  }

  let resp, blob, dur;
  try {
    resp = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!resp.ok) {
      const detail = await safeReadJson(resp);
      throw new Error(
        "speak HTTP " + resp.status + (detail && detail.reason ? " - " + detail.reason : "")
      );
    }
    // Verifica que e audio/wav
    const ctype = resp.headers.get("Content-Type") || "";
    if (!ctype.startsWith("audio/")) {
      throw new Error("backend devolveu content-type errado: " + ctype);
    }
    blob = await resp.blob();
    dur = parseFloat(resp.headers.get("X-Jarvis-Duration") || "0") || 0;
  } catch (e) {
    console.error("[tts-backend] erro na requisicao:", e);
    return { ok: false, reason: e.message || "fetch_fail" };
  }

  // WAV chegou. Agora toca no navegador.
  setState("speaking");
  if (typeof showVoiceHint === "function") {
    showVoiceHint("Respondendo...");
  }

  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.volume = 1.0;
    audio.preload = "auto";

    const cleanup = () => {
      try { URL.revokeObjectURL(url); } catch (err) { /* noop */ }
      if (state.currentAudio === audio) state.currentAudio = null;
      clearTimeout(state.speechTimer);
    };

    audio.onended = () => {
      cleanup();
      if (typeof hideVoiceHint === "function") hideVoiceHint();
      setState("idle");
      resolve({ ok: true, engine: "sapi5", duration: dur });
    };
    audio.onerror = (ev) => {
      console.error("[tts-backend] audio error:", ev);
      cleanup();
      setState("idle");
      resolve({ ok: false, reason: "audio_play_fail" });
    };

    state.currentAudio = audio;
    const p = audio.play();
    if (p && typeof p.then === "function") {
      p.catch((err) => {
        console.error("[tts-backend] audio.play() rejeitado:", err);
        // Autoplay policy: precisa de gesture (clique do usuario).
        const hint = document.getElementById("voice-hint");
        if (hint) {
          hint.textContent =
            "⚠ Clique em 'Ativar audio' (acima do microfone) para liberar o som do navegador.";
        }
        cleanup();
        setState("idle");
        resolve({ ok: false, reason: "play_blocked" });
      });
    }

    // Safety timer: se audio.onended nunca dispara (WAV corrompido),
    // ainda assim finaliza o estado depois de dur + 3s.
    clearTimeout(state.speechTimer);
    state.speechTimer = setTimeout(() => {
      if (state.currentAudio === audio) {
        try { audio.pause(); } catch (e) { /* noop */ }
      }
      cleanup();
      setState("idle");
      resolve({ ok: false, reason: "timeout" });
    }, (dur + 3) * 1000);
  });
}

async function safeReadJson(resp) {
  try { return await resp.json(); } catch { return null; }
}

async function speakArbitrary(text) {
  if (!text) return;
  setState("speaking");

  const result = await ttsSpeak(text);

  if (window.JARVIS_DEBUG) console.log("[tts] result:", result);

  setState("idle");
  if (state.continuousMode) startMic();
}

function interruptSpeech() {
  // Hard-stop current audio + reset visual state.
  if (state.currentAudio) {
    try { state.currentAudio.pause(); } catch (e) { /* noop */ }
    state.currentAudio = null;
  }
  clearTimeout(state.speechTimer);
  ttsStop();
  setState("idle");
}

// Para QUALQUER fala em curso (browser + utterance pendente).
// Não bloqueia falas futuras — só interrompe a atual.
function ttsStop() {
  try {
    if (TTS && TTS.currentUtterance) {
      try { TTS.currentUtterance.onend = null; TTS.currentUtterance.onerror = null; } catch (e) {}
      TTS.currentUtterance = null;
    }
    if (window.speechSynthesis && window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel();
    }
  } catch (e) {
    // speechSynthesis pode não existir em alguns browsers; ignora
  }
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

  // Snapshot: numero de mensagens e ultimo texto AI ANTES do brain responder.
  // Quando o poll detectar nova AI line, dispara TTS. Sem isso, o JS lia
  // messages[0] (a mais antiga) e perdia a resposta recem-chegada.
  const before = await fetchChatSnapshot();
  await waitForNewAiAndSpeak(before);
}

async function fetchChatSnapshot() {
  try {
    const r = await fetch("/api/chat?limit=1");
    const data = await r.json();
    const last = (data.messages && data.messages[data.messages.length - 1]) || null;
    return {
      count: (data.messages || []).length,
      lastAi: last && last.ai ? last.ai : "",
    };
  } catch (e) {
    return { count: 0, lastAi: "" };
  }
}

async function waitForNewAiAndSpeak(before, maxMs = 30000, intervalMs = 700) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    await new Promise(r => setTimeout(r, intervalMs));
    const now = await fetchChatSnapshot();
    // Critério: nova AI line diferente da anterior.
    if (now.lastAi && now.lastAi !== before.lastAi) {
      await refreshChat();
      const spoken = now.lastAi.split("\n\nFontes:\n")[0].trim();
      if (!spoken) {
        setState("idle");
        return;
      }
      state.lastAnswer = spoken;
      setState("speaking");
      try {
        const { blob, duration } = await fetchTtsBlob(spoken);
        const fallback = Math.min(Math.max(spoken.split(/\s+/).length / 2.5 + 1, 2), 40);
        const seconds = duration > 0 ? duration : fallback;
        playBlob(blob, seconds, () => {
          setState("idle");
          if (state.continuousMode) startMic();
        });
      } catch (e) {
        console.error("speak during chat:", e);
        setState("idle");
      }
      return;
    }
  }
  // Timeout: brain nao respondeu a tempo. Sai do estado thinking sem falar.
  console.warn("waitForNewAiAndSpeak: timeout esperando nova AI line");
  setState("idle");
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
    const last = r.messages && r.messages[r.messages.length - 1];
    if (last && last.ai) {
      result.textContent = last.ai;
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
    const last = r.messages && r.messages[r.messages.length - 1];
    if (last && last.ai) {
      const full = last.ai;
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
// Estado do mic: queremos distinguir "usuário clicou pra parar" de
// "engine terminou sozinho por timeout (no-speech)".
// userWantsMic=true significa: o usuário QUER o mic aberto. Se o engine
// terminar sozinho (onend), reiniciamos. Se o usuário clicou pra parar,
// não reiniciamos.
const SR_ERR_FATAL = new Set(["not-allowed", "service-not-allowed", "audio-capture"]);
const SR_ERR_RECOVERABLE = new Set(["no-speech", "aborted", "network"]);
const SR_RETRY_DELAY_MS = 600;

function initSpeechRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    const hint = document.getElementById("voice-hint");
    if (hint) hint.textContent = "Reconhecimento de voz não suportado neste navegador. Use Chrome ou Edge.";
    const btn = document.getElementById("mic-btn");
    if (btn) btn.disabled = true;
    if (window.JARVIS_DEBUG) console.warn("[mic] SpeechRecognition indisponível");
    return null;
  }

  const recognition = new SR();
  recognition.lang = "pt-BR";
  // Modo conversação: continuous=true deixa o engine aberto entre utterances.
  // O auto-restart é controlado por userWantsMic, não pelo engine.
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    state.micListening = true;
    setState("listening");
    const input = document.getElementById("ask-input");
    if (input) input.placeholder = "Fale agora…";
    if (window.JARVIS_DEBUG) console.log("[mic] onstart");
  };

  recognition.onresult = (event) => {
    let interim = "", final = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const t = event.results[i][0].transcript;
      if (event.results[i].isFinal) final += t;
      else interim += t;
    }
    const text = (final || interim).trim();
    const input = document.getElementById("ask-input");
    if (input) input.value = text;

    if (final.trim()) {
      // Reset do timer de auto-send a cada utterance final.
      clearTimeout(state.finalTranscriptTimer);
      state.finalTranscriptTimer = setTimeout(() => {
        // Só dispara ask() se o usuário deixou texto válido.
        const current = document.getElementById("ask-input");
        if (current && current.value.trim() && state.userWantsMic) {
          if (window.JARVIS_DEBUG) console.log("[mic] auto-send (1.5s silence)");
          // stop() vai disparar onend, que por sua vez respeita userWantsMic
          // e decide se reinicia. Aqui só pedimos pra parar de ouvir.
          try { recognition.stop(); } catch (e) { /* noop */ }
          ask();
        }
      }, 1500);
    }
  };

  recognition.onerror = (e) => {
    const err = e.error || "unknown";
    state.micListening = false;

    // Mensagens amigáveis no UI
    const hint = document.getElementById("voice-hint");
    if (err === "not-allowed" || err === "service-not-allowed") {
      if (hint) hint.textContent = "Permissão de microfone negada. Habilite nas configurações do navegador.";
      state.userWantsMic = false;
      if (window.JARVIS_DEBUG) console.error("[mic] permissão negada:", err);
    } else if (err === "audio-capture") {
      if (hint) hint.textContent = "Nenhum microfone detectado. Conecte um microfone e tente de novo.";
      state.userWantsMic = false;
      if (window.JARVIS_DEBUG) console.error("[mic] sem captura de áudio:", err);
    } else if (SR_ERR_RECOVERABLE.has(err)) {
      // no-speech, aborted, network — não é erro fatal, só não ouviu nada.
      // onend vai disparar e o auto-restart cuida.
      if (window.JARVIS_DEBUG) console.warn("[mic] recoverable:", err);
    } else {
      if (window.JARVIS_DEBUG) console.warn("[mic] erro desconhecido:", err);
    }

    if (state.userWantsMic && SR_ERR_FATAL.has(err)) {
      // Erro fatal (sem permissão / sem mic): cancela a intenção do usuário.
      state.userWantsMic = false;
    }

    setState("idle");
  };

  recognition.onend = () => {
    state.micListening = false;
    const input = document.getElementById("ask-input");
    if (input) input.placeholder = "Fale com o JARVIS ou digite aqui…";
    if (window.JARVIS_DEBUG) console.log("[mic] onend, userWantsMic=" + state.userWantsMic);

    // Auto-restart inteligente: só reinicia se o usuário QUER o mic aberto
    // e o último erro não foi fatal.
    if (state.userWantsMic && state.recognition === recognition) {
      clearTimeout(state.micRestartTimer);
      state.micRestartTimer = setTimeout(() => {
        if (state.userWantsMic && !state.micListening) {
          try { recognition.start(); }
          catch (e) {
            // InvalidStateError: já está rodando — ignora.
            if (window.JARVIS_DEBUG) console.warn("[mic] restart falhou:", e.name);
          }
        }
      }, SR_RETRY_DELAY_MS);
    }
    if (state.currentState === "listening") setState("idle");
  };

  return recognition;
}

function startMic() {
  if (!state.recognition) {
    state.recognition = initSpeechRecognition();
    if (!state.recognition) return;
  }
  state.userWantsMic = true;
  if (state.micListening) return;
  const input = document.getElementById("ask-input");
  if (input) input.value = "";
  try {
    state.recognition.start();
  } catch (e) {
    // InvalidStateError significa que já está rodando — não é erro real.
    if (e && e.name !== "InvalidStateError") {
      if (window.JARVIS_DEBUG) console.error("[mic] start falhou:", e);
    }
  }
}

function stopMic() {
  // Usuário pediu pra parar — desliga auto-restart.
  state.userWantsMic = false;
  clearTimeout(state.micRestartTimer);
  clearTimeout(state.finalTranscriptTimer);
  if (state.recognition && state.micListening) {
    try { state.recognition.stop(); } catch (e) { /* noop */ }
  }
}

function toggleMic() {
  if (!state.recognition) {
    state.recognition = initSpeechRecognition();
    if (!state.recognition) return;
  }
  // toggleMic alterna intenção do usuário, não só estado do engine.
  if (state.userWantsMic && state.micListening) {
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

// Log de boot em dev
if (window.JARVIS_DEBUG) {
  console.log("[jarvis] dashboard inicializado, SpeechRecognition=" +
    ((window.SpeechRecognition || window.webkitSpeechRecognition) ? "ok" : "indisponível"));
}

// Build do orb (curvas + partículas)
buildOrbCurves();
buildOrbParticles();

// ───────── Boot greeting ─────────
// Pede uma saudação contextual ao backend (/api/greeting) e:
//   1. Mostra no campo de input como placeholder inicial
//   2. Atualiza o status do orb (visual)
//   3. Fala via TTS (se nao bloqueado por preferencia do usuario)
async function bootGreeting() {
  try {
    const r = await fetch("/api/greeting");
    if (!r.ok) return;
    const g = await r.json();
    if (!g.text) return;

    // 1. placeholder inicial no input
    const input = document.getElementById("ask-input");
    if (input) input.placeholder = g.text;

    // 2. atualiza status do orb por 8 segundos
    const status = document.getElementById("orb-status");
    if (status) {
      const original = status.textContent;
      status.textContent = g.text;
      setTimeout(() => { status.textContent = original; }, 8000);
    }

    // 3. fala via TTS no boot SOMENTE se o usuario ja desbloqueou audio.
    //    Sem gesture previo, Chrome bloqueia audio.play() e a gente
    //    fica mudo. O usuario clica "Ativar audio" primeiro.
    if (!window.JARVIS_MUTED && audioUnlocked) {
      speakArbitrary(g.text).catch(e => {
        if (window.JARVIS_DEBUG) console.warn("[greeting] speak falhou:", e);
      });
    }
  } catch (e) {
    if (window.JARVIS_DEBUG) console.warn("[greeting] falhou:", e);
  }
}
bootGreeting();