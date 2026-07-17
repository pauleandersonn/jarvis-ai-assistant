"""Text-to-speech + playback using Windows native SAPI5 + os.startfile.

We replaced the original `playsound==1.2.2` (which deadlocks on
Python 3.13+) and `os.startfile` (which spawned Windows Media Player
and accumulated instances in background, causing the "same audio
loop" bug) with `sounddevice` + `wave` stdlib: the WAV is played in a
Python thread directly through the default audio device, no external
player, no instance leak.

We create a fresh `SAPI.SpVoice` instance on every call instead of
caching one. Caching leads to COM error 0x80010008 ("Exception") when
another module on the same process also uses SAPI5.

Threads spawned by FastAPI / uvicorn need `CoInitialize` before they
can touch COM objects; we wrap SAPI calls in a helper that does this.

We explicitly set Volume=100 and Rate=0 on every fresh instance to
defeat any leftover state from the SAPI5 defaults.
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
    """Render `text` to a WAV file, then play it via os.startfile.

    This is the proven reliable path: SAPI5 writes a WAV, Windows
    opens it with the default player, audio comes out. Direct SAPI5
    playback silently fails inside the uvicorn worker process.
    """
    print(f"[tts] speak_with_audio: len={len(text or '')}")
    clean = _clean_for_speech(text)
    if not clean:
        print("[tts] skip: empty after clean")
        return "Nothing to say."

    # Bloqueia meta-fala (LLM falando sobre si mesmo em vez de responder).
    if _has_meta_content(clean):
        print(f"[tts] skip: meta-content detected")
        return f"[skip meta-talk: {clean[:80]}...]"

    # Encurta respostas longas pra nao gerar WAVs gigantes.
    clean = _smart_truncate(clean, max_chars=600)

    speaker = None
    stream = None
    try:
        wav_path = (
            pathlib.Path(audio_file) if audio_file
            else TMP_DIR / f"jarvis_{int(time.time()*1000)}.wav"
        )
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[tts] target wav: {wav_path}")

        speaker = _new_speaker()
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        # 22 = 16-bit 16 kHz mono (good balance of size and clarity).
        stream.Format.Type = 22
        # 3 = SSFMCreateForWrite
        stream.Open(str(wav_path), 3, False)
        speaker.AudioOutputStream = stream
        # SVSFlagsAsync would let us return early; we use sync (0) so we
        # know the WAV is fully written before we hand it to the player.
        speaker.Speak(clean, 0)
        stream.Close()
        stream = None
        speaker.AudioOutputStream = None
        print(f"[tts] wav written: size={wav_path.stat().st_size if wav_path.exists() else 0}")

        # Reproduz o WAV DIRETAMENTE via sounddevice (sem abrir player externo).
        # Antes usavamos os.startfile(), que abria o Windows Media Player toda vez
        # e acumulava instancias em background tocando o mesmo audio em loop.
        _play_wav_blocking(str(wav_path))
        print(f"[tts] playback OK: {wav_path}")
        return f"Played: {wav_path}"
    except Exception as exc:  # noqa: BLE001
        print(f"[tts] ERROR: {exc}")
        return f"Audio playback error: {exc}"
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


def _play_wav_blocking(wav_path: str) -> None:
    """Reproduz um WAV via sounddevice, bloqueando ate o fim.

    Substitui os.startfile() que abria o player externo e acumulava instancias.
    sounddevice gera um buffer em memoria e toca direto no dispositivo de audio
    padrao, sem spawn de processos.

    Se sounddevice nao estiver disponivel, faz fallback silencioso para
    winsound (tambem nao spawna processo).
    """
    try:
        # Le o WAV com stdlib
        import wave
        with wave.open(wav_path, "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            data = wf.readframes(n_frames)

        # Tenta sounddevice primeiro (PCM int16 ou float32)
        try:
            import sounddevice as sd
            import numpy as np  # type: ignore
            if sample_width == 2:
                audio = np.frombuffer(data, dtype=np.int16)
            elif sample_width == 4:
                audio = np.frombuffer(data, dtype=np.int32)
            elif sample_width == 1:
                audio = np.frombuffer(data, dtype=np.uint8).astype(np.int16) * 256
            else:
                audio = np.frombuffer(data, dtype=np.int16)
            sd.play(audio, samplerate=framerate, blocking=True)
            return
        except ImportError:
            pass

        # Fallback: winsound (nao spawna processo, toca direto)
        import winsound  # type: ignore
        winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
    except Exception:
        # Em ultimo caso, log silencioso. NUNCA chamar os.startfile() de novo:
        # isso era o bug original.
        pass


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