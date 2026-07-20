"""Email action — ler inbox, ler mensagem especifica, enviar email.

Wrapper sobre a skill `google-workspace` (Gmail API). Toda chamada passa pelo
google_api.py que cuida do OAuth token + refresh automatico.

Funcoes expostas:
  - search_emails(query, max_results)  -> lista de dicts (id, from, subject, snippet, date)
  - get_email(msg_id)                  -> dict com body completo
  - send_email(to, subject, body, html=False, from_alias=None)
  - summarize_inbox(query, max_results) -> string pronta pra TTS

Todas retornam dict com `"ok": bool` + payload ou `"error": str`.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

LOG = logging.getLogger("jarvis.actions.email")

# Resolve path da skill google-workspace. Segue convencao dos outros actions:
# workspace em ~/.hermes/skills/productivity/google-workspace/scripts/
_GAPI_PATH = (
    Path.home()
    / "AppData"
    / "Local"
    / "hermes"
    / "skills"
    / "productivity"
    / "google-workspace"
    / "scripts"
    / "google_api.py"
)

# Tokens de exibicao
_DATE_FMT_HUMAN = "%d/%m %H:%M"


def _run_gapi(*args: str, timeout: int = 30) -> tuple[bool, str]:
    """Roda google_api.py com os args dados. Retorna (ok, stdout_or_stderr)."""
    if not _GAPI_PATH.exists():
        return False, f"google-workspace skill nao encontrada em {_GAPI_PATH}"

    cmd = [sys.executable, str(_GAPI_PATH), *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "unknown error").strip()
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, f"timeout apos {timeout}s"
    except Exception as e:
        return False, f"execucao falhou: {e}"


def search_emails(query: str = "is:unread", max_results: int = 5) -> dict:
    """Busca emails na inbox. Query usa sintaxe Gmail (is:unread, from:, newer_than:).

    Retorna {"ok": True, "emails": [...]} ou {"ok": False, "error": "..."}.
    """
    ok, out = _run_gapi("gmail", "search", query, "--max", str(max_results))
    if not ok:
        return {"ok": False, "error": out}
    try:
        emails = json.loads(out)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"resposta nao e JSON: {out[:200]}"}

    if not isinstance(emails, list):
        return {"ok": False, "error": f"formato inesperado: {type(emails).__name__}"}

    return {"ok": True, "query": query, "count": len(emails), "emails": emails}


def get_email(msg_id: str) -> dict:
    """Le o corpo completo de uma mensagem por ID."""
    if not msg_id:
        return {"ok": False, "error": "msg_id vazio"}
    ok, out = _run_gapi("gmail", "get", msg_id)
    if not ok:
        return {"ok": False, "error": out}
    try:
        msg = json.loads(out)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"resposta nao e JSON: {out[:200]}"}
    return {"ok": True, "email": msg}


def send_email(
    to: str,
    subject: str,
    body: str,
    html: bool = False,
    from_alias: str | None = None,
) -> dict:
    """Envia email.

    CUIDADO: ENVIA DE VERDADE. Usar com confirmacao do usuario.
    """
    if not to or "@" not in to:
        return {"ok": False, "error": "destinatario invalido (precisa ter @)"}
    if not subject.strip():
        return {"ok": False, "error": "assunto vazio"}
    if not body.strip():
        return {"ok": False, "error": "corpo vazio"}

    args = ["gmail", "send", "--to", to, "--subject", subject, "--body", body]
    if html:
        args.append("--html")
    if from_alias:
        args.extend(["--from", from_alias])

    ok, out = _run_gapi(*args, timeout=30)
    if not ok:
        return {"ok": False, "error": out}
    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        # Sucesso pode vir como string simples
        return {"ok": True, "raw_response": out[:200]}
    return {"ok": result.get("status") == "sent", "result": result}


# ────────────── Summarizers (TTS-friendly) ──────────────

def summarize_inbox(query: str = "is:unread", max_results: int = 5) -> str:
    """Retorna string curta, natural pra TTS, com os N emails mais recentes."""
    res = search_emails(query=query, max_results=max_results)
    if not res.get("ok"):
        return f"Nao consegui ler a inbox: {res.get('error', 'erro desconhecido')}"

    emails = res.get("emails", [])
    if not emails:
        return "Nenhum email encontrado."

    # CORRECAO: usar "senhor" (sem cedilha) pra evitar bug cp1252 do Windows.
    lines = [f"O senhor tem {len(emails)} email(s)."]  # noqa: E501
    for i, e in enumerate(emails, 1):
        sender = (e.get("from") or "remetente desconhecido").split("<")[0].strip().strip('"')
        subject = e.get("subject") or "(sem assunto)"
        lines.append(f"Email {i}: de {sender}, assunto {subject}.")
    return " ".join(lines)


def summarize_email(msg_id: str) -> str:
    """Le uma mensagem e retorna resumo TTS-friendly."""
    res = get_email(msg_id)
    if not res.get("ok"):
        return f"Nao consegui abrir o email: {res.get('error')}"
    e = res["email"]
    sender = (e.get("from") or "remetente desconhecido").split("<")[0].strip().strip('"')
    subject = e.get("subject") or "(sem assunto)"
    body = (e.get("body") or "").strip()
    # Limita corpo pra nao explodir TTS (max ~600 chars)
    if len(body) > 600:
        body = body[:600].rsplit(".", 1)[0] + "..."
    return f"Email de {sender}, assunto {subject}. {body}"


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if cmd == "summary":
        q = sys.argv[2] if len(sys.argv) > 2 else "is:unread"
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        print(summarize_inbox(q, n))
    elif cmd == "search":
        q = sys.argv[2] if len(sys.argv) > 2 else "is:unread"
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        r = search_emails(q, n)
        print(json.dumps(r, indent=2, ensure_ascii=False))
    elif cmd == "send":
        # send <to> <subject> <body>
        if len(sys.argv) < 5:
            print("uso: send <to> <subject> <body>")
        else:
            r = send_email(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
            print(json.dumps(r, indent=2, ensure_ascii=False))