"""Standalone TTS test — run this to confirm SAPI5 is producing audio.

Usage:
    python test_tts_manual.py
    python test_tts_manual.py "Seu texto aqui"
"""

import sys

import win32com.client
import pythoncom


def main():
    pythoncom.CoInitialize()
    text = " ".join(sys.argv[1:]) or (
        "Teste de audio. Se você está ouvindo isso, o sistema "
        "de voz do Windows está funcionando corretamente."
    )

    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    speaker.Rate = 0  # -10..+10 (default 0)
    speaker.Volume = 100  # 0..100

    voices = speaker.GetVoices()
    # Prefer Portuguese voice if available.
    pt_idx = 0
    for i in range(voices.Count):
        if "Portuguese" in voices.Item(i).GetDescription():
            pt_idx = i
            break
    speaker.Voice = voices.Item(pt_idx)
    print(f"Voice: {speaker.Voice.GetDescription()}")
    print(f"Rate:  {speaker.Rate}")
    print(f"Volume: {speaker.Volume}")
    print()
    print(f"Saying: {text}")
    print()
    # 1 = SVSFIsXML / 0 = sync (wait until done)
    speaker.Speak(text, 0)
    print("Done.")


if __name__ == "__main__":
    main()