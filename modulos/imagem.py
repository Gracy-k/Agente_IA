"""Geração de imagem leve, embutida no próprio app.

Usa o SD-Turbo, que cria uma imagem em 1 a 4 passos (o Stable Diffusion comum usa 20 a 30).
- Com placa NVIDIA (ex.: GTX 1050 3 GB): roda na GPU em meia precisão, com "offload" para a RAM,
  então cabe em placas de 3-4 GB.
- Sem NVIDIA: roda no processador (mais lento, mas funciona).
O modelo (~2,6 GB) é baixado automaticamente na primeira imagem e carregado só quando for usado.

Opcional: IMAGE_BACKEND=webui usa um Stable Diffusion WebUI/Forge externo (IMAGE_API_URL) em vez disso.
"""
import base64  # Decodifica imagens retornadas em base64 pelo backend WebUI externo
import io  # Cria buffer em memória para converter a imagem PIL em bytes PNG
import os  # Lê variáveis de ambiente e a quantidade de núcleos da CPU
import threading  # Garante acesso exclusivo ao pipeline (uma imagem por vez)

import requests  # Faz requisições HTTP quando o backend externo (WebUI) está ativo

BACKEND = os.getenv("IMAGE_BACKEND", "local")  # Define se gera localmente ("local") ou via WebUI ("webui")
MODEL_ID = os.getenv("IMAGE_MODEL", "stabilityai/sd-turbo")  # ID do modelo Stable Diffusion no Hugging Face
STEPS = int(os.getenv("IMAGE_STEPS", "2"))  # Número de passos de inferência (SD-Turbo precisa de 1 a 4)
IMAGE_API_URL = os.getenv("IMAGE_API_URL", "http://127.0.0.1:7860").rstrip("/")  # URL da API externa do WebUI

# Mapeamento de formatos amigáveis para resoluções (largura, altura) otimizadas para o SD-Turbo
SIZES = {"quadrado": (512, 512), "paisagem": (640, 384), "retrato": (384, 640)}

_pipe = None  # Cache global do pipeline carregado sob demanda (lazy loading)
_lock = threading.Lock()  # Trava para gerar apenas uma imagem por vez e evitar estourar a memória


def _installed():  # Verifica se as bibliotecas de geração de imagem estão instaladas
    try:  # Tenta importar diffusers e torch
        import diffusers, torch  # noqa: F401  # Importação apenas para checar disponibilidade
        return True  # Ambas as bibliotecas estão disponíveis
    except ImportError:  # Caso alguma não esteja instalada
        return False  # Indica que o recurso de imagem não está pronto


def device_name():  # Descobre se a geração vai rodar na GPU NVIDIA ou na CPU
    try:  # Tenta consultar o PyTorch
        import torch  # Importa torch sob demanda para não atrasar o boot do app
        if torch.cuda.is_available():  # Verifica se há GPU NVIDIA com CUDA compatível
            return f"GPU {torch.cuda.get_device_name(0)}"  # Retorna o nome da placa de vídeo
    except ImportError:  # Se o torch não estiver instalado
        pass  # Cai para o retorno padrão "CPU"
    return "CPU"  # Fallback padrão quando não há CUDA disponível


def status():  # Informa para a rota /api/status se o gerador de imagem está operacional
    if BACKEND == "webui":  # Se configurado para usar WebUI externo
        try:  # Testa se o servidor WebUI está respondendo
            requests.get(f"{IMAGE_API_URL}/sdapi/v1/sd-models", timeout=3).raise_for_status()  # Ping na API
            return {"available": True, "detail": "WebUI externo"}  # WebUI online e pronto
        except requests.RequestException:  # Se o WebUI estiver fora do ar
            return {"available": False, "detail": f"WebUI offline em {IMAGE_API_URL}"}  # Reporta indisponibilidade
    if not _installed():  # Se o backend local não tem torch/diffusers instalados
        return {"available": False, "detail": "instale: pip install -r requirements-imagem.txt"}  # Instrui instalação
    return {"available": True, "detail": f"SD-Turbo em {device_name()}"}  # Pronto no modo local (GPU ou CPU)


def _load():  # Carrega o modelo SD-Turbo em memória apenas na primeira geração
    global _pipe  # Permite atualizar o cache global do pipeline
    if _pipe is not None:  # Se já foi carregado anteriormente
        return _pipe  # Reaproveita a instância sem recarregar
    import torch  # Importa PyTorch para configurar precisão e dispositivo
    from diffusers import AutoPipelineForText2Image  # Carregador automático de pipelines text-to-image

    cuda = torch.cuda.is_available()  # Verifica se há GPU CUDA ativa
    pipe = AutoPipelineForText2Image.from_pretrained(  # Baixa (na 1ª vez) e carrega os pesos do SD-Turbo
        MODEL_ID,  # Repositório do modelo no Hugging Face
        torch_dtype=torch.float16 if cuda else torch.float32,  # Meia precisão na GPU; float32 na CPU
        variant="fp16",  # Usa os arquivos fp16 menores (~2,6 GB em vez de ~5 GB)
    )  # Finaliza o carregamento do pipeline
    pipe.set_progress_bar_config(disable=True)  # Oculta barra de progresso no terminal do servidor
    if cuda:  # Otimizações específicas para placas com pouca VRAM (ex.: GTX 1050 3 GB)
        pipe.enable_model_cpu_offload()  # Mantém na GPU só o módulo ativo no momento, resto fica na RAM
        pipe.enable_attention_slicing()  # Divide o cálculo de atenção para reduzir pico de VRAM
        pipe.enable_vae_slicing()  # Decodifica a imagem em fatias para economizar VRAM
    else:  # Caso esteja rodando no processador (CPU)
        torch.set_num_threads(max(1, (os.cpu_count() or 4) - 1))  # Usa quase todos os núcleos, deixando 1 livre
    _pipe = pipe  # Guarda o pipeline pronto no cache global
    return _pipe  # Retorna o pipeline carregado


def generate(prompt, size="quadrado"):  # Gera uma imagem PNG a partir de um prompt em inglês
    """Gera uma imagem e devolve (bytes_png, largura, altura)."""
    width, height = SIZES.get(size, SIZES["quadrado"])  # Converte o formato escolhido em (largura, altura)
    if BACKEND == "webui":  # Caminho alternativo usando Stable Diffusion WebUI externo
        r = requests.post(f"{IMAGE_API_URL}/sdapi/v1/txt2img", json={  # Envia parâmetros para a API txt2img
            "prompt": prompt, "negative_prompt": "blurry, low quality, deformed, watermark",  # Prompt positivo e negativo
            "steps": 20, "width": width, "height": height, "cfg_scale": 6}, timeout=(10, 900))  # Executa com timeout longo
        r.raise_for_status()  # Levanta erro caso a API retorne status HTTP inválido
        return base64.b64decode(r.json()["images"][0].split(",", 1)[-1]), width, height  # Decodifica o PNG base64

    with _lock:  # Garante que apenas uma requisição use o SD-Turbo por vez
        pipe = _load()  # Obtém o pipeline já carregado (ou carrega na primeira chamada)
        image = pipe(prompt=prompt, num_inference_steps=STEPS, guidance_scale=0.0,  # SD-Turbo exige guidance_scale=0.0
                     width=width, height=height).images[0]  # Extrai a primeira imagem PIL gerada
    buffer = io.BytesIO()  # Cria um arquivo virtual em memória
    image.save(buffer, format="PNG")  # Serializa a imagem PIL no formato PNG
    return buffer.getvalue(), width, height  # Devolve os bytes do PNG junto com largura e altura
