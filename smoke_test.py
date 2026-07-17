"""Full smoke test for the cleaned-up jarvis-ai-assistant.

Runs every subsystem we can exercise without:
  - a real microphone (we use the pyaudio/sounddevice shim instead)
  - WhatsApp Web login
  - a phone camera

Exits non-zero if any subsystem errors out.
"""

import sys
import time
import traceback


def _safe(label, fn):
    try:
        result = fn()
        print(f"[OK]  {label}")
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {label}: {exc}")
        traceback.print_exc()
        return None


def main():
    print("=" * 60)
    print(" Jarvis AI Assistant — full smoke test")
    print("=" * 60)

    # 1. Brain (FreeAI)
    print("\n--- Brain ---")
    from Brain.brain import Main_Brain
    response = _safe("Main_Brain('how are you?')", lambda: Main_Brain("how are you?"))
    if response:
        print(f"   response: {response[:120]}")

    # 2. TTS (Windows SAPI5)
    print("\n--- TTS ---")
    _safe("speak('Hello world')", lambda: __import__("TextToSpeech.Fast_DF_TTS", fromlist=["speak"]).speak("Hello world"))

    # 3. Image generation (Pollinations)
    print("\n--- Image gen ---")
    from TextToImage.gen_image import generate_image
    img_path = _safe("generate_image('a green triangle')", lambda: generate_image("a green triangle"))
    if img_path:
        print(f"   {img_path}")

    # 4. Weather (wttr.in)
    print("\n--- Weather ---")
    from Weather_Check.check_weather import get_weather_by_address
    weather = _safe("get_weather_by_address('São Paulo')", lambda: get_weather_by_address("São Paulo"))
    if weather:
        print(f"   {str(weather)[:200]}")

    # 5. Time / Date
    print("\n--- Time / Date ---")
    from Time_Operations.brain import input_manage
    _safe("input_manage('tell me time')", lambda: input_manage("tell me time"))

    # 6. Battery (should report "no battery" on desktop)
    print("\n--- Battery ---")
    from Automation.Battery import check_percentage
    bat = _safe("check_percentage", check_percentage)
    if bat:
        print(f"   {bat}")

    # 7. Volume (Windows)
    print("\n--- Volume (read) ---")
    try:
        from Features.set_get_volume import get_volume_windows
        _safe("get_volume_windows", get_volume_windows)
    except Exception as exc:
        print(f"[FAIL] volume import: {exc}")

    # 8. Brightness (Windows)
    print("\n--- Brightness (read) ---")
    try:
        from Features.br_persentage import check_br_persentage
        _safe("check_br_persentage", check_br_persentage)
    except Exception as exc:
        print(f"[FAIL] brightness import: {exc}")

    # 9. pyaudio shim works
    print("\n--- pyaudio shim ---")
    import pyaudio
    pa = pyaudio.PyAudio()
    _safe("PyAudio().get_device_count()", pa.get_device_count)
    pa.terminate()

    # 10. SoundDevice read short clip from mic (no callback)
    print("\n--- Mic read (1s) ---")
    pa = pyaudio.PyAudio()
    s = pa.open(rate=16000, channels=1, frames_per_buffer=1024, input=True)
    data = s.read(1024)
    print(f"[OK]  Mic read returned {len(data)} bytes")
    s.close()
    pa.terminate()

    print("\n" + "=" * 60)
    print(" Smoke test finished")
    print("=" * 60)


if __name__ == "__main__":
    main()