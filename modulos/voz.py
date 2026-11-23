"""Conversa por voz (estilo "Gemini Live"), 100% local.

1. Ouvir:  o navegador grava a sua fala e para sozinho quando você fica em silêncio.
2. Entender: o Whisper (versão "base", na CPU) transforma o áudio em texto.
3. Pensar:  o mesmo modelo do Ollama responde, em frases curtas próprias para fala.
4. Falar:   o Piper (voz brasileira "faber") transforma a resposta em áudio.

Tudo roda na CPU para deixar a placa de vídeo livre. Uso de RAM: ~500 MB.
Os modelos de voz (~200 MB) são baixados na primeira vez.
"""
import html  # Decodifica entidades HTML (&amp;, &nbsp;, etc.) antes da fala
import io  # Manipula buffers de áudio WAV diretamente na memória
import os  # Lê variáveis de ambiente para configurar modelos de voz
import re  # Expressões regulares para limpar markdown, HTML e links da fala
import threading  # Serializa o acesso ao Whisper e ao Piper entre requisições
import wave  # Lê e grava arquivos de áudio no formato WAV padrão
from pathlib import Path  # Manipulação portável de caminhos de pastas/arquivos

import requests  # Faz download dos arquivos de voz do Piper no Hugging Face

MODELS_DIR = Path(__file__).resolve().parent.parent / "modelos_voz"  # Pasta onde ficam salvos Whisper e Piper
WHISPER_SIZE = os.getenv("WHISPER_MODEL", "base")  # Tamanho do Whisper (tiny = rápido, base = equilibrado, small = preciso)
PIPER_VOICE = os.getenv("PIPER_VOICE", "pt_BR-faber-medium")  # Nome da voz brasileira do Piper TTS
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/{name}/{quality}/{voice}{ext}"  # URL de download do Piper

# Prompt de sistema usado pelo LLM em conversas livres por voz (sem busca web)
VOICE_SYSTEM = """Você é o CodeLocal em modo de conversa por voz, em português do Brasil.
Responda como numa conversa falada: frases curtas, naturais e diretas, no máximo 3 ou 4 frases.
Não use markdown, listas, emojis, tabelas, tags HTML nem blocos de código (eles não podem ser falados).
Se o usuário pedir código, explique em palavras e diga que ele pode pedir o código no chat de texto."""

# Prompt de sistema usado pelo LLM quando a conversa por voz inclui resultados de pesquisa na internet
VOICE_SEARCH_SYSTEM = """Você é um assistente de voz em português do Brasil respondendo com base em uma pesquisa na internet.
Resuma a resposta com suas próprias palavras em 2 a 4 frases curtas, naturais e diretas, prontas para serem faladas em voz alta.
Nunca copie texto bruto de páginas web, nunca gere HTML, markdown, listas numeradas, tópicos, links ou citações como [1]."""

_whisper = None  # Cache global do modelo Whisper (carregado sob demanda)
_piper = None  # Cache global do modelo Piper TTS (carregado sob demanda)
_lock = threading.Lock()  # Trava para evitar uso simultâneo dos modelos na CPU


def _installed():  # Verifica se faster-whisper e piper-tts estão instalados no ambiente
    try:  # Tenta importar ambas as bibliotecas
        import faster_whisper, piper  # noqa: F401  # Importação apenas para checagem
        return True  # Dependências de voz presentes
    except ImportError:  # Se alguma biblioteca estiver faltando
        return False  # Indica que o módulo de voz está indisponível


def status():  # Retorna o status do módulo de voz para o endpoint /api/status
    if not _installed():  # Se as dependências não estiverem instaladas
        return {"available": False, "detail": "instale: pip install -r requirements.txt"}  # Mensagem de orientação
    return {"available": True, "detail": f"Whisper {WHISPER_SIZE} + Piper {PIPER_VOICE}"}  # Módulo pronto para uso


def _download(url, dest):  # Baixa um arquivo grande em partes e salva de forma atômica
    tmp = dest.with_suffix(dest.suffix + ".part")  # Arquivo temporário para evitar corrupção se o download cair
    with requests.get(url, stream=True, timeout=(15, 300)) as r:  # Abre requisição em modo streaming
        r.raise_for_status()  # Falha imediatamente se o servidor retornar erro HTTP
        with open(tmp, "wb") as f:  # Abre o arquivo temporário para escrita binária
            for chunk in r.iter_content(1 << 20):  # Lê em blocos de 1 MB por vez
                f.write(chunk)  # Grava o bloco no disco
    tmp.replace(dest)  # Renomeia o arquivo temporário para o destino final após concluir


