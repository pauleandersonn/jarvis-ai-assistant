"""LLM client with multi-provider fallback.

Stack of providers tried in order (configurable via env vars):

  1. OpenRouter   — primary (Claude Sonnet 4.5 if OPENROUTER_API_KEY set)
  2. Anthropic    — direct Anthropic API if ANTHROPIC_API_KEY set
  3. Hermes proxy — local hermes proxy if HERMES_PROXY_URL set
  4. FreeAI       — webscout fallback (no key needed, slow)

Configure via env vars (in Brain/.env or system env):

  OPENROUTER_API_KEY    = sk-or-v1-...
  OPENROUTER_MODEL      = anthropic/claude-sonnet-4-5  (default)
  OPENROUTER_BASE_URL   = https://openrouter.ai/api/v1

  ANTHROPIC_API_KEY     = sk-ant-...

  HERMES_PROXY_URL      = http://127.0.0.1:8765/v1  (if using hermes proxy)
  HERMES_PROXY_API_KEY  = hermes  (any string, proxy accepts any bearer)

All providers expose a single `complete(prompt, *, system=None, max_tokens=1024)`
function that returns the assistant text or raises an error.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

LOG = logging.getLogger("jarvis.llm")

_DEFAULT_MODEL_OPENROUTER = "anthropic/claude-sonnet-4-5"
_DEFAULT_MODEL_ANTHROPIC = "claude-sonnet-4-5"
_DEFAULT_MODEL_HERMES = "auto"


class LLMUnavailable(Exception):
    """Raised when no provider is configured or all providers failed."""


def _openai_compat_complete(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    system: Optional[str],
    max_tokens: int,
    timeout: float = 120.0,
) -> str:
    """Call any OpenAI-compatible /v1/chat/completions endpoint."""
    import urllib.request, urllib.error, json
    url = base_url.rstrip("/") + "/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.6,
    }
    req = urllib.request.Request(
        url, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # OpenRouter recommends these
            "HTTP-Referer": "https://jarvis.local",
            "X-Title": "JARVIS",
        },
    )
    req.data = json.dumps(body).encode("utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return (
        resp.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        or ""
    )


def _anthropic_complete(prompt: str, system: Optional[str], max_tokens: int, timeout: float = 120.0) -> str:
    """Direct Anthropic Messages API."""
    import urllib.request, json
    api_key = os.environ["ANTHROPIC_API_KEY"]
    model = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL_ANTHROPIC)

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    req.data = json.dumps(body).encode("utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    parts = resp.get("content", [])
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")


def _freeai_complete(prompt: str, system: Optional[str], max_tokens: int, timeout: float = 120.0) -> str:
    """FreeAI fallback via webscout. No system arg support (prepend it)."""
    from webscout import FreeAI
    full = f"{system}\n\n{prompt}" if system else prompt
    ai = FreeAI()
    raw = ai.ask(full)
    if isinstance(raw, dict):
        return (
            raw.get("text")
            or raw.get("message")
            or raw.get("response")
            or str(raw)
        )
    return str(raw)


def complete(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = 1024,
    timeout: float = 120.0,
) -> str:
    """Try providers in order; return first success or raise LLMUnavailable.

    Precedence:
      1. OpenRouter (best quality Claude)
      2. Anthropic (direct API)
      3. Hermes proxy (any OAuth provider routed by Hermes)
      4. FreeAI (webscout fallback)
    """
    errors = []

    # 1) OpenRouter
    if os.environ.get("OPENROUTER_API_KEY"):
        try:
            base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            model = os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODEL_OPENROUTER)
            out = _openai_compat_complete(base_url, os.environ["OPENROUTER_API_KEY"], model, prompt, system, max_tokens, timeout)
            if out.strip():
                LOG.info("LLM=openrouter model=%s len=%d", model, len(out))
                return out
            errors.append("openrouter: empty response")
        except Exception as e:  # noqa: BLE001
            errors.append(f"openrouter: {e}")
            LOG.warning("openrouter failed: %s", e)

    # 2) Anthropic
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            out = _anthropic_complete(prompt, system, max_tokens, timeout)
            if out.strip():
                LOG.info("LLM=anthropic len=%d", len(out))
                return out
            errors.append("anthropic: empty response")
        except Exception as e:  # noqa: BLE001
            errors.append(f"anthropic: {e}")
            LOG.warning("anthropic failed: %s", e)

    # 3) Hermes proxy
    if os.environ.get("HERMES_PROXY_URL"):
        try:
            base_url = os.environ["HERMES_PROXY_URL"]
            api_key = os.environ.get("HERMES_PROXY_API_KEY", "hermes")
            model = os.environ.get("HERMES_PROXY_MODEL", _DEFAULT_MODEL_HERMES)
            out = _openai_compat_complete(base_url, api_key, model, prompt, system, max_tokens, timeout)
            if out.strip():
                LOG.info("LLM=hermes-proxy model=%s len=%d", model, len(out))
                return out
            errors.append("hermes-proxy: empty response")
        except Exception as e:  # noqa: BLE001
            errors.append(f"hermes-proxy: {e}")
            LOG.warning("hermes-proxy failed: %s", e)

    # 4) FreeAI (always available)
    try:
        out = _freeai_complete(prompt, system, max_tokens, timeout)
        if out.strip():
            LOG.info("LLM=freeai len=%d", len(out))
            return out
        errors.append("freeai: empty response")
    except Exception as e:  # noqa: BLE001
        errors.append(f"freeai: {e}")
        LOG.warning("freeai failed: %s", e)

    raise LLMUnavailable("; ".join(errors))


# Self-test
if __name__ == "__main__":
    import sys
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Diga oi em uma frase."
    try:
        print(complete(prompt, max_tokens=200))
    except LLMUnavailable as e:
        print(f"[FALHA] nenhum provider: {e}", file=sys.stderr)
        sys.exit(1)