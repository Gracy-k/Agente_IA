"""Geração de imagem leve, embutida no próprio app.

Usa o SD-Turbo, que cria uma imagem em 1 a 4 passos (o Stable Diffusion comum usa 20 a 30).
- Com placa NVIDIA (ex.: GTX 1050 3 GB): roda na GPU em meia precisão, com "offload" para a RAM,
  então cabe em placas de 3-4 GB.
- Sem NVIDIA: roda no processador (mais lento, mas funciona).
O modelo (~2,6 GB) é baixado automaticamente na primeira imagem e carregado só quando for usado.

Opcional: IMAGE_BACKEND=webui usa um Stable Diffusion WebUI/Forge externo (IMAGE_API_URL) em vez disso.
"""
import base64
import io
import os
import threading

import requests

BACKEND = os.getenv("IMAGE_BACKEND", "local")          # "local" (embutido) ou "webui" (externo)
MODEL_ID = os.getenv("IMAGE_MODEL", "stabilityai/sd-turbo")
STEPS = int(os.getenv("IMAGE_STEPS", "2"))             # SD-Turbo: 1 a 4 passos bastam
IMAGE_API_URL = os.getenv("IMAGE_API_URL", "http://127.0.0.1:7860").rstrip("/")

# Tamanhos pensados para o SD-Turbo (treinado em 512 px) e para GPUs pequenas
SIZES = {"quadrado": (512, 512), "paisagem": (640, 384), "retrato": (384, 640)}

_pipe = None
_lock = threading.Lock()  # uma imagem por vez: evita estourar a memória


def _installed():
    try:
        import diffusers, torch  # noqa: F401
        return True
    except ImportError:
        return False


def device_name():
    try:
        import torch
        if torch.cuda.is_available():
            return f"GPU {torch.cuda.get_device_name(0)}"
    except ImportError:
        pass
    return "CPU"


def status():
    if BACKEND == "webui":
        try:
            requests.get(f"{IMAGE_API_URL}/sdapi/v1/sd-models", timeout=3).raise_for_status()
            return {"available": True, "detail": "WebUI externo"}
        except requests.RequestException:
            return {"available": False, "detail": f"WebUI offline em {IMAGE_API_URL}"}
    if not _installed():
        return {"available": False, "detail": "instale: pip install -r requirements-imagem.txt"}
    return {"available": True, "detail": f"SD-Turbo em {device_name()}"}


def _load():
    global _pipe
    if _pipe is not None:
        return _pipe
    import torch
    from diffusers import AutoPipelineForText2Image

    cuda = torch.cuda.is_available()
    pipe = AutoPipelineForText2Image.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.float16 if cuda else torch.float32,
        variant="fp16",  # baixa a versão menor dos pesos (metade do tamanho)
    )
    pipe.set_progress_bar_config(disable=True)
    if cuda:
        # Mantém na GPU só a parte que está trabalhando no momento → cabe em 3 GB de VRAM
        pipe.enable_model_cpu_offload()
        pipe.enable_attention_slicing()
        pipe.enable_vae_slicing()
    else:
        torch.set_num_threads(max(1, (os.cpu_count() or 4) - 1))  # deixa 1 núcleo livre p/ o sistema
    _pipe = pipe
    return _pipe


def generate(prompt, size="quadrado"):
    """Gera uma imagem e devolve (bytes_png, largura, altura)."""
    width, height = SIZES.get(size, SIZES["quadrado"])
    if BACKEND == "webui":
        r = requests.post(f"{IMAGE_API_URL}/sdapi/v1/txt2img", json={
            "prompt": prompt, "negative_prompt": "blurry, low quality, deformed, watermark",
            "steps": 20, "width": width, "height": height, "cfg_scale": 6}, timeout=(10, 900))
        r.raise_for_status()
        return base64.b64decode(r.json()["images"][0].split(",", 1)[-1]), width, height

    with _lock:
        pipe = _load()
        image = pipe(prompt=prompt, num_inference_steps=STEPS, guidance_scale=0.0,
                     width=width, height=height).images[0]
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), width, height
