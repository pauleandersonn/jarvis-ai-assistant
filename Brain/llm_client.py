"""
Local LLM client - adaptado de Mark XLIX (FatihMakes, CC BY-NC 4.0).
Adaptado por @pauleandersonn para JARVIS Premium Edition.

Adaptacoes:
  - Adicionado provider "freeai" (webscout.FreeAI, sem key, default).
  - Provider via env var JARVIS_LLM_PROVIDER > config file > default.
  - call_llm_text() delega para brain.ask_brain() quando provider=freeai.
  - Mantem 100% do suporte Ollama + OpenAI-compatible.

Supports three backends - selected via  "llm_provider"  in config/api_keys.json
or env var JARVIS_LLM_PROVIDER:

  "llm_provider": "freeai"   (default para JARVIS)
        Usa webscout.FreeAI (sem API key, sem Ollama).
        Funciona out-of-the-box. Recomendado para testes.

  "llm_provider": "ollama"
        Uses Ollama native /api/chat endpoint.
        Download: https://ollama.com
        Default port: 11434
        Requer: ollama serve && ollama pull llama3.2

  "llm_provider": "openai"
        Uses any OpenAI-compatible server: LM Studio, Jan, LocalAI,
        llama.cpp server, vLLM, etc.
        Default port: 1234
        Note: tool-calling support depends on the model.
"""
import json
import re
import subprocess
import sys
import os
import time
from pathlib import Path
from typing import Callable, Generator

import requests

# Matches a sentence boundary: [.!?] followed by whitespace, or a blank line.
# Avoids splitting on decimals (3.5) because those have no space after the dot.
_SENT_END = re.compile(r'(?<=[.!?])\s+|(?<=\n)\s*\n')

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

_DEFAULTS = {
    "llm_url":      "http://localhost:11434",
    "llm_model":    "llama3.2",
    # "freeai" (default) | "ollama" | "openai" | "openai_cloud"
    # freeai       - webscout.FreeAI (sem chave, sem Ollama)
    # ollama       - Ollama local (precisa ollama serve + ollama pull)
    # openai       - OpenAI-compat local sem chave (LM Studio, Jan, llama.cpp)
    # openai_cloud - OpenAI-compat HTTPS (OpenAI, Groq, OpenRouter, DeepSeek, Together)
    #                Requer JARVIS_OPENAI_API_KEY (ou openai_api_key no config)
    "llm_provider": "freeai",
    # openai_cloud defaults (podem ser sobrescritos via env vars)
    "openai_cloud_base_url": "https://api.openai.com/v1",
    "openai_cloud_model":    "gpt-4o-mini",
}


def _safe_mask_key(k):
    """Mascara chave para log seguro: 'sk-abc...xyz'. Vazia se nao setada.

    NUNCA retorna a chave inteira em log / print / repr().
    """
    if not k or not isinstance(k, str):
        return ""
    k = k.strip()
    if len(k) <= 8:
        return "<short>"
    return f"{k[:6]}...{k[-4:]}"


def _read_env_file(path):
    """Carrega `.env` (KEY=VALUE) em os.environ SE ainda nao setadas.

    Variaveis ja presentes na sessao NAO sao sobrescritas. Comentarios comecam
    com `#`, aspas externas (simples/dupla) sao removidas.
    """
    p = Path(path)
    if not p.exists():
        return
    try:
        for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if not k:
                continue
            os.environ.setdefault(k, v)
    except Exception as exc:
        print(f"[LLM] warn: falha ao ler {path}: {exc}")


# Carrega .env antes de qualquer leitura de env var no resto do modulo.
_read_env_file(get_base_dir() / ".env")


def get_openai_api_key():
    """Devolve a chave OpenAI/cloud. Ordem: env var > config > ''.

    NUNCA imprima / repr() o retorno direto - use `_safe_mask_key()`.
    """
    env = (os.environ.get("JARVIS_OPENAI_API_KEY") or "").strip()
    if env:
        return env

    cfg = _load_config()
    k = cfg.get("openai_api_key")
    if isinstance(k, str) and k.strip():
        return k.strip()

    # Fallback opcional: OpenRouter costuma usar OPENROUTER_API_KEY
    env_or = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if env_or:
        return env_or
    return ""


