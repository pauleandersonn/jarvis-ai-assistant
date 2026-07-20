"""JARVIS MCP server — exposes JARVIS actions as MCP tools.

Transports:
  - stdio (for local CLI integration)
  - HTTP/SSE on port 8789 (for Hermes gateway / Open WebUI / other clients)

Tools exposed (9 total):

  READ (no confirmation):
    - jarvis_list_emails(query, max_results)
    - jarvis_read_email(msg_id)
    - jarvis_list_calendar(start, end, max_results)
    - jarvis_ask_brain(text)
    - jarvis_read_hermes_context(query)

  WRITE (require voice confirmation in the JARVIS dashboard):
    - jarvis_send_email(to, subject, body)
    - jarvis_create_event(summary, start_iso, end_iso, location, description, attendees)
    - jarvis_delete_event(event_id)
    - jarvis_set_reminder(message, minutes)
    - jarvis_open_app(query)

Each write tool returns:
  - {"status": "executed", "result": {...}} on success
  - {"status": "pending_voice_confirm", "request_id": "...",
     "voice_prompt": "...", "intent": "..."} on confirm request
  - {"status": "denied", "reason": "..."} if user said no
  - {"status": "timeout"} if no response in 30s

The confirm flow uses Brain/voice_confirm.py which writes a JSON to
dashboard state; the dashboard JS polls /api/voice-confirm/pending and
when a request exists, it speaks the prompt via TTS and listens for
response via webkitSpeechRecognition.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

# Make jarvis package importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

LOG = logging.getLogger("jarvis.mcp")

# Import Brain actions lazily so MCP doesn't crash if deps missing
def _actions():
    from Brain.actions import (
        search_emails, get_email, send_email,
        list_events, create_event, delete_event,
        add_reminder, open_app,
    )
    return {
        "search_emails": search_emails,
        "get_email": get_email,
        "send_email": send_email,
        "list_events": list_events,
        "create_event": create_event,
        "delete_event": delete_event,
        "add_reminder": add_reminder,
        "open_app": open_app,
    }


def _confirm(intent: str, voice_prompt: str, action_payload: dict,
             timeout: float = 30.0) -> dict:
    """Ask for voice confirmation. Returns the action result or denial."""
    from Brain.voice_confirm import request_confirmation
    return request_confirmation(
        intent=intent,
        voice_prompt=voice_prompt,
        action_payload=action_payload,
        timeout=timeout,
    )


# ────────────── Tool implementations ──────────────

def tool_list_emails(query: str = "is:unread", max_results: int = 5) -> str:
    """List recent emails (read-only, no confirmation)."""
    a = _actions()
    r = a["search_emails"](query=query, max_results=max_results)
    # Return summary only — DON'T include full bodies (privacy + token bloat).
    if not r.get("ok"):
        return json.dumps({"status": "error", "error": r.get("error")}, ensure_ascii=False)
    emails = r.get("emails", [])
    safe = [
        {"id": e.get("id"), "from": e.get("from"), "subject": e.get("subject"),
         "date": e.get("date"), "snippet": (e.get("snippet") or "")[:200]}
        for e in emails
    ]
    return json.dumps({"status": "ok", "count": len(safe), "emails": safe},
                      ensure_ascii=False)


def tool_read_email(msg_id: str) -> str:
    """Read a specific email by id (read-only, returns body up to 600 chars)."""
    a = _actions()
    r = a["get_email"](msg_id)
    if not r.get("ok"):
        return json.dumps({"status": "error", "error": r.get("error")}, ensure_ascii=False)
    e = r["email"]
    body = (e.get("body") or "").strip()
    if len(body) > 600:
        body = body[:600].rsplit(".", 1)[0] + "..."
    return json.dumps({
        "status": "ok",
        "email": {
            "id": e.get("id"),
            "from": e.get("from"),
            "subject": e.get("subject"),
            "date": e.get("date"),
            "body": body,
        },
    }, ensure_ascii=False)


def tool_list_calendar(start: str = "", end: str = "", max_results: int = 10) -> str:
    """List calendar events (read-only)."""
    a = _actions()
    r = a["list_events"](start=start or None, end=end or None, max_results=max_results)
    if not r.get("ok"):
        return json.dumps({"status": "error", "error": r.get("error")}, ensure_ascii=False)
    return json.dumps({"status": "ok", "count": r.get("count", 0), "events": r.get("events", [])},
                      ensure_ascii=False)


def tool_ask_brain(text: str) -> str:
    """Send a question to the JARVIS brain (Claude via llm_client)."""
    from Brain.brain import Main_Brain
    answer = Main_Brain(text)
    return json.dumps({"status": "ok", "answer": answer}, ensure_ascii=False)


def tool_read_hermes_context(query: str = "") -> str:
    """Read shared Hermes memory (filtered by query if provided)."""
    from Brain.hermes_bridge import ask_hermes_context
    out = ask_hermes_context(text=query, limit=4000)
    return json.dumps({"status": "ok", "context": out}, ensure_ascii=False)


def tool_send_email(to: str, subject: str, body: str) -> str:
    """Send email — requires voice confirmation."""
    prompt = f"Confirmar envio de email? Para: {to}. Assunto: {subject}."
    result = _confirm(
        intent="send_email",
        voice_prompt=prompt,
        action_payload={"to": to, "subject": subject, "body": body},
    )
    if result.get("status") != "approved":
        return json.dumps(result, ensure_ascii=False)
    # Execute
    a = _actions()
    r = a["send_email"](to=to, subject=subject, body=body)
    return json.dumps({"status": "executed", "ok": r.get("ok"),
                       "result": r.get("result"), "error": r.get("error")},
                      ensure_ascii=False)


def tool_create_event(summary: str, start_iso: str, end_iso: str,
                      location: str = "", description: str = "",
                      attendees: str = "") -> str:
    """Create calendar event — requires voice confirmation."""
    parts = [f"Confirmar criação de evento? {summary}.",
             f"De {start_iso} até {end_iso}."]
    if location:
        parts.append(f"Local: {location}.")
    prompt = " ".join(parts)
    att_list = [a.strip() for a in attendees.split(",") if a.strip()] if attendees else None
    result = _confirm(
        intent="create_event",
        voice_prompt=prompt,
        action_payload={
            "summary": summary, "start_iso": start_iso, "end_iso": end_iso,
            "location": location or None, "description": description or None,
            "attendees": att_list,
        },
    )
    if result.get("status") != "approved":
        return json.dumps(result, ensure_ascii=False)
    a = _actions()
    r = a["create_event"](summary=summary, start_iso=start_iso, end_iso=end_iso,
                          location=location or None, description=description or None,
                          attendees=att_list)
    return json.dumps({"status": "executed", "ok": r.get("ok"),
                       "event": r.get("event"), "error": r.get("error")},
                      ensure_ascii=False)


def tool_delete_event(event_id: str) -> str:
    """Delete calendar event — requires voice confirmation."""
    prompt = f"Confirmar exclusão do evento de ID {event_id}?"
    result = _confirm(
        intent="delete_event",
        voice_prompt=prompt,
        action_payload={"event_id": event_id},
    )
    if result.get("status") != "approved":
        return json.dumps(result, ensure_ascii=False)
    a = _actions()
    r = a["delete_event"](event_id)
    return json.dumps({"status": "executed", "ok": r.get("ok"), "error": r.get("error")},
                      ensure_ascii=False)


def tool_set_reminder(message: str, minutes: int) -> str:
    """Set reminder N minutes from now — requires voice confirmation."""
    prompt = f"Confirmar lembrete? {message}, em {minutes} minutos."
    result = _confirm(
        intent="set_reminder",
        voice_prompt=prompt,
        action_payload={"message": message, "minutes": minutes},
    )
    if result.get("status") != "approved":
        return json.dumps(result, ensure_ascii=False)
    a = _actions()
    r = a["add_reminder"](message, minutes)
    return json.dumps({"status": "executed", "ok": r.get("ok"),
                       "task_name": r.get("task_name"), "error": r.get("error")},
                      ensure_ascii=False)


def tool_open_app(query: str) -> str:
    """Open an application by friendly name — requires voice confirmation."""
    prompt = f"Confirmar abertura de {query}?"
    result = _confirm(
        intent="open_app",
        voice_prompt=prompt,
        action_payload={"query": query},
    )
    if result.get("status") != "approved":
        return json.dumps(result, ensure_ascii=False)
    a = _actions()
    r = a["open_app"](query)
    return json.dumps({"status": "executed", "ok": r.get("ok"),
                       "launched": r.get("launched"), "error": r.get("error")},
                      ensure_ascii=False)


# ────────────── FastMCP wiring ──────────────

def build_server():
    """Build FastMCP instance with all tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise RuntimeError(
            "MCP not installed. Run: pip install mcp"
        )

    mcp = FastMCP(
        "JARVIS",
        instructions=(
            "JARVIS is Pauleanderson's personal AI assistant. "
            "Read-only tools return data without confirmation. "
            "Write tools require voice confirmation in the JARVIS dashboard. "
            "When a write tool returns status='pending_voice_confirm', the user "
            "must say yes/no to the JARVIS dashboard microphone within 30 seconds. "
            "For long outputs (email bodies, calendar lists), prefer the *_summary "
            "tools that return TTS-friendly strings instead of raw JSON."
        ),
    )

    # READ tools
    mcp.add_tool(
        name="jarvis_list_emails",
        description="List recent emails matching a Gmail query (default: is:unread). "
                    "Returns id, from, subject, date, snippet. Does NOT include bodies.",
        fn=tool_list_emails,
    )
    mcp.add_tool(
        name="jarvis_read_email",
        description="Read a specific email by its Gmail message ID. "
                    "Returns up to 600 chars of body.",
        fn=tool_read_email,
    )
    mcp.add_tool(
        name="jarvis_list_calendar",
        description="List calendar events between ISO 8601 start/end timestamps. "
                    "Empty start/end defaults to next 7 days.",
        fn=tool_list_calendar,
    )
    mcp.add_tool(
        name="jarvis_ask_brain",
        description="Send a free-form question to the JARVIS brain (Claude via llm_client). "
                    "Returns the AI's answer as text.",
        fn=tool_ask_brain,
    )
    mcp.add_tool(
        name="jarvis_read_hermes_context",
        description="Read the shared Hermes memory (~/.hermes/memories/). "
                    "Optional query filters relevant context.",
        fn=tool_read_hermes_context,
    )

    # WRITE tools (require voice confirmation)
    mcp.add_tool(
        name="jarvis_send_email",
        description="Send an email. REQUIRES voice confirmation in JARVIS dashboard. "
                    "Args: to (email), subject, body.",
        fn=tool_send_email,
    )
    mcp.add_tool(
        name="jarvis_create_event",
        description="Create a Google Calendar event. REQUIRES voice confirmation. "
                    "Args: summary, start_iso, end_iso, optional location/description/attendees.",
        fn=tool_create_event,
    )
    mcp.add_tool(
        name="jarvis_delete_event",
        description="Delete a Google Calendar event by ID. REQUIRES voice confirmation.",
        fn=tool_delete_event,
    )
    mcp.add_tool(
        name="jarvis_set_reminder",
        description="Set a JARVIS reminder N minutes from now. REQUIRES voice confirmation. "
                    "Args: message, minutes (1..10080).",
        fn=tool_set_reminder,
    )
    mcp.add_tool(
        name="jarvis_open_app",
        description="Open an application by name (chrome, vscode, spotify, etc). "
                    "REQUIRES voice confirmation.",
        fn=tool_open_app,
    )

    return mcp


# ────────────── Entrypoints ──────────────

def run_stdio():
    """Run MCP server over stdio (for direct CLI integration)."""
    server = build_server()
    server.run(transport="stdio")


def run_http(host: str = "127.0.0.1", port: int = 8789):
    """Run MCP server over HTTP/SSE (for Hermes / Open WebUI)."""
    import uvicorn
    from mcp.server.fastmcp import FastMCP
    server = build_server()
    # FastMCP exposes a Starlette app under .streamable_http_app() or .sse_app()
    try:
        app = server.streamable_http_app()
    except AttributeError:
        app = server.sse_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8789)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.transport == "stdio":
        run_stdio()
    else:
        run_http(host=args.host, port=args.port)