"""Voice confirmation orchestrator.

When JARVIS MCP server wants to do a write action (send email, create event,
etc.), it calls request_confirmation(...) which:

  1. Writes a JSON file to dashboard state dir: ~/.jarvis/voice_confirm/<uuid>.json
  2. The JARVIS dashboard JS polls /api/voice-confirm/pending every 1s
  3. When a pending request is detected, dashboard speaks the prompt via TTS
     and starts webkitSpeechRecognition for user response
  4. Dashboard posts the result to /api/voice-confirm/respond
  5. request_confirmation() blocks until response arrives or timeout (30s)
  6. Returns {"status": "approved"|"denied"|"timeout", ...}

This file contains:
  - the orchestrator (request_confirmation)
  - the file-based request/response queue
  - helpers for dashboard integration

The dashboard pulls pending requests via /api/voice-confirm/pending and
posts responses via /api/voice-confirm/respond (see dashboard.py patches).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path

LOG = logging.getLogger("jarvis.voice_confirm")

_STATE_DIR = Path(os.environ.get("JARVIS_STATE_DIR", Path.home() / ".jarvis" / "voice_confirm"))
_STATE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TIMEOUT = 30.0
POLL_INTERVAL = 0.25  # seconds


def _request_path(request_id: str) -> Path:
    return _STATE_DIR / f"{request_id}.json"


def _write_request(request_id: str, payload: dict) -> None:
    """Atomically write the request file (so dashboard can poll it)."""
    p = _request_path(request_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _read_response(request_id: str) -> dict | None:
    p = _STATE_DIR / f"{request_id}.response.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def request_confirmation(
    intent: str,
    voice_prompt: str,
    action_payload: dict,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Block until user confirms/denies via voice in the JARVIS dashboard.

    Returns:
      {"status": "approved", "request_id": "..."} - user said yes
      {"status": "denied", "reason": "..."} - user said no
      {"status": "timeout", "request_id": "..."} - no response in `timeout` sec
      {"status": "error", "error": "..."} - dashboard not running / other
    """
    request_id = str(uuid.uuid4())[:8]
    payload = {
        "request_id": request_id,
        "intent": intent,
        "voice_prompt": voice_prompt,
        "action_payload": action_payload,
        "created_at": time.time(),
        "status": "pending",
    }
    _write_request(request_id, payload)
    LOG.info("voice_confirm: pending request %s for intent=%s", request_id, intent)

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        resp = _read_response(request_id)
        if resp is None:
            continue
        # Got response
        LOG.info("voice_confirm: %s -> %s", request_id, resp.get("status"))
        return resp

    LOG.warning("voice_confirm: %s timed out after %.1fs", request_id, timeout)
    return {"status": "timeout", "request_id": request_id}


# ────────────── Dashboard-side helpers (called by FastAPI endpoints) ──────────────

def list_pending() -> list[dict]:
    """Return all pending confirm requests (called by /api/voice-confirm/pending)."""
    pending = []
    for p in _STATE_DIR.glob("*.json"):
        if p.suffix == ".tmp" or p.name.endswith(".response.json"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("status") == "pending":
                pending.append(data)
        except Exception:
            continue
    # Oldest first
    pending.sort(key=lambda d: d.get("created_at", 0))
    return pending


def post_response(request_id: str, status: str, reason: str = "") -> dict:
    """Called by dashboard when user answers (or denies)."""
    if status not in ("approved", "denied"):
        return {"ok": False, "error": "status deve ser 'approved' ou 'denied'"}
    # Write response file
    resp_path = _STATE_DIR / f"{request_id}.response.json"
    resp_path.write_text(json.dumps({
        "request_id": request_id, "status": status, "reason": reason,
        "responded_at": time.time(),
    }, ensure_ascii=False), encoding="utf-8")
    # Mark request as resolved
    req_path = _request_path(request_id)
    if req_path.exists():
        try:
            data = json.loads(req_path.read_text(encoding="utf-8"))
            data["status"] = status
            data["reason"] = reason
            tmp = req_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(req_path)
        except Exception:
            pass
    return {"ok": True, "request_id": request_id, "status": status}


def cleanup_resolved(older_than_sec: float = 300) -> int:
    """Remove resolved/timeout request files older than `older_than_sec`."""
    cutoff = time.time() - older_than_sec
    removed = 0
    for p in list(_STATE_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("status") in ("approved", "denied", "timeout") and data.get("responded_at", data.get("created_at", 0)) < cutoff:
                p.unlink(missing_ok=True)
                removed += 1
        except Exception:
            continue
    return removed


# Self-test
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        pending = list_pending()
        print(f"Pending: {len(pending)}")
        for p in pending:
            print(f"  - {p['request_id']} intent={p['intent']} prompt='{p['voice_prompt'][:60]}'")
    elif cmd == "cleanup":
        n = cleanup_resolved()
        print(f"Removed {n} resolved files")