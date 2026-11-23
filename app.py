from pathlib import Path
import base64, json, os, re, sqlite3, uuid
from datetime import datetime
import requests
from modulos import busca, imagem, voz
from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory, stream_with_context

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE = (BASE_DIR / "workspace").resolve()
DATABASE = BASE_DIR / "conversas.db"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "3000"))
IMAGES_DIR = WORKSPACE / "imagens"
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # áudio de voz cabe aqui

SYSTEM_PROMPT = """Você é o CodeLocal, engenheiro de software sênior e tutor de programação, rodando localmente via Ollama.
Seja direto, didático e entregue soluções completas e funcionais.

Regras:
- Quando pedirem implementação, entregue o código completo. Nunca use reticências nem "restante do código".
- Não invente bibliotecas, APIs, resultados de testes ou links. Informe dependências e como executar.
- Nunca peça senhas/tokens; use variáveis de ambiente para segredos.
- Ao corrigir: diga o erro, por que ocorria e mostre a correção, preservando o resto do projeto.
- Ao explicar: comece simples, use exemplos curtos.
- Ao revisar: sintaxe, lógica, segurança, desempenho, legibilidade.
- Prefira soluções leves (o computador pode ser fraco).

Sites/páginas web (HTML, portfólio, landing page, formulário, interface):
- Responda com EXATAMENTE UM bloco ```html com documento completo (<!DOCTYPE html>, lang="pt-BR", meta viewport).
- Todo CSS dentro de <style> no <head>; todo JS dentro de <script> antes de </body>. Nada de arquivos separados.
- Conteúdo real, visual moderno, responsivo, botões e formulários funcionais. Depois do bloco, no máximo 3 observações curtas.
"""

