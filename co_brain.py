"""Co_brain: the orchestrator that reads user commands from input.txt and
dispatches them to the right module.

Notes from the cleanup pass:
- The original `while True` could spin at 100% CPU if `input.txt` was empty
  and never changed. We now use a small `time.sleep(1)` and respect a
  KeyboardInterrupt.
- `Main_Brain` was renamed in Brain/brain.py; we import it as `BrainMain`
  so the rest of the file keeps the original call sites working.
- Many optional features (mic, WhatsApp, vision, mobile camera) are kept
  behind try/except so a single broken module does not crash the whole
  assistant.
"""

import os
import sys
import threading
import time
import traceback

from Automation.Automation_Brain import Auto_main_brain, clear_file
from Brain.brain import Main_Brain as BrainMain
from Data.DLG_Data import online_dlg, offline_dlg
from Features.br_persentage import check_br_persentage
from Features.check_running_app import check_running_app
from Features.create_file import create_file
from TextToImage.gen_image import generate_image
from TextToSpeech.Fast_DF_TTS import speak
from Time_Operations.brain import input_manage, input_manage_Alam
from Weather_Check.check_weather import get_weather_by_address

# Mic-related Features are optional — they need pyaudio.
try:
    from Features.mike_health import mike_health
except Exception:  # noqa: BLE001
    def mike_health(*a, **kw):
        return "Mic health check unavailable (pyaudio not installed)."

try:
    from Features.speaker_health import speaker_health_test
except Exception:  # noqa: BLE001
    def speaker_health_test(*a, **kw):
        return "Speaker health check unavailable (pyaudio not installed)."

try:
    from Features.set_br import set_brightness_windows
except Exception:  # noqa: BLE001
    def set_brightness_windows(*a, **kw):
        return "Brightness control unavailable."

try:
    from Features.set_get_volume import get_volume_windows, set_volume_windows
except Exception:  # noqa: BLE001
    def get_volume_windows(*a, **kw):
        return "Volume control unavailable."

    def set_volume_windows(*a, **kw):
        return "Volume control unavailable."

# Optional / requires microphone
try:
    from NetHyTechSTT.listen import listen
except Exception:  # noqa: BLE001
    listen = None
    print("[co_brain] NetHyTechSTT.listen not available (mic features disabled).")

try:
    import random as _random
    from Vision.Vbrain import (
        capture_image_and_save as _capture_pc,
        encode_image_to_base64 as _encode_pc,
        vision_brain as _vision_pc,
    )
    from Vision.MVbrain import (
        capture_image_and_save as _capture_mobile,
        encode_image_to_base64 as _encode_mobile,
        mobile_vision_brain as _vision_mobile,
    )

    def capture_image_and_save(*a, **kw):
        return _capture_pc(*a, **kw)

    def encode_image_to_base64(*a, **kw):
        return _encode_pc(*a, **kw)

    def vision_brain(*a, **kw):
        return _vision_pc(*a, **kw)

    def mobile_vision_brain(*a, **kw):
        return _vision_mobile(*a, **kw)
except Exception:  # noqa: BLE001
    print("[co_brain] Vision modules not available (vision features disabled).")

    def capture_image_and_save(*a, **kw):
        return False

    def encode_image_to_base64(*a, **kw):
        return ""

    def vision_brain(*a, **kw):
        return "Vision module unavailable."

    def mobile_vision_brain(*a, **kw):
        return "Vision module unavailable."

try:
    from Whatsapp_automation.wa import send_msg_wa
except Exception:  # noqa: BLE001
    def send_msg_wa(*a, **kw):  # type: ignore[no-redef]
        return "WhatsApp automation unavailable."

INPUT_FILE = "input.txt"
LOG_FILE = "log.txt"

NUMBERS = ["1:", "2:", "3:", "4:", "5:", "6:", "7:", "8:", "9:"]
SPL_NUMBERS = ["11:", "12:"]


def _log(line: str) -> None:
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write("\n" + line)
    except Exception:
        pass


def _normalize_time_tokens(text: str) -> str:
    text = text.replace(" p.m.", "PM").replace(" a.m.", "AM")
    for number in NUMBERS:
        if number in text and number not in SPL_NUMBERS:
            text = text.replace(number, f"0{number}")
    return text


def _read_input() -> str:
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def _write_input(content: str) -> None:
    try:
        with open(INPUT_FILE, "w", encoding="utf-8") as fh:
            fh.write(content)
    except Exception as exc:
        print(f"[co_brain] could not clear {INPUT_FILE}: {exc}")


