"""Conversa por voz (estilo "Gemini Live"), 100% local.

1. Ouvir:  o navegador grava a sua fala e para sozinho quando você fica em silêncio.
2. Entender: o Whisper (versão "base", na CPU) transforma o áudio em texto.
3. Pensar:  o mesmo modelo do Ollama responde, em frases curtas próprias para fala.
4. Falar:   o Piper (voz brasileira "faber") transforma a resposta em áudio.

Tudo roda na CPU para deixar a placa de vídeo livre. Uso de RAM: ~500 MB.
Os modelos de voz (~200 MB) são baixados na primeira vez.
"""
import io
import os
import re
import threading
import wave
from pathlib import Path

import requests

MODELS_DIR = Path(__file__).resolve().parent.parent / "modelos_voz"
WHISPER_SIZE = os.getenv("WHISPER_MODEL", "base")  # tiny = mais rápido, small = mais preciso
PIPER_VOICE = os.getenv("PIPER_VOICE", "pt_BR-faber-medium")
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/{name}/{quality}/{voice}{ext}"

VOICE_SYSTEM = """Você é o CodeLocal em modo de conversa por voz, em português do Brasil.
Responda como numa conversa falada: frases curtas, naturais e diretas, no máximo 3 ou 4 frases.
Não use markdown, listas, emojis, tabelas nem blocos de código (eles não podem ser falados).
Se o usuário pedir código, explique em palavras e diga que ele pode pedir o código no chat de texto."""

_whisper = None
_piper = None
_lock = threading.Lock()


def _installed():
    try:
        import faster_whisper, piper  # noqa: F401
        return True
    except ImportError:
        return False


def status():
    if not _installed():
        return {"available": False, "detail": "instale: pip install -r requirements.txt"}
    return {"available": True, "detail": f"Whisper {WHISPER_SIZE} + Piper {PIPER_VOICE}"}


def _download(url, dest):
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=(15, 300)) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)


def _load():
    global _whisper, _piper
    if _whisper is None:
        from faster_whisper import WhisperModel
        # int8 na CPU: rápido e com pouca memória
        _whisper = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8",
                                download_root=str(MODELS_DIR / "whisper"))
    if _piper is None:
        from piper import PiperVoice
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        lang, name, quality = PIPER_VOICE.split("-")
        onnx = MODELS_DIR / f"{PIPER_VOICE}.onnx"
        for ext in (".onnx", ".onnx.json"):
            target = MODELS_DIR / f"{PIPER_VOICE}{ext}"
            if not target.exists():
                _download(PIPER_URL.format(name=name, quality=quality, voice=PIPER_VOICE, ext=ext), target)
        _piper = PiperVoice.load(str(onnx))
    return _whisper, _piper


def _wav_to_array(wav_bytes):
    """WAV (o navegador já manda em 16 kHz mono) → números que o Whisper entende. Sem ffmpeg."""
    import numpy as np
    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate, channels, frames = w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != 16000:  # reamostragem simples, caso chegue em outra taxa
        audio = np.interp(np.linspace(0, len(audio), int(len(audio) * 16000 / rate), endpoint=False),
                          np.arange(len(audio)), audio).astype(np.float32)
    return audio


def transcribe(wav_bytes):
    """Áudio WAV → texto em português."""
    with _lock:
        whisper, _ = _load()
        segments, _info = whisper.transcribe(_wav_to_array(wav_bytes), language="pt", beam_size=1,
                                             vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()


def clean_for_speech(text):
    """Remove o que não faz sentido falar em voz alta."""
    text = re.sub(r"```.*?```", " (o código está no chat) ", text, flags=re.S)
    text = re.sub(r"\[\d+\]", "", text)                 # marcações de fonte [1]
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def speak(text):
    """Texto → áudio WAV (bytes)."""
    with _lock:
        _, voice = _load()
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            if hasattr(voice, "synthesize_wav"):   # piper-tts 1.3+
                voice.synthesize_wav(clean_for_speech(text), wav)
            else:                                  # versões antigas
                voice.synthesize(clean_for_speech(text), wav)
        return buffer.getvalue()
