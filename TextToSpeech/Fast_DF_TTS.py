"""Text-to-speech WAV generator using Windows native SAPI5 (no local playback).

Contrato:
 - O servidor APENAS gera o audio (WAV em disco) — nunca reproduz no host.
 - O navegador baixa o WAV via `/api/speak` e toca via HTMLAudioElement.
 - Substituimos `playsound` (deadlock no Py 3.13+), `os.startfile` (acumulava
   instancias do Windows Media Player) e `sounddevice.play` (tocava no servidor,
   nao no cliente). Agora o TTS so escreve o WAV — quem toca e o navegador.
 - Usamos `SAPI.SpFileStream` + `SAPI.SpVoice.Speak` sincrono para escrever
   o WAV completo antes de devolver o path.
 - Cada chamada cria uma instancia nova de `SpVoice` (cache leva a
   COM error 0x80010008 quando outro modulo tambem usa SAPI5).
 - Threads do FastAPI/uvicorn precisam de `CoInitialize` antes de tocar COM.
 - Volume fixo em 100, Rate=0.
 - Voz: tenta Portuguese/Brasil primeiro, cai pra default se nao houver.
"""

import os
import pathlib
import re
import threading
import time

import win32com.client  # type: ignore[import-not-found]

# Directory the project will use for generated WAV files.
TMP_DIR = pathlib.Path(__file__).resolve().parent / "tmp_audio"
TMP_DIR.mkdir(exist_ok=True)

# Per-thread COM apartment tracking.
_init_lock = threading.Lock()
_initialized_threads: set[int] = set()


def _ensure_com() -> None:
    """Initialize COM in the current thread (STA mode) if needed."""
    tid = threading.get_ident()
    with _init_lock:
        if tid in _initialized_threads:
            return
        try:
            import pythoncom  # type: ignore[import-not-found]
            pythoncom.CoInitialize()
            _initialized_threads.add(tid)
        except Exception:
            _initialized_threads.add(tid)


def _clean_for_speech(text: str) -> str:
    """Strip sources / markdown / meta-talk that don't sound good when spoken."""
    if not text:
        return ""
    # Remove "Fontes:\n..." blocks added by the researcher.
    text = text.split("\n\nFontes:\n")[0]
    # Remove citation markers like [1], [2].
    text = re.sub(r"\[\d+\]", "", text)
    # Strip code fences and inline code (JARVIS shouldn't read raw code aloud).
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`]+`", " ", text)
    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Phrases the LLM sometimes echoes back that we don't want spoken out loud.
# These are signs the model is talking about itself instead of answering.
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


def _has_meta_content(text: str) -> bool:
    """Detecta se a resposta do LLM e meta-fala (fala sobre si mesmo em vez de responder).

    Quando True, o cliente vai mostrar fallback em vez de falar essa bobagem.
    """
    if not text:
        return False
    lower = text.lower()
    # Tem 2+ marcadores meta = claramente falando sobre si mesmo
    hits = sum(1 for p in _META_PHRASES if p in lower)
    return hits >= 2


def _smart_truncate(text: str, max_chars: int = 600) -> str:
    """Encurta respostas muito longas pra TTS.

    FreeAI as vezes cospe o prompt inteiro do sistema ou respostas de 2000+ chars.
    Cortamos em max_chars preservando a primeira sentenca completa.
    """
    if len(text) <= max_chars:
        return text
    # Corta em sentenca mais proxima
    cut = text[:max_chars]
    last_dot = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if last_dot > max_chars * 0.5:
        return cut[:last_dot + 1]
    return cut + "..."


def _new_speaker():
    """Create a fresh SAPI5 SpVoice instance with sane defaults.

    A fresh instance is safer than a cached one: COM apartments and the
    SAPI engine don't always play nicely across concurrent threads.
    """
    _ensure_com()
    speaker = win32com.client.Dispatch("SAPI.SpVoice")

    # Pin volume at 100% so the user always hears output, regardless of
    # whatever the OS-level SAPI default might be in the current session.
    try:
        speaker.Volume = 100
    except Exception:
        pass

    # Pick the best Portuguese voice available, fallback to default.
    try:
        voices = speaker.GetVoices()
        chosen = None
        for i in range(voices.Count):
            v = voices.Item(i)
            desc = v.GetDescription() or ""
            if "Portuguese" in desc or "Brasil" in desc:
                chosen = v
                break
        if chosen is not None:
            speaker.Voice = chosen
    except Exception:
        pass

    return speaker


