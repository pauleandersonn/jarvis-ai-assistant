"""Transcreve um WAV usando SAPI5 Speech Recognition (Windows nativo)."""
import sys
import win32com.client
import pythoncom

wav_path = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\paule\Projects\jarvis-ai-assistant\TextToSpeech\tmp_audio\jarvis_1784264968547.wav'

pythoncom.CoInitialize()
try:
    # Tenta com o reconhecedor in-process
    recognizer = win32com.client.Dispatch("SAPI.SpInprocRecognizer")
    recognizer.AudioInputStream = win32com.client.Dispatch("SAPI.SpFileStream")
    recognizer.AudioInputStream.Open(wav_path, 3)  # 3 = SSFMOpenForRead
    recognizer.Recognizer = win32com.client.Dispatch("SAPI.SpInprocRecognizer")
except Exception:
    # Fallback: usa SAPI nativo do Windows
    print("Inproc nao disponivel, mostrando apenas metadados do arquivo:")
    import os, struct
    size = os.path.getsize(wav_path)
    with open(wav_path, 'rb') as f:
        h = f.read(44)
    sr = struct.unpack('<I', h[24:28])[0]
    ch = struct.unpack('<H', h[22:24])[0]
    bps = struct.unpack('<H', h[34:36])[0]
    dur = (size - 44) / (sr * ch * bps / 8)
    print(f'File: {wav_path}')
    print(f'Size: {size} bytes')
    print(f'Duration: {dur:.2f} seconds')
    sys.exit(0)

print('Setup ok, recognition nao implementado completamente. Use SpeechRecognition lib.')