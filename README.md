# CodeLocal — Assistente de IA que roda no seu computador

Um assistente que **escreve código, gera imagens, pesquisa na internet e conversa por voz**, rodando
no seu próprio PC. Ele foi otimizado para notebooks simples, como um **Lenovo L340 com GTX 1050 (3 GB) e 16 GB de RAM**.

## Explicando de forma simples

Pense no CodeLocal como uma pequena equipe trabalhando dentro do seu computador:

| Quem | O que faz | Programa usado | Onde roda |
|---|---|---|---|
| 🧠 **O cérebro** | Entende e responde suas perguntas | Ollama + `llama3.2:1b` | Placa de vídeo |
| 🎨 **O desenhista** | Cria imagens a partir de uma descrição | SD-Turbo | Placa de vídeo (ou processador) |
| 🔎 **O pesquisador** | Busca informações atuais na internet | DuckDuckGo | Internet |
| 👂 **O ouvido** | Transforma sua fala em texto | Whisper | Processador |
| 🗣️ **A voz** | Lê a resposta em voz alta | Piper (voz brasileira) | Processador |

E existe um **"recepcionista"** (o modo *Automático*) que lê seu pedido e decide quem da equipe vai trabalhar:
- "Gere uma imagem de um gato astronauta" → chama o **desenhista**
- "Qual a cotação do dólar hoje?" → chama o **pesquisador**, e o cérebro responde citando as fontes
- "Crie uma função em Python" → só o **cérebro**

### Por que é leve?
- **Cérebro pequeno:** o modelo de 1 bilhão de parâmetros ocupa só ~1,3 GB.
- **Desenhista rápido:** o SD-Turbo desenha em **2 passos** (o Stable Diffusion comum usa 20 a 30).
- **Revezamento na placa de vídeo:** a GTX 1050 tem só 3 GB, então o cérebro "sai" da placa antes do desenho começar, e o desenhista só carrega na placa a parte que está trabalhando naquele momento.
- **Ouvido e voz no processador:** deixam a placa de vídeo livre.
- **Nada carrega antes da hora:** os modelos de imagem e voz só são abertos quando você usa pela primeira vez.

### Como funciona a conversa por voz (estilo Gemini Live)
1. Você clica em **🎙 Voz** e fala normalmente.
2. Quando você faz uma pausa de ~1 segundo, o app entende que você terminou.
3. O **ouvido** transforma a fala em texto, o **cérebro** responde (pesquisando ou desenhando, se precisar) e a **voz** fala a resposta.
4. Se você falar por cima, ele **para de falar e volta a ouvir**, como numa conversa de verdade.
5. Tudo fica salvo no histórico do chat.

## Instalação (Windows)

**1. Programas necessários**
- [Python 3.12](https://www.python.org/downloads/) (marque "Add to PATH")
- [Ollama](https://ollama.com/download)

**2. Baixar o cérebro**
```bash
ollama pull llama3.2:1b
```

**3. Instalar o CodeLocal** (na pasta do projeto)
```bash
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**4. Instalar o desenhista** (opcional, ~3 GB)
```bash
# Notebook com placa NVIDIA (GTX 1050, 1650...):
pip install torch --index-url https://download.pytorch.org/whl/cu121
# Depois (com ou sem NVIDIA):
pip install -r requirements-imagem.txt
```

**5. Abrir**
```bash
python app.py
```
Acesse `http://127.0.0.1:5000`. A primeira imagem baixa o modelo (~2,6 GB) e a primeira conversa por voz baixa ~200 MB; depois disso, tudo fica no PC.

## Tempo e memória esperados (estimativa para L340, GTX 1050 3 GB, 16 GB RAM)

| Tarefa | Tempo aproximado | Memória |
|---|---|---|
| Resposta de texto | começa em 1–3 s | ~1,5 GB na placa |
| Imagem 512×512 | ~5–10 s | ~2,5 GB na placa + ~3 GB de RAM |
| Ouvir sua fala | ~1 s | ~300 MB de RAM |
| Falar a resposta | < 1 s | ~100 MB de RAM |

Sem placa NVIDIA, a imagem roda no processador e leva mais tempo, mas funciona.

## Ajustes opcionais (variáveis de ambiente)

| Variável | Padrão | Para que serve |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.2:1b` | Modelo do cérebro (`qwen2.5:3b` é mais inteligente, mas mais lento) |
| `IMAGE_STEPS` | `2` | Passos do desenho (1 = mais rápido, 4 = mais caprichado) |
| `IMAGE_PROMPT_MODEL` | (o mesmo) | Modelo usado só para traduzir o pedido de imagem para inglês |
| `WHISPER_MODEL` | `base` | `tiny` = ouve mais rápido, `small` = entende melhor |
| `PIPER_VOICE` | `pt_BR-faber-medium` | Voz usada nas respostas |
| `IMAGE_BACKEND` | `local` | `webui` para usar um Stable Diffusion WebUI/Forge externo (`IMAGE_API_URL`) |

## Arquivos do projeto
- `app.py` — o servidor e o "recepcionista" que decide o que fazer
- `modulos/imagem.py` — o desenhista
- `modulos/busca.py` — o pesquisador
- `modulos/voz.py` — o ouvido e a voz
- `static/voz.js` — o microfone no navegador (detecta quando você fala e quando para)
- `workspace/` — onde ficam os arquivos e imagens que você salva

## Privacidade e segurança
- O chat, a voz e as imagens são processados **no seu computador**. Só a **pesquisa** usa a internet, e apenas quando necessário.
- O histórico fica em `conversas.db`, e esse arquivo não vai para o Git.
- O agente não executa código e só salva arquivos dentro de `workspace/`, sem sobrescrever nada.