def get_openai_cloud_settings():
    """(base_url, model) para o provider openai_cloud."""
    cfg = _load_config()
    block = cfg.get("openai_cloud") if isinstance(cfg.get("openai_cloud"), dict) else {}

    url = (
        (os.environ.get("JARVIS_OPENAI_BASE_URL") or "").strip()
        or (block.get("base_url") or "").strip()
        or _DEFAULTS["openai_cloud_base_url"]
    )
    model = (
        (os.environ.get("JARVIS_OPENAI_MODEL") or "").strip()
        or (block.get("model") or "").strip()
        or _DEFAULTS["openai_cloud_model"]
    )
    return url.rstrip("/"), model


def validate_openai_cloud_key(timeout=8):
    """GET /models com a chave para confirmar que ela e' aceita.

    NAO loga a chave - apenas mascara com `_safe_mask_key()`.
    """
    key = get_openai_api_key()
    if not key:
        return False
    url, _ = get_openai_cloud_settings()
    try:
        r = requests.get(
            f"{url}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        if r.status_code == 200:
            print(f"[LLM] openai_cloud key OK ({_safe_mask_key(key)}) -> {url}")
            return True
        print(f"[LLM] openai_cloud key rejeitada: HTTP {r.status_code}")
        return False
    except Exception as exc:
        print(f"[LLM] openai_cloud health error: {exc}")
        return False


def get_llm_provider() -> str:
    """Retorna um de: 'freeai', 'ollama', 'openai' (local) ou 'openai_cloud' (HTTPS).

    Precedencia: env var JARVIS_LLM_PROVIDER > config/api_keys.json > default (freeai).

    Aliases aceitos no env var:
      - openai, lmstudio, localai, jan, llamacpp -> 'openai'  (local sem chave)
      - groq, openrouter, deepseek, together, openai_cloud -> 'openai_cloud' (HTTPS com chave)
    """
    env = (os.environ.get("JARVIS_LLM_PROVIDER") or "").strip().lower()
    if env in ("freeai", "ollama", "openai_cloud", "openai",
               "lmstudio", "localai", "jan", "llamacpp",
               "groq", "openrouter", "deepseek", "together"):
        if env in ("openai", "lmstudio", "localai", "jan", "llamacpp"):
            return "openai"
        if env in ("groq", "openrouter", "deepseek", "together"):
            return "openai_cloud"
        return env

    raw = _load_config().get("llm_provider", "freeai").strip().lower()
    if raw in ("ollama", "openai", "openai_cloud"):
        return raw
    if raw in ("openai", "lmstudio", "localai", "jan", "llamacpp"):
        return "openai"
    if raw in ("groq", "openrouter", "deepseek", "together"):
        return "openai_cloud"
    return "freeai"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def ensure_ollama_running(timeout: int = 15) -> bool:
    """
    For Ollama: ping /api/tags; auto-launch 'ollama serve' if not running.
    For OpenAI-compatible providers: just ping /v1/models (server must be started manually).
    Returns True if the LLM server is reachable.
    """
    url, _   = get_llm_settings()
    provider = get_llm_provider()

    if provider == "openai":
        # OpenAI-compatible servers (LM Studio, LocalAI, etc.) must be started
        # by the user â€” we just check if they're reachable.
        health = f"{url}/v1/models"
        try:
            ok = requests.get(health, timeout=5).status_code == 200
            if ok:
                print(f"[LLM] OpenAI-compatible server reachable at {url}")
            else:
                print(f"[LLM] Server at {url} returned non-200.  Is it running?")
            return ok
        except Exception as e:
            print(
                f"[LLM] Cannot reach OpenAI-compatible server at {url}.\n"
                "      Make sure LM Studio / LocalAI / Jan is running and the server is started."
            )
            return False

    # â”€â”€ Ollama â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    health = f"{url}/api/tags"

    def _is_up() -> bool:
        try:
            return requests.get(health, timeout=3).status_code == 200
        except Exception:
            return False

    if _is_up():
        return True

    print("[LLM] Ollama not running â€” launching 'ollama serve'â€¦")
    try:
        kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(["ollama", "serve"], **kwargs)
    except FileNotFoundError:
        print("[LLM] 'ollama' command not found. Install Ollama from https://ollama.com")
        return False
    except Exception as e:
        print(f"[LLM] Could not launch Ollama: {e}")
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.0)
        if _is_up():
            print("[LLM] Ollama started successfully.")
            return True

    print("[LLM] Ollama did not respond within the timeout.")
    return False


