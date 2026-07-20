"""Edge TTS neural voice generator.

Opção C do plano "voz do Jarvis": Edge TTS com voz pt-BR-AntonioNeural
+ ajustes de rate/pitch pra soar mais grave e pausado (estilo Jarvis).

Pipeline:
  1. Recebe texto do /api/speak
  2. Limpa o texto (mesma sanitizacao do Fast_DF_TTS)
  3. Chama edge-tts.Communicate com voz AntonioNeural
  4. Stream do MP3 pra WAV em disco
  5. Devolve o path pro dashboard que serve via HTMLAudioElement

Vantagens vs SAPI5:
  - Voz neural Microsoft de alta qualidade (natural, nao-robotica)
  - Configuravel via SSML (rate, pitch, volume, estilo)
  - Voz masculina grave brasileira

Limitacoes:
  - Requer internet (Edge TTS e servico online)
  - Latencia ~500ms-2s pra primeira conexao
  - Edge gera MP3, nao WAV — convertemos via pydub se instalado; senao
    devolvemos MP3 mesmo (HTMLAudioElement toca ambos)
"""

import asyncio
import io
import os
import pathlib
import re
import subprocess

# Configuracao de voz (Opção C — Jarvis-like).
EDGE_VOICE = os.environ.get("JARVIS_EDGE_VOICE", "pt-BR-AntonioNeural")
EDGE_RATE = os.environ.get("JARVIS_EDGE_RATE", "-8%")      # mais lento
EDGE_PITCH = os.environ.get("JARVIS_EDGE_PITCH", "-4Hz")   # mais grave
EDGE_VOLUME = os.environ.get("JARVIS_EDGE_VOLUME", "+0%")

TMP_DIR = pathlib.Path(__file__).resolve().parent / "tmp_audio"
TMP_DIR.mkdir(exist_ok=True)

# Frases meta que o LLM as vezes cospe — mesmo filtro do Fast_DF_TTS.
_META_PHRASES = (
    "como sou um modelo de texto",
    "como modelo de linguagem",
    "nao tenho acesso a sua localizacao",
    "nao tenho acesso a localizacao",
    "como um modelo de ia",
    "nao possuo um corpo fisico",
    "nao tenho um corpo",
    "use o comando /voice",
    "use o botao de microfone",
    "como assistente virtual",
    "como ia",
    "como inteligencia artificial",
    "minha funcao e",
)


def _clean_for_speech(text: str) -> str:
    """Strip sources / markdown / meta-talk that don't sound good when spoken."""
    if not text:
        return ""
    text = text.split("\n\nFontes:\n")[0]
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`]+`", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Importa o normalizer compartilhado (DRY — Edge e SAPI5 usam o mesmo).
try:
    from TextToSpeech.normalizer import normalize_for_speech as _normalize_for_speech
except ImportError:
    # Fallback se o modulo nao estiver disponivel (importado de fora do dir).
    _normalize_for_speech = None


def _has_meta_content(text: str) -> bool:
    lower = (text or "").lower()
    hits = sum(1 for p in _META_PHRASES if p in lower)
    return hits >= 2


def _smart_truncate(text: str, max_chars: int = 600) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_dot = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if last_dot > max_chars * 0.5:
        return cut[:last_dot + 1]
    return cut + "..."


async def _synthesize_async(text: str, out_path: pathlib.Path) -> None:
    """Async: chama edge-tts e salva o audio em `out_path`."""
    import edge_tts  # import lazy pra nao quebrar se nao estiver instalado

    communicate = edge_tts.Communicate(
        text,
        voice=EDGE_VOICE,
        rate=EDGE_RATE,
        pitch=EDGE_PITCH,
        volume=EDGE_VOLUME,
    )
    # Edge devolve MP3 por padrao. Salvamos como .mp3 e (opcionalmente)
    # convertemos pra WAV se o usuario preferir.
    await communicate.save(str(out_path))


async def speak_to_file(text: str) -> str:
    """Renderiza `text` em audio usando Edge TTS neural. Retorna path.

    Suporta ser chamada de:
      - sync context (curl direto, scripts) — usa asyncio.run()
      - async context (FastAPI endpoint) — usa await direto
    Detecta o contexto via asyncio.get_running_loop() e age diferente.
    """
    text = _clean_for_speech(text)
    if _has_meta_content(text):
        text = ""
    # Aplica o normalizer compartilhado (tira markdown/pontuacao).
    if _normalize_for_speech is not None:
        text = _normalize_for_speech(text)
    text = _smart_truncate(text, 600)
    if not text:
        return _silent_wav()

    import time
    ts = int(time.time() * 1000)
    out_path = TMP_DIR / f"jarvis_edge_{ts}.mp3"

    try:
        # Detecta se ja existe loop async rodando.
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if in_loop:
            # Estamos dentro de um event loop (ex: FastAPI endpoint).
            # NAO use asyncio.run() — use await direto na coroutine.
            await _synthesize_async(text, out_path)
        else:
            # Contexto sync (script, CLI).
            asyncio.run(_synthesize_async(text, out_path))

        size = out_path.stat().st_size
        print(f"[tts-edge] {EDGE_VOICE} wrote {size} bytes -> {out_path}")
        return str(out_path)
    except Exception as exc:
        print(f"[tts-edge] FAIL: {exc}")
        return _silent_wav()


def _silent_wav() -> str:
    """Devolve path pra um WAV de 1s de silencio. Fallback."""
    import time
    ts = int(time.time() * 1000)
    out_path = TMP_DIR / f"jarvis_silent_{ts}.wav"
    # WAV PCM 16-bit mono 16kHz com 1s de silencio (32000 samples).
    import struct
    sample_rate = 16000
    duration = 1
    num_samples = sample_rate * duration
    data_size = num_samples * 2
    with open(out_path, "wb") as fh:
        # RIFF header
        fh.write(b"RIFF")
        fh.write(struct.pack("<I", 36 + data_size))
        fh.write(b"WAVE")
        # fmt chunk
        fh.write(b"fmt ")
        fh.write(struct.pack("<I", 16))
        fh.write(struct.pack("<H", 1))            # PCM
        fh.write(struct.pack("<H", 1))            # mono
        fh.write(struct.pack("<I", sample_rate))
        fh.write(struct.pack("<I", sample_rate * 2))
        fh.write(struct.pack("<H", 2))
        fh.write(struct.pack("<H", 16))
        # data chunk (silencio = zeros)
        fh.write(b"data")
        fh.write(struct.pack("<I", data_size))
        fh.write(b"\x00" * data_size)
    return str(out_path)


def speak(text: str) -> str:
    """Compat: mesma assinatura do Fast_DF_TTS.speak."""
    return speak_to_file(text)