def db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, model TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE)""")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
        if "image" not in cols:  # migração de bancos antigos
            conn.execute("ALTER TABLE messages ADD COLUMN image TEXT")

def now():
    return datetime.now().isoformat(timespec="seconds")

@app.get("/")
def index():
    return render_template("index.html", default_model=DEFAULT_MODEL)

@app.get("/api/models")
def models():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        r.raise_for_status()
        names = [m.get("name") for m in r.json().get("models", []) if m.get("name")]
        return jsonify({"models": names, "default": DEFAULT_MODEL})
    except requests.RequestException as exc:
        return jsonify({"models": [], "default": DEFAULT_MODEL, "error": str(exc)}), 503

@app.get("/api/chats")
def list_chats():
    with db() as conn:
        rows = conn.execute("SELECT id,title,model,created_at,updated_at FROM chats ORDER BY updated_at DESC").fetchall()
    return jsonify({"chats": [dict(x) for x in rows]})

@app.post("/api/chats")
def create_chat():
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "Nova conversa").strip()[:80] or "Nova conversa"
    model = str(data.get("model") or DEFAULT_MODEL).strip()[:100]
    chat_id, timestamp = uuid.uuid4().hex, now()
    with db() as conn:
        conn.execute("INSERT INTO chats VALUES (?,?,?,?,?)", (chat_id,title,model,timestamp,timestamp))
    return jsonify({"id":chat_id,"title":title,"model":model}), 201

@app.get("/api/chats/<chat_id>")
def get_chat(chat_id):
    with db() as conn:
        chat = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            return jsonify({"error":"Conversa não encontrada."}),404
        msgs = conn.execute("SELECT role,content,image,created_at FROM messages WHERE chat_id=? ORDER BY id",(chat_id,)).fetchall()
    return jsonify({"chat":dict(chat),"messages":[dict(m) for m in msgs]})

@app.delete("/api/chats/<chat_id>")
def delete_chat(chat_id):
    with db() as conn:
        cur = conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
        if cur.rowcount == 0:
            return jsonify({"error":"Conversa não encontrada."}),404
    return jsonify({"deleted":True})

@app.get("/api/status")
def status():
    """Diz para a interface quais recursos estão prontos (imagem, voz)."""
    return jsonify({"imagem": imagem.status(), "voz": voz.status()})

@app.get("/imagens/<name>")
def serve_image(name):
    if not re.fullmatch(r"[0-9a-f]{32}\.png", name):
        abort(404)
    return send_from_directory(IMAGES_DIR, name)

IMAGE_WORDS = ("gere uma imagem", "gerar uma imagem", "gere a imagem", "crie uma imagem", "criar uma imagem",
               "desenhe", "desenha ", "ilustração", "ilustracao", "faça uma imagem", "faca uma imagem",
               "gera uma imagem", "foto de", "logotipo", "wallpaper", "pintura de")

def ollama_once(model, system, user, predict=200, keep_alive="30m"):
    r = requests.post(f"{OLLAMA_URL}/api/chat", json={
        "model": model, "stream": False,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"num_ctx": 2048, "num_predict": predict, "temperature": 0.3}, "keep_alive": keep_alive},
        timeout=(15, 180))
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "").strip()

def wants_image(prompt, model):
    """Roteador do agente: palavras-chave primeiro (rápido); na dúvida, pergunta ao LLM."""
    low = prompt.lower()
    if any(w in low for w in IMAGE_WORDS):
        return True
    if not any(w in low for w in ("imagem", "foto", "desenho", "arte ", "ícone", "icone", "banner", "logo")):
        return False
    try:
        answer = ollama_once(model, "Classifique o pedido. Responda apenas IMAGEM se o usuário quer que uma imagem "
                             "seja gerada, ou TEXTO se quer código, explicação ou texto.", prompt, predict=5)
        return answer.upper().startswith("IMAGEM")
    except requests.RequestException:
        return False

IMAGE_PROMPT_MODEL = os.getenv("IMAGE_PROMPT_MODEL", "")  # opcional: modelo melhor só para traduzir o prompt
QUALITY_TAGS = "highly detailed, sharp focus, vibrant colors, professional composition"
TRANSLATE_SYSTEM = ("You translate image descriptions from Portuguese to English for Stable Diffusion. "
                    "Translate faithfully: keep every subject, object, style and color. Do NOT add emotions, "
                    "details or objects that are not in the text. Output only comma-separated English keywords, "
                    "one line, no explanations.")
TRANSLATE_EXAMPLES = [
    ("um gato astronauta flutuando no espaço, ilustração digital colorida",
     "an astronaut cat wearing a space suit, floating in outer space, stars, colorful digital illustration"),
    ("logo minimalista de uma cafeteria chamada Grão, tons de marrom",
     "minimalist logo for a coffee shop named Grão, coffee bean icon, brown tones, flat vector design"),
    ("foto de uma praia ao pôr do sol com coqueiros",
     "photo of a beach at sunset, palm trees, golden hour lighting, realistic photography"),
]
REQUEST_PREFIX = re.compile(r"^\s*(por favor[,]?\s*)?(gere|gera|gerar|crie|cria|criar|fa[çc]a|desenhe|desenha|"
                            r"quero|me (mostre|d[eê]))\s+(uma?\s+)?(imagem|foto|ilustra[çc][ãa]o|desenho|arte|"
                            r"pintura)?\s*(de|do|da|com)?\s*", re.IGNORECASE)
PT_WORDS = re.compile(r"\b(um|uma|de|do|da|com|no|na|em|que|imagem|não)\b|[ãõçáéíóúâêô]", re.IGNORECASE)

def build_image_prompt(prompt, model):
    """Pedido em português → prompt em inglês: limpa o pedido, o LLM só traduz, o código acrescenta qualidade."""
    subject = REQUEST_PREFIX.sub("", prompt.strip()).strip(" .!") or prompt.strip()
    messages = [{"role": "system", "content": TRANSLATE_SYSTEM}]
    for pt, en in TRANSLATE_EXAMPLES:
        messages += [{"role": "user", "content": pt}, {"role": "assistant", "content": en}]
    messages.append({"role": "user", "content": subject})
    english = ""
    for _ in range(2):  # uma nova tentativa se a resposta não vier em inglês
        try:
            r = requests.post(f"{OLLAMA_URL}/api/chat", json={
                "model": IMAGE_PROMPT_MODEL or model, "stream": False, "messages": messages,
                "options": {"num_ctx": 2048, "num_predict": 100, "temperature": 0.1},
                "keep_alive": 0}, timeout=(15, 180))  # keep_alive=0 libera a VRAM para o Stable Diffusion
            r.raise_for_status()
            text = r.json().get("message", {}).get("content", "").strip().strip('"')
            text = text.splitlines()[0].strip() if text else ""
        except requests.RequestException:
            break
        if text and len(PT_WORDS.findall(text)) <= 1:
            english = text
            break
    base = english or subject  # sem tradução válida, usa o texto limpo (o SD ainda entende parte)
    return f"{base}, {QUALITY_TAGS}"

def sse(obj):
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

def save_messages(chat_id, model, prompt, answer, image=None):
    timestamp = now()
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,)).fetchone()[0]
        conn.execute("INSERT INTO messages (chat_id,role,content,created_at) VALUES (?,?,?,?)",
                     (chat_id, "user", prompt, timestamp))
        conn.execute("INSERT INTO messages (chat_id,role,content,image,created_at) VALUES (?,?,?,?,?)",
                     (chat_id, "assistant", answer, image, timestamp))
        if count == 0:
            title = prompt.replace("\n", " ")[:52] + ("…" if len(prompt) > 52 else "")
            conn.execute("UPDATE chats SET title=?,model=?,updated_at=? WHERE id=?", (title, model, timestamp, chat_id))
        else:
            conn.execute("UPDATE chats SET model=?,updated_at=? WHERE id=?", (model, timestamp, chat_id))

def create_image(prompt, model, size):
    """Pedido em português → prompt em inglês → imagem salva. Devolve (nome_arquivo, texto_resposta)."""
    sd_prompt = build_image_prompt(prompt, model)
    png, width, height = imagem.generate(sd_prompt, size)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ".png"
    (IMAGES_DIR / name).write_bytes(png)
    answer = (f"Imagem gerada ({width}×{height}), salva em workspace/imagens/{name}.\n\n"
              f"Prompt usado:\n```text\n{sd_prompt}\n```")
    return name, answer

def image_stream(chat_id, model, prompt, size):
    try:
        yield sse({"status": "Gerando imagem… (a primeira vez baixa o modelo, ~2,6 GB)"})
        name, answer = create_image(prompt, model, size)
        save_messages(chat_id, model, prompt, answer, name)
        yield sse({"token": answer, "image": name})
        yield sse({"done": True, "model": model, "chat_id": chat_id})
    except requests.RequestException as exc:
        yield sse({"error": f"Falha na API de imagem: {exc}"})
    except ImportError:
        yield sse({"error": "Gerador de imagem não instalado. Rode: pip install -r requirements-imagem.txt"})
    except Exception as exc:
        yield sse({"error": f"Falha ao gerar imagem: {exc}"})

@app.post("/api/generate")
def generate():
    data = request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()
    model = str(data.get("model") or DEFAULT_MODEL).strip()
    chat_id = str(data.get("chat_id") or "").strip()
    if not prompt: return jsonify({"error": "Digite uma solicitação antes de gerar."}), 400
    if len(prompt) > 12000: return jsonify({"error": "A solicitação é muito longa (máximo de 12.000 caracteres)."}), 400
    if not model or len(model) > 100: return jsonify({"error": "Nome de modelo inválido."}), 400
    with db() as conn:
        chat = conn.execute("SELECT id FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat: return jsonify({"error": "Conversa não encontrada. Crie uma nova conversa."}), 404
        history = conn.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()
    mode = str(data.get("mode") or "auto")
    if mode == "imagem" or (mode == "auto" and wants_image(prompt, model)):
        size = str(data.get("size") or "quadrado")
        return Response(stream_with_context(image_stream(chat_id, model, prompt, size)), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history[-6:])
    # Reforça a instrução para modelos pequenos quando o pedido exige um único arquivo web.
    lower_prompt = prompt.lower()
    asks_web_stack = ("html" in lower_prompt and "css" in lower_prompt and
                      ("javascript" in lower_prompt or " js" in lower_prompt or "js " in lower_prompt))
    asks_to_build_site = any(word in lower_prompt for word in ("crie um site", "criar um site", "crie um portfólio", "crie um portfolio", "crie um portifolio", "site html", "página html", "pagina html"))
    asks_single_file = any(word in lower_prompt for word in ("junto", "único", "unico", "mesmo arquivo", "num código só", "um código só", "tudo junto"))
    if asks_to_build_site or (asks_web_stack and asks_single_file):
        prompt_for_model = prompt + "\n\nINSTRUÇÃO DE FORMATO E ENTREGA: produza o site funcionando, não descreva um projeto. Responda com EXATAMENTE UM bloco ```html contendo o documento completo, CSS dentro de <style> e JavaScript dentro de <script>. Não gere blocos CSS/JS separados, não entregue apenas especificações, não repita seções e não invente URLs. Inclua conteúdo, layout responsivo, cores solicitadas e interações funcionais."
    else:
        prompt_for_model = prompt
    use_web = mode == "web" or (mode == "auto" and busca.needs_search(prompt))

    def generate_stream():
        full_answer = ""
        results = []
        try:
            user_content = prompt_for_model
            if use_web:
                yield sse({"status": "Pesquisando na internet…"})
                results = busca.search(prompt)
                if results:
                    user_content = busca.context_for_model(results, prompt_for_model)
                    # Para pesquisa, um "papel" simples funciona melhor que o de programador
                    messages[0] = {"role": "system", "content": busca.SEARCH_SYSTEM}
                else:
                    yield sse({"status": "Sem resultados da internet; respondendo com o que o modelo sabe…"})
            messages.append({"role": "user", "content": user_content})
            with requests.post(f"{OLLAMA_URL}/api/chat", json={
                "model": model, "messages": messages, "stream": True,
                "options": {"num_ctx": NUM_CTX, "num_predict": NUM_PREDICT, "temperature": 0.2},
                "keep_alive": "30m"}, stream=True, timeout=(15, 600)) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line: continue
                    packet = json.loads(line)
                    token = packet.get("message", {}).get("content", "")
                    if token:
                        full_answer += token
                        yield "data: " + json.dumps({"token": token}, ensure_ascii=False) + "\n\n"
                    if packet.get("done"):
                        break
            if not full_answer:
                yield "data: " + json.dumps({"error": "O modelo não retornou conteúdo. Tente novamente."}, ensure_ascii=False) + "\n\n"
                return
            if results:  # lista de fontes ao final da resposta
                fontes = busca.sources_markdown(results)
                full_answer += fontes
                yield sse({"token": fontes})
            save_messages(chat_id, model, prompt, full_answer)
            yield "data: " + json.dumps({"done": True, "model": model, "chat_id": chat_id}, ensure_ascii=False) + "\n\n"
        except requests.ConnectionError:
            yield "data: " + json.dumps({"error": "Não foi possível conectar ao Ollama. Verifique se ele está aberto."}, ensure_ascii=False) + "\n\n"
        except requests.Timeout:
            yield "data: " + json.dumps({"error": "O Ollama excedeu o tempo limite. Tente uma solicitação menor."}, ensure_ascii=False) + "\n\n"
        except requests.RequestException as exc:
            yield "data: " + json.dumps({"error": f"Falha na comunicação com o Ollama: {exc}"}, ensure_ascii=False) + "\n\n"
        except Exception as exc:
            yield "data: " + json.dumps({"error": f"Falha ao processar a resposta: {exc}"}, ensure_ascii=False) + "\n\n"
    return Response(stream_with_context(generate_stream()), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

def ask_llm(model, messages, predict=300):
    r = requests.post(f"{OLLAMA_URL}/api/chat", json={
        "model": model, "messages": messages, "stream": False,
        "options": {"num_ctx": NUM_CTX, "num_predict": predict, "temperature": 0.4}, "keep_alive": "30m"},
        timeout=(15, 300))
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "").strip()

@app.post("/api/voice")
def voice_turn():
    """Uma rodada da conversa por voz: áudio → texto → (busca/imagem) → resposta → áudio."""
    audio = request.files.get("audio")
    chat_id = str(request.form.get("chat_id") or "")
    model = str(request.form.get("model") or DEFAULT_MODEL)[:100]
    if not audio:
        return jsonify({"error": "Nenhum áudio recebido."}), 400
    with db() as conn:
        if not conn.execute("SELECT id FROM chats WHERE id=?", (chat_id,)).fetchone():
            return jsonify({"error": "Conversa não encontrada."}), 404
        history = conn.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()
    try:
        text = voz.transcribe(audio.read())
    except ImportError:
        return jsonify({"error": "Módulo de voz não instalado. Rode: pip install -r requirements.txt"}), 503
    if len(text) < 2:
        return jsonify({"text": "", "answer": "", "audio": None})  # só ruído: continua ouvindo

    image_name, results = None, []
    try:
        if wants_image(text, model):
            image_name, answer = create_image(text, model, "quadrado")
            spoken = "Pronto, gerei a imagem. Ela está no chat."
        else:
            messages = [{"role": "system", "content": voz.VOICE_SYSTEM}]
            messages += [{"role": m["role"], "content": m["content"][:1500]} for m in history[-6:]]
            user_content = text
            if busca.needs_search(text):
                results = busca.search(text)
                if results:
                    user_content = busca.context_for_model(results, text)
            messages.append({"role": "user", "content": user_content})
            spoken = ask_llm(model, messages)
            answer = spoken + (busca.sources_markdown(results) if results else "")
    except requests.RequestException as exc:
        return jsonify({"error": f"Falha ao falar com o Ollama: {exc}", "text": text}), 502
    save_messages(chat_id, model, text, answer, image_name)
    wav = voz.speak(spoken)
    return jsonify({"text": text, "answer": answer, "image": image_name,
                    "audio": base64.b64encode(wav).decode()})

@app.post("/api/save")
def save_file():
    data=request.get_json(silent=True) or {}
    relative_path=str(data.get("path","")).strip()
    content=data.get("content","")
    if not relative_path or not isinstance(content,str): return jsonify({"error":"Informe o caminho e o conteúdo do arquivo."}),400
    if len(relative_path)>240 or len(content)>500000: return jsonify({"error":"Caminho ou conteúdo excede o limite permitido."}),400
    rel=Path(relative_path)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts: return jsonify({"error":"Caminho inválido. Use um caminho relativo dentro de workspace/."}),400
    destination=(WORKSPACE/rel).resolve()
    if destination!=WORKSPACE and WORKSPACE not in destination.parents: return jsonify({"error":"Por segurança, só é permitido salvar dentro de workspace/."}),403
    try:
        destination.parent.mkdir(parents=True,exist_ok=True)
        # Criação exclusiva: nunca substitui um arquivo que já existe.
        with destination.open("x", encoding="utf-8", newline="") as file:
            file.write(content)
        return jsonify({"saved":True,"path":rel.as_posix()}),201
    except FileExistsError:
        return jsonify({"error":f"O arquivo workspace/{rel.as_posix()} já existe. Escolha outro nome para preservar o arquivo anterior."}),409
    except OSError as exc: return jsonify({"error":f"Não foi possível salvar o arquivo: {exc}"}),500

init_db()
WORKSPACE.mkdir(exist_ok=True)

if __name__=="__main__":
    app.run(host="127.0.0.1",port=5000,debug=False)