def warmup_model(system_prompt: str | None = None) -> bool:
    """
    Pre-load the model AND prime Ollama's KV prefix cache.

    Why the system_prompt matters
    â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    Ollama caches the KV attention state of the prompt prefix across requests.
    If warmup includes the same system prompt that real requests will use, Ollama
    evaluates those tokens ONCE at startup.  Every subsequent request only needs
    to evaluate the small delta (user message Â± time context) instead of the full
    300-500 token system prompt â†’ drops first-token latency from ~17 s to <1 s.

    Pass the *static* part of the system prompt (the JARVIS protocol text, without
    timestamps or per-minute context) so the prefix stays valid across calls.
    """
    url, model = get_llm_settings()
    provider   = get_llm_provider()
    print(f"[LLM] Warming up '{model}' ({provider})â€¦")

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": "hi"})

    if provider in ("openai", "openai_cloud"):
        # OpenAI-compatible: just fire a minimal request to ensure the model is loaded.
        payload = {
            "model":      model,
            "messages":   messages,
            "stream":     False,
            "max_tokens": 1,
        }
        try:
            resp = requests.post(
                f"{url}/v1/chat/completions",
                json=payload,
                headers=_llm_headers(provider),
                timeout=180,
            )
            resp.raise_for_status()
            print(f"[LLM] '{model}' ready ({provider}).")
            return True
        except Exception as e:
            print(f"[LLM] Warmup failed (non-fatal): {e}")
            return False

    # â”€â”€ Ollama â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    payload = {
        "model":      model,
        "messages":   messages,
        "stream":     False,
        "keep_alive": -1,
        # num_gpu:99 â†’ push ALL transformer layers to GPU (Ollama caps at available)
        # This is safe even without a GPU â€” Ollama silently ignores if n_gpu_layers=0
        "options":    {"num_predict": 1, "num_gpu": 99},
    }
    try:
        resp = requests.post(f"{url}/api/chat", json=payload, timeout=180)
        resp.raise_for_status()
        print(f"[LLM] '{model}' loaded and KV cache primed.")
        return True
    except Exception as e:
        print(f"[LLM] Warmup failed (non-fatal): {e}")
        return False


def check_model_available(log: Callable | None = None) -> bool:
    """
    Returns True if the configured model is already pulled in Ollama.
    Logs an actionable warning (to console + optional UI callback) if not.
    Always returns True for non-Ollama providers (cannot inspect their model list).
    """
    if get_llm_provider() != "ollama":
        return True

    url, model = get_llm_settings()
    try:
        resp = requests.get(f"{url}/api/tags", timeout=5)
        resp.raise_for_status()
        pulled = [m.get("name", "") for m in resp.json().get("models", [])]
        model_base = model.split(":")[0]
        found = any(
            m == model or m == model_base or m.startswith(model_base + ":")
            for m in pulled
        )
        if not found:
            available = ", ".join(pulled) if pulled else "none"
            warn = (
                f"WRN: Model '{model}' is not pulled in Ollama.\n"
                f"     Available: {available}\n"
                f"     Fix: ollama pull {model}"
            )
            print(warn)
            if log:
                log(f"WRN: '{model}' not found â€” run: ollama pull {model}")
        return found
    except Exception:
        return True   # Ollama might still be starting up; non-blocking


def get_llm_settings() -> tuple[str, str]:
    """Returns (base_url, model_name) para o provider ativo.

    Para 'ollama' / 'openai' local -> usa llm_url/llm_model do config (legado).
    Para 'openai_cloud' -> usa get_openai_cloud_settings() (env var ou bloco
    openai_cloud do config), sempre HTTPS.
    """
    cfg = _load_config()
    provider = get_llm_provider()

    if provider == "openai_cloud":
        url, model = get_openai_cloud_settings()
        return url, model

    url   = cfg.get("llm_url",   _DEFAULTS["llm_url"]).rstrip("/")
    model = cfg.get("llm_model", _DEFAULTS["llm_model"])
    return url, model