def check_inputs():
    """Main dispatcher loop. Reads input.txt, dispatches to handlers."""
    output_text = ""
    idle_turns = 0
    MAX_IDLE_TURNS = 1000  # safety cap so we never run forever

    try:
        while True:
            user_input = _read_input()
            if not user_input:
                idle_turns += 1
                if idle_turns >= MAX_IDLE_TURNS:
                    print(f"[co_brain] idle for {MAX_IDLE_TURNS} turns, exiting")
                    break
                time.sleep(1)
                continue

            # Got something new to process.
            idle_turns = 0
            if user_input == output_text:
                # Already handled this same content — just wait.
                time.sleep(1)
                continue
            output_text = user_input

            try:
                _dispatch(user_input)
            except Exception as exc:  # noqa: BLE001
                print(f"[co_brain] handler crashed: {exc}")
                traceback.print_exc()

            _write_input("")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[co_brain] interrupted by user")


def _dispatch(output_text: str) -> None:
    """Run the appropriate handler for a single user command."""
    out = output_text.strip()
    lower = out.lower()

    if lower in {"exit", "quit", "bye"}:
        print("[JARVIS] Goodbye.")
        # Stop the loop by raising; check_inputs catches KeyboardInterrupt.
        raise KeyboardInterrupt

    # ---- time / alarms ----
    if lower.startswith("tell me"):
        normalized = _normalize_time_tokens(out)
        input_manage(normalized)
        clear_file()
        return

    if lower.startswith("set alarm"):
        normalized = _normalize_time_tokens(out)
        input_manage_Alam(normalized)
        clear_file()
        return

    # ---- general chat (Phind AI) ----
    if "jarvis" in lower:
        _log(f"You : {out}")
        response = BrainMain(out)
        _log(f"jarvis : {response}")
        speak(response)
        return

    # ---- file creation ----
    if lower.startswith("create") and "file" in lower:
        create_file(out)
        return

    # ---- vision: webcam ----
    if lower in {"what is this", "what can you see"}:
        image_path = "captured_image.png"
        if capture_image_and_save(image_path):
            encoded = encode_image_to_base64(image_path)
            speak(vision_brain(encoded))
        else:
            speak("I could not capture an image from the webcam.")
        return

    # ---- vision: phone camera (DroidCam / IP webcam) ----
    if (
        "what is in front of mobile camera" in lower
        or "what can you see use mobile camera" in lower
    ):
        image_path = "captured_image.png"
        if capture_image_and_save(image_path):
            encoded = encode_image_to_base64(image_path)
            speak(mobile_vision_brain(encoded))
        else:
            speak("I could not reach the mobile camera.")
        return

    # ---- weather ----
    if "check weather" in lower:
        city = out.lower().replace("check weather in", "").strip()
        speak(get_weather_by_address(city))
        return

    # ---- whatsapp ----
    if "send message on whatsapp" in lower:
        speak(send_msg_wa())
        return

    # ---- image generation ----
    if lower.startswith("generate image"):
        prompt = out[len("generate image"):].strip()
        result = generate_image(prompt)
        speak("Image generated successfully." if result.startswith("Image generated") else result)
        return

    # ---- system health ----
    if "check mike" in lower or "check microphone" in lower:
        mike_health()
        return
    if "check speaker health" in lower or "check speaker" in lower:
        speaker_health_test()
        return
    if "check brightness percentage" in lower:
        check_br_persentage()
        return
    if lower.startswith("set brightness percentage"):
        try:
            value = int(out.lower().replace("set brightness percentage", "").strip())
            set_brightness_windows(value)
        except ValueError:
            speak("Invalid brightness value.")
        return
    if "check volume level" in lower:
        get_volume_windows()
        return
    if lower.startswith("set volume level"):
        try:
            value = int(out.lower().replace("set volume level", "").replace("%", "").strip())
            set_volume_windows(value)
        except ValueError:
            speak("Invalid volume value.")
        return
    if "check running application" in lower:
        check_running_app()
        return

    # ---- fallback to automation brain ----
    Auto_main_brain(out)


def Jarvis():
    """Entry point: starts mic listener (if available) and dispatcher."""
    clear_file()
    threads = []

    if listen is not None:
        t_listen = threading.Thread(target=listen, daemon=True)
        threads.append(t_listen)
        t_listen.start()

    t_dispatch = threading.Thread(target=check_inputs, daemon=True)
    threads.append(t_dispatch)
    t_dispatch.start()

    # Wait until both threads finish (Ctrl+C / KeyboardInterrupt will exit).
    for t in threads:
        t.join()


if __name__ == "__main__":
    try:
        Jarvis()
    except KeyboardInterrupt:
        print("\nExiting Jarvis.")
        sys.exit(0)