def speak(text: str) -> str:
    """Speak `text` out loud and return a status message.

    Strategy: render the audio to a WAV file using SAPI5, then open the
    file with the OS default player (os.startfile on Windows). Calling
    SAPI5's `Speak()` directly worked in isolation but failed silently
    when called from inside a FastAPI / uvicorn worker, so we go through
    the file path which is reliable.
    """
    result = speak_with_audio(text)
    return result


def speak_to_file(text: str) -> str:
    """Render `text` to a WAV file via SAPI5 and return its path.

    Server-side helper for the dashboard /api/speak endpoint: we want
    to GENERATE the audio but NOT play it on the server (server playback
    goes through speakers attached to the host machine, not the user's
    headphones). The browser fetches the resulting WAV and plays it
    locally.
    """
    print(f"[tts] speak_to_file: len={len(text or '')}")
    clean = _clean_for_speech(text)
    if not clean:
        raise ValueError("Nothing to say (empty after clean).")
    if _has_meta_content(clean):
        raise ValueError(f"meta-talk blocked: {clean[:80]}...")
    clean = _smart_truncate(clean, max_chars=600)

    speaker = None
    stream = None
    try:
        wav_path = TMP_DIR / f"jarvis_{int(time.time()*1000)}.wav"
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[tts] target wav: {wav_path}")

        speaker = _new_speaker()
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Format.Type = 22
        stream.Open(str(wav_path), 3, False)
        speaker.AudioOutputStream = stream
        speaker.Speak(clean, 0)
        stream.Close()
        stream = None
        speaker.AudioOutputStream = None
        size = wav_path.stat().st_size if wav_path.exists() else 0
        print(f"[tts] wav written: size={size}")
        return str(wav_path)
    finally:
        try:
            if stream is not None:
                stream.Close()
        except Exception:
            pass
        try:
            if speaker is not None:
                speaker.AudioOutputStream = None
        except Exception:
            pass


def speak_with_audio(text: str, audio_file: str | None = None) -> str:
    """[DEPRECIADO] Mantido por retrocompat — apenas chama `speak_to_file()`.

    Historicamente esta funcao reproduzia o WAV no servidor via sounddevice.
    Isso esta errado para uma aplicacao web: o audio tocava na maquina onde o
    servidor roda, nao onde o usuario esta. Agora a geracao acontece aqui mas
    a REPRODUCAO e responsabilidade do navegador — o WAV e devolvido por
    `/api/speak` e tocado pelo frontend via HTMLAudioElement.

    Para o caminho antigo (CLI local, fora do navegador) use `speak_to_file()`
    + um player externo, ou use diretamente `speaker.Speak(...)`.
    """
    print(f"[tts] speak_with_audio (legacy): len={len(text or '')}")
    wav_path = speak_to_file(text)
    return f"Generated: {wav_path} (playback is browser responsibility)"


def wav_duration_seconds(wav_path) -> float:
    """Return the duration of a WAV file in seconds by reading its header.

    Standard PCM WAV header layout:
      bytes 0-3   : "RIFF"
      bytes 4-7   : file size - 8
      bytes 8-11  : "WAVE"
      bytes 12-15 : "fmt "
      bytes 16-19 : subchunk size (usually 16 for PCM)
      bytes 20-21 : audio format (1 = PCM)
      bytes 22-23 : num channels
      bytes 24-27 : sample rate
      bytes 28-31 : byte rate = sample_rate * channels * bits_per_sample / 8
      bytes 32-33 : block align
      bytes 34-35 : bits per sample
      then a "data" subchunk with size + audio bytes
    """
    try:
        with open(wav_path, "rb") as fh:
            riff = fh.read(12)
            if not riff.startswith(b"RIFF") or not riff[8:12] == b"WAVE":
                return 0.0
            # Walk subchunks until we find "fmt " and "data".
            sample_rate = 0
            num_channels = 0
            bits_per_sample = 0
            data_size = 0
            while True:
                chunk_header = fh.read(8)
                if len(chunk_header) < 8:
                    break
                chunk_id = chunk_header[0:4]
                chunk_size = int.from_bytes(chunk_header[4:8], "little")
                if chunk_id == b"fmt ":
                    fmt = fh.read(chunk_size)
                    num_channels = int.from_bytes(fmt[2:4], "little")
                    sample_rate = int.from_bytes(fmt[4:8], "little")
                    bits_per_sample = int.from_bytes(fmt[14:16], "little")
                elif chunk_id == b"data":
                    data_size = chunk_size
                    break
                else:
                    fh.seek(chunk_size, 1)  # skip past this chunk
            if sample_rate <= 0 or num_channels <= 0 or bits_per_sample <= 0:
                return 0.0
            bytes_per_second = sample_rate * num_channels * bits_per_sample // 8
            return data_size / bytes_per_second if bytes_per_second else 0.0
    except Exception:
        return 0.0