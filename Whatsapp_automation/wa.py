"""WhatsApp automation — number is now configurable via env / runtime.

The original file hard-coded the original author's personal phone number,
which is unsafe to ship in a public repo. Replace the value below (or set
the JARVIS_WA_RECIPIENT environment variable) before sending.
"""

import os
import time

import pywhatkit

# Recipient in international format (no "+", no spaces, no dashes).
# You can override this by exporting JARVIS_WA_RECIPIENT in your shell.
RECIPIENT = os.environ.get("JARVIS_WA_RECIPIENT", "0000000000")


def send_msg_wa(*args, **kwargs) -> str:
    """Backwards-compatible wrapper. Prompts for recipient and message."""
    try:
        recipient = (
            kwargs.get("recipient")
            or os.environ.get("JARVIS_WA_RECIPIENT")
            or input("Recipient (intl format, no +): ").strip()
        )
        msg = kwargs.get("message") or input("Message: ").strip()
        return send_wa(msg) if recipient else "No recipient provided."
    except Exception as exc:  # noqa: BLE001
        return f"WhatsApp send failed: {exc}"


def send_wa(msg: str) -> str:
    """Send a WhatsApp message via pywhatkit (uses WhatsApp Web)."""
    recipient = os.environ.get("JARVIS_WA_RECIPIENT", RECIPIENT)
    if recipient == "0000000000":
        return (
            "WhatsApp recipient not configured. "
            "Set JARVIS_WA_RECIPIENT (international format, no '+') "
            "and run again."
        )
    try:
        pywhatkit.sendwhatmsg_instantly(recipient, msg, wait_time=10)
        time.sleep(2)
        return f"WhatsApp message sent to {recipient}"
    except Exception as exc:  # noqa: BLE001
        return f"WhatsApp send failed: {exc}"