def _llm_headers(provider: str) -> dict:
    """Headers para o provider dado. Sempre inclui 'Content-Type'.

    Para 'openai_cloud' adiciona 'Authorization: Bearer <key>' (a chave e'
    lida mas NUNCA impressa em log).
    """
    h = {"Content-Type": "application/json"}
    if provider == "openai_cloud":
        key = get_openai_api_key()
        if key:
            h["Authorization"] = f"Bearer {key}"
        else:
            print("[LLM] WARN: openai_cloud selecionado sem "
                  "JARVIS_OPENAI_API_KEY - chamada provavelmente falhara.")
    return h


def call_llm(
    messages: list,
    tools:    list | None = None,
    timeout:  int = 120,
) -> dict:
    """
    Non-streaming chat request.  Routes to Ollama or OpenAI-compatible backend.

    Returns:
        {"content": str, "tool_calls": list}
    """
    url, model = get_llm_settings()
    provider   = get_llm_provider()

    if provider in ("openai", "openai_cloud"):
        endpoint = f"{url}/v1/chat/completions"
        payload: dict = {
            "model":      model,
            "messages":   messages,
            "stream":     False,
            "max_tokens": 150,
        }
        if tools:
            payload["tools"]       = tools
            payload["tool_choice"] = "auto"
        try:
            resp = requests.post(
                endpoint,
                json=payload,
                headers=_llm_headers(provider),
                timeout=timeout,
            )
            resp.raise_for_status()
            choice = resp.json().get("choices", [{}])[0]
            msg    = choice.get("message", {})
            # OpenAI tool_calls format -> normalise to Ollama-style
            raw_tc  = msg.get("tool_calls") or []
            tc_list = [
                {
                    "id":       t.get("id", ""),
                    "function": {
                        "name":      t["function"]["name"],
                        "arguments": (
                            json.loads(t["function"]["arguments"])
                            if isinstance(t["function"].get("arguments"), str)
                            else t["function"].get("arguments", {})
                        ),
                    },
                }
                for t in raw_tc
            ]
            return {
                "content":    (msg.get("content") or "").strip(),
                "tool_calls": tc_list,
            }
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            body = (e.response.text or "")[:200] if e.response is not None else ""
            print(f"[LLM] HTTPError ({provider}): {code} - {body}")
            if provider == "openai_cloud" and code in (401, 403):
                raise RuntimeError(
                    "openai_cloud rejeitou a chave (HTTP "
                    f"{code}). Verifique JARVIS_OPENAI_API_KEY."
                )
            raise RuntimeError(f"OpenAI-compatible LLM call failed: {code} - {body}")
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible LLM call failed: {e}")

    # â”€â”€ Ollama â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    endpoint = f"{url}/api/chat"
    payload = {
        "model":      model,
        "messages":   messages,
        "stream":     False,
        "keep_alive": -1,
        "options":    {"num_predict": 150, "num_gpu": 99},
    }
    if tools:
        payload["tools"] = tools

    try:
        resp = requests.post(endpoint, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        msg  = data.get("message", {})
        return {
            "content":    (msg.get("content") or "").strip(),
            "tool_calls": msg.get("tool_calls") or [],
        }
    except requests.exceptions.ConnectionError as e:
        print(f"[LLM] ConnectionError â€” trying to restart Ollamaâ€¦ ({e})")
        if ensure_ollama_running():
            try:
                resp = requests.post(endpoint, json=payload, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                msg  = data.get("message", {})
                return {
                    "content":    (msg.get("content") or "").strip(),
                    "tool_calls": msg.get("tool_calls") or [],
                }
            except Exception:
                pass
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama request timed out after 120 s.")
    except requests.exceptions.HTTPError as e:
        print(f"[LLM] HTTPError: {e.response.status_code} â€” {e.response.text[:200]}")
        raise RuntimeError(f"Ollama HTTP error: {e.response.status_code}")
    except Exception as e:
        print(f"[LLM] Unexpected error: {type(e).__name__}: {e}")
        raise RuntimeError(f"LLM call failed: {e}")


def call_llm_text(
    prompt:  str,
    system:  str | None = None,
    model:   str | None = None,
    timeout: int = 120,
) -> str:
    """
    Simple text-only generation (no tools).
    Used by planner, executor, error_handler, code_helper, dev_agent.
    """
    # JARVIS Premium: freeai provider -> delegate to brain.ask_brain()
    if get_llm_provider() == "freeai":
        try:
            from Brain.brain import ask_brain
            full = f"{system}\n\n{prompt}" if system else prompt
            return ask_brain(full)
        except Exception as _e:
            return f"[freeai offline] {_e}"

    url, default_model = get_llm_settings()
    provider = get_llm_provider()
    m        = model or default_model

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # openai_cloud usa o mesmo formato OpenAI-compat de '/v1/chat/completions'.
    if provider == "openai_cloud":
        endpoint = f"{url}/v1/chat/completions"
        payload  = {
            "model":      m,
            "messages":   messages,
            "stream":     False,
            "max_tokens": 600,
        }
        try:
            resp = requests.post(
                endpoint,
                json=payload,
                headers=_llm_headers(provider),
                timeout=timeout,
            )
            resp.raise_for_status()
            choice = resp.json().get("choices", [{}])[0]
            return (choice.get("message", {}).get("content") or "").strip()
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            body = (e.response.text or "")[:200] if e.response is not None else ""
            if code in (401, 403):
                raise RuntimeError(
                    f"openai_cloud rejeitou a chave (HTTP {code}). "
                    "Verifique JARVIS_OPENAI_API_KEY."
                )
            raise RuntimeError(f"openai_cloud HTTP {code} - {body}")
        except Exception as e:
            raise RuntimeError(f"openai_cloud call failed: {e}")

    # Ollama (legado)
    endpoint = f"{url}/api/chat"
    payload  = {"model": m, "messages": messages, "stream": False, "keep_alive": -1, "options": {"num_predict": 600}}

    try:
        resp = requests.post(endpoint, json=payload, timeout=timeout)
        resp.raise_for_status()
        return (resp.json().get("message", {}).get("content") or "").strip()
    except requests.exceptions.ConnectionError:
        if ensure_ollama_running():
            try:
                resp = requests.post(endpoint, json=payload, timeout=timeout)
                resp.raise_for_status()
                return (resp.json().get("message", {}).get("content") or "").strip()
            except Exception:
                pass
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except Exception as e:
        raise RuntimeError(f"LLM text call failed: {e}")


def _stream_openai(
    messages: list,
    tools:    list | None,
    timeout:  int,
) -> Generator[dict, None, None]:
    """
    Streaming backend for OpenAI-compatible servers (LM Studio, LocalAI, Jan,
    e tambem o provider 'openai_cloud' - OpenAI/Groq/OpenRouter/DeepSeek/Together).

    Parses Server-Sent Events (SSE) e acumula fragmentos de tool-call para que o
    formato de saida seja identico ao backend Ollama. Adiciona o header
    `Authorization: Bearer <key>` automaticamente quando provider='openai_cloud'.
    """
    provider = get_llm_provider()
    url, model = get_llm_settings()
    endpoint   = f"{url}/v1/chat/completions"

    payload: dict = {
        "model":      model,
        "messages":   messages,
        "stream":     True,
        "max_tokens": 150,
    }
    if tools:
        payload["tools"]       = tools
        payload["tool_choice"] = "auto"

    try:
        with requests.post(
            endpoint,
            json=payload,
            headers=_llm_headers(provider),
            timeout=timeout,
            stream=True,
        ) as resp:
            resp.raise_for_status()
            full_content = ""
            buf          = ""
            # tool_call fragments: index â†’ {"id", "function": {"name", "arguments"}}
            tc_fragments: dict[int, dict] = {}

            for raw in resp.iter_lines():
                if not raw:
                    continue
                # SSE lines look like: b"data: {...}" or b"data: [DONE]"
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choice = chunk.get("choices", [{}])[0]
                delta  = choice.get("delta", {})
                text   = delta.get("content") or ""

                full_content += text
                buf          += text

                # Accumulate sentence boundaries for streaming TTS
                while True:
                    m = _SENT_END.search(buf)
                    if not m:
                        break
                    sentence = buf[: m.start() + 1].strip()
                    buf      = buf[m.end():]
                    if sentence:
                        yield {"type": "sentence", "text": sentence}

                # Accumulate streaming tool-call fragments
                for tc in (delta.get("tool_calls") or []):
                    idx = tc.get("index", 0)
                    if idx not in tc_fragments:
                        tc_fragments[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
                    frag = tc_fragments[idx]
                    frag["id"] = frag["id"] or tc.get("id", "")
                    fn = tc.get("function", {})
                    frag["function"]["name"]      += fn.get("name") or ""
                    frag["function"]["arguments"] += fn.get("arguments") or ""

                finish = choice.get("finish_reason")
                if finish in ("stop", "tool_calls", "length"):
                    break

            # Flush any trailing content
            if buf.strip():
                yield {"type": "sentence", "text": buf.strip()}

            # Parse accumulated tool-call argument strings â†’ dicts
            tool_calls: list = []
            for idx in sorted(tc_fragments):
                frag = tc_fragments[idx]
                args = frag["function"]["arguments"]
                try:
                    args = json.loads(args)
                except Exception:
                    pass   # leave as raw string; _execute_tool handles it
                tool_calls.append({
                    "id":       frag["id"],
                    "function": {"name": frag["function"]["name"], "arguments": args},
                })

            yield {
                "type":       "done",
                "content":    full_content.strip(),
                "tool_calls": tool_calls,
            }

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot reach OpenAI-compatible server at {url}.\n"
            "Make sure LM Studio / LocalAI / Jan is running and the server is started."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("OpenAI-compatible stream timed out.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"OpenAI-compatible HTTP error: {e.response.status_code}")
    except Exception as e:
        raise RuntimeError(f"OpenAI-compatible stream failed: {e}")


def call_llm_stream(
    messages: list,
    tools:    list | None = None,
    timeout:  int = 120,
) -> Generator[dict, None, None]:
    """
    Streaming chat request.  Routes to Ollama or OpenAI-compatible backend.

    Yields:
        {"type": "sentence", "text": str}   â€” each complete sentence as it arrives
        {"type": "done", "content": str, "tool_calls": list}  â€” when stream ends

    Sentences are split on [.!?] + whitespace so TTS can start immediately.
    Tool calls always appear in the final "done" event.
    """
    provider = get_llm_provider()
    if provider in ("openai", "openai_cloud"):
        yield from _stream_openai(messages, tools, timeout)
        return

    url, model = get_llm_settings()
    endpoint   = f"{url}/api/chat"

    payload: dict = {
        "model":      model,
        "messages":   messages,
        "stream":     True,
        "keep_alive": -1,
        # 150 tokens â‰ˆ 100 words â‰ˆ 3-4 sentences â€” enough for any voice reply.
        # num_gpu:99 pushes all layers to GPU; num_thread removed (Ollama auto-tunes).
        "options":    {"num_predict": 150, "num_gpu": 99},
    }
    if tools:
        payload["tools"] = tools

    def _do_stream() -> Generator[dict, None, None]:
        with requests.post(endpoint, json=payload, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            full_content = ""
            tool_calls:  list = []
            buf          = ""

            for raw in resp.iter_lines():
                if not raw:
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg   = chunk.get("message", {})
                delta = msg.get("content") or ""

                full_content += delta
                buf          += delta

                # Yield complete sentences as they accumulate
                while True:
                    m = _SENT_END.search(buf)
                    if not m:
                        break
                    sentence = buf[: m.start() + 1].strip()
                    buf      = buf[m.end() :]
                    if sentence:
                        yield {"type": "sentence", "text": sentence}

                tc = msg.get("tool_calls")
                if tc:
                    tool_calls.extend(tc)

                if chunk.get("done"):
                    if buf.strip():
                        yield {"type": "sentence", "text": buf.strip()}

                    yield {
                        "type":       "done",
                        "content":    full_content.strip(),
                        "tool_calls": tool_calls,
                    }
                    return

    try:
        yield from _do_stream()
    except requests.exceptions.ConnectionError as e:
        print(f"[LLM] Stream ConnectionError â€” trying to restart Ollamaâ€¦ ({e})")
        if ensure_ollama_running():
            yield from _do_stream()
            return
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama stream timed out.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Ollama HTTP error: {e.response.status_code}")
    except Exception as e:
        print(f"[LLM] Stream error: {type(e).__name__}: {e}")
        raise RuntimeError(f"LLM stream failed: {e}")