def _load():  # Carrega Whisper e Piper na memória somente na primeira vez que forem usados
    global _whisper, _piper  # Permite salvar as instâncias no cache global
    if _whisper is None:  # Se o Whisper ainda não foi carregado
        from faster_whisper import WhisperModel  # Importa sob demanda para manter o boot rápido
        _whisper = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8",  # int8 na CPU: leve e rápido
                                download_root=str(MODELS_DIR / "whisper"))  # Salva os pesos dentro de modelos_voz/whisper
    if _piper is None:  # Se o Piper ainda não foi carregado
        from piper import PiperVoice  # Importa sintetizador de voz local
        MODELS_DIR.mkdir(parents=True, exist_ok=True)  # Garante que a pasta modelos_voz/ exista
        lang, name, quality = PIPER_VOICE.split("-")  # Separa idioma, nome da voz e qualidade (ex.: pt_BR, faber, medium)
        onnx = MODELS_DIR / f"{PIPER_VOICE}.onnx"  # Caminho do arquivo principal do modelo de voz
        for ext in (".onnx", ".onnx.json"):  # Precisa tanto do modelo (.onnx) quanto da configuração (.onnx.json)
            target = MODELS_DIR / f"{PIPER_VOICE}{ext}"  # Caminho final do arquivo atual
            if not target.exists():  # Baixa apenas se ainda não estiver em cache local
                _download(PIPER_URL.format(name=name, quality=quality, voice=PIPER_VOICE, ext=ext), target)  # Baixa do HF
        _piper = PiperVoice.load(str(onnx))  # Carrega o modelo ONNX do Piper na memória
    return _whisper, _piper  # Retorna ambos os modelos prontos


def _wav_to_array(wav_bytes):  # Converte bytes WAV (16 kHz mono) em vetor NumPy float32 para o Whisper
    """WAV (o navegador já manda em 16 kHz mono) → números que o Whisper entende. Sem ffmpeg."""
    import numpy as np  # Importa NumPy para converter PCM 16-bit em float32
    with wave.open(io.BytesIO(wav_bytes)) as w:  # Abre os bytes WAV diretamente da memória
        rate, channels, frames = w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())  # Lê taxa, canais e amostras
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0  # Normaliza PCM 16-bit para [-1.0, 1.0]
    if channels > 1:  # Se o áudio vier em estéreo (ou mais canais)
        audio = audio.reshape(-1, channels).mean(axis=1)  # Faz a média dos canais para virar mono
    if rate != 16000:  # Se a taxa de amostragem não for 16 kHz (exigida pelo Whisper)
        audio = np.interp(np.linspace(0, len(audio), int(len(audio) * 16000 / rate), endpoint=False),  # Interpola linearmente
                          np.arange(len(audio)), audio).astype(np.float32)  # Gera o vetor reamostrado em float32
    return audio  # Devolve o array pronto para transcrição


def transcribe(wav_bytes):  # Recebe áudio WAV e devolve o texto falado em português
    """Áudio WAV → texto em português."""
    with _lock:  # Garante acesso exclusivo aos modelos de voz
        whisper, _ = _load()  # Obtém o modelo Whisper carregado
        segments, _info = whisper.transcribe(_wav_to_array(wav_bytes), language="pt", beam_size=1,  # Transcreve em PT-BR
                                             vad_filter=True)  # Filtra silêncios automaticamente (Voice Activity Detection)
        return " ".join(s.text.strip() for s in segments).strip()  # Junta todos os trechos transcritos em uma única string


def clean_for_speech(text):  # Remove elementos visuais/estruturais que ficariam ruins se lidos em voz alta
    """Remove o que não faz sentido falar em voz alta (HTML, markdown, links, citações, raciocínio)."""
    text = re.sub(r"<think>.*?</think>", " ", text or "", flags=re.S | re.I)  # Remove blocos internos de raciocínio (qwen3)
    text = re.sub(r"```.*?```", " (o código está no chat) ", text, flags=re.S)  # Substitui blocos de código por aviso falado
    text = re.split(r"\n\s*Fontes?\s*:", text, maxsplit=1, flags=re.I)[0]  # Corta lista de fontes ao final da resposta
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # Converte links markdown [texto](url) apenas para "texto"
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)  # Remove comentários HTML
    text = re.sub(r"<[^>]+>", " ", text)  # Remove qualquer tag HTML residual
    text = html.unescape(text)  # Converte entidades HTML (&amp;, &quot;, etc.) em caracteres normais
    text = re.sub(r"\[\d+\]", "", text)  # Remove citações numéricas como [1], [2]
    text = re.sub(r"(?:https?://|www\.)\S+", "", text)  # Remove URLs soltas que não fazem sentido falar
    text = re.sub(r"(?m)^\s*(?:[-•*]|\d+[.)])\s+", "", text)  # Remove marcadores de listas e numerações no início das linhas
    text = re.sub(r"[*_#`>|~]", "", text)  # Remove símbolos de formatação markdown
    return re.sub(r"\s+", " ", text).strip()  # Compacta espaços múltiplos e remove espaços nas pontas


def speak(text):  # Converte uma resposta em texto para áudio WAV (bytes) usando Piper TTS
    """Texto → áudio WAV (bytes)."""
    spoken = clean_for_speech(text) or "Não consegui gerar uma resposta em áudio agora."  # Limpa texto e garante fallback
    with _lock:  # Garante acesso exclusivo ao sintetizador
        _, voice = _load()  # Obtém a voz Piper carregada
        buffer = io.BytesIO()  # Cria buffer em memória para armazenar o WAV gerado
        with wave.open(buffer, "wb") as wav:  # Abre o buffer como arquivo WAV de escrita
            if hasattr(voice, "synthesize_wav"):  # Compatibilidade com piper-tts versão 1.3 ou superior
                voice.synthesize_wav(spoken, wav)  # Sintetiza o texto limpo diretamente no WAV
            else:  # Compatibilidade com versões antigas do piper-tts
                voice.synthesize(spoken, wav)  # Sintetiza usando a assinatura legada
        return buffer.getvalue()  # Devolve os bytes completos do áudio WAV
