from pathlib import Path  # Manipulação segura e portável de caminhos de arquivos/pastas
import base64, json, os, re, sqlite3, uuid  # Utilitários padrão: base64 (áudio), JSON, SO, regex, SQLite e UUID
from datetime import datetime  # Gera timestamps ISO para registrar criação/atualização das conversas
import requests  # Faz chamadas HTTP ao servidor local do Ollama
from modulos import busca, imagem, voz  # Importa os módulos internos de pesquisa web, geração de imagem e voz
from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory, stream_with_context  # Framework web Flask

BASE_DIR = Path(__file__).resolve().parent  # Diretório raiz onde o app.py está localizado
WORKSPACE = (BASE_DIR / "workspace").resolve()  # Pasta segura onde arquivos salvos pelo usuário são gravados
DATABASE = BASE_DIR / "conversas.db"  # Caminho do banco de dados SQLite local com o histórico
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")  # Endereço da API local do Ollama
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")  # Modelo padrão caso o usuário não escolha outro
NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))  # Tamanho máximo da janela de contexto enviada ao LLM
NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "3000"))  # Limite máximo de tokens gerados por resposta no chat
IMAGES_DIR = WORKSPACE / "imagens"  # Subpasta onde ficam salvas as imagens PNG geradas pelo SD-Turbo
app = Flask(__name__)  # Cria a aplicação web Flask
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # Limita uploads a 10 MB (comporta áudios WAV de voz)

# Prompt de sistema padrão usado no chat de programação/texto
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

def db():  # Abre uma nova conexão com o banco SQLite configurada com Row e chaves estrangeiras
    conn = sqlite3.connect(DATABASE)  # Conecta ao arquivo conversas.db (cria se não existir)
    conn.row_factory = sqlite3.Row  # Permite acessar colunas pelo nome (ex.: row["title"])
    conn.execute("PRAGMA foreign_keys = ON")  # Ativa integridade referencial (ON DELETE CASCADE)
    return conn  # Retorna a conexão pronta

def init_db():  # Cria as tabelas iniciais e migra bancos antigos automaticamente
    with db() as conn:  # Abre transação no SQLite
        # Cria tabela de conversas (chats) caso ainda não exista
        conn.execute("""CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, model TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        # Cria tabela de mensagens ligada à tabela chats (apaga mensagens ao excluir o chat)
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE)""")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}  # Lista colunas existentes em messages
        if "image" not in cols:  # Migração automática para bancos criados na branch main antiga
            conn.execute("ALTER TABLE messages ADD COLUMN image TEXT")  # Adiciona coluna para nome do arquivo PNG

def now():  # Retorna data e hora atuais no formato ISO (sem microssegundos)
    return datetime.now().isoformat(timespec="seconds")

@app.get("/")  # Rota raiz: entrega a página principal do CodeLocal
def index():
    return render_template("index.html", default_model=DEFAULT_MODEL)  # Renderiza templates/index.html com modelo padrão

@app.get("/api/models")  # Lista os modelos instalados no Ollama local
def models():
    try:  # Consulta a API /api/tags do Ollama
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)  # Timeout de 10s para verificar disponibilidade
        r.raise_for_status()  # Levanta erro se o Ollama retornar HTTP inválido
        names = [m.get("name") for m in r.json().get("models", []) if m.get("name")]  # Extrai os nomes dos modelos
        return jsonify({"models": names, "default": DEFAULT_MODEL})  # Devolve lista em JSON
    except requests.RequestException as exc:  # Se o Ollama estiver fechado ou inacessível
        return jsonify({"models": [], "default": DEFAULT_MODEL, "error": str(exc)}), 503  # Retorna erro 503

@app.get("/api/chats")  # Lista todas as conversas salvas ordenadas pela atualização mais recente
def list_chats():
    with db() as conn:  # Consulta o SQLite
        rows = conn.execute("SELECT id,title,model,created_at,updated_at FROM chats ORDER BY updated_at DESC").fetchall()
    return jsonify({"chats": [dict(x) for x in rows]})  # Converte sqlite3.Row em dicionários JSON

@app.post("/api/chats")  # Cria uma nova conversa vazia no banco
def create_chat():
    data = request.get_json(silent=True) or {}  # Lê corpo JSON da requisição com fallback vazio
    title = str(data.get("title") or "Nova conversa").strip()[:80] or "Nova conversa"  # Sanitiza e limita o título
    model = str(data.get("model") or DEFAULT_MODEL).strip()[:100]  # Define o modelo associado ao chat
    chat_id, timestamp = uuid.uuid4().hex, now()  # Gera ID único hexadecimal e timestamp atual
    with db() as conn:  # Insere o registro na tabela chats
        conn.execute("INSERT INTO chats VALUES (?,?,?,?,?)", (chat_id,title,model,timestamp,timestamp))
    return jsonify({"id":chat_id,"title":title,"model":model}), 201  # Retorna 201 Created com os dados do chat

@app.get("/api/chats/<chat_id>")  # Retorna os metadados e todas as mensagens de uma conversa específica
def get_chat(chat_id):
    with db() as conn:  # Busca o chat e suas mensagens no SQLite
        chat = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()  # Busca dados do chat
        if not chat:  # Se o ID não existir
            return jsonify({"error":"Conversa não encontrada."}),404  # Retorna 404 Not Found
        msgs = conn.execute("SELECT role,content,image,created_at FROM messages WHERE chat_id=? ORDER BY id",(chat_id,)).fetchall()  # Busca mensagens em ordem
    return jsonify({"chat":dict(chat),"messages":[dict(m) for m in msgs]})  # Devolve chat + lista de mensagens

@app.delete("/api/chats/<chat_id>")  # Exclui uma conversa (e suas mensagens via ON DELETE CASCADE)
def delete_chat(chat_id):
    with db() as conn:  # Executa o DELETE no banco
        cur = conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))  # Remove pelo ID
        if cur.rowcount == 0:  # Se nenhuma linha foi afetada, o chat não existia
            return jsonify({"error":"Conversa não encontrada."}),404  # Retorna 404
    return jsonify({"deleted":True})  # Confirma exclusão

@app.get("/api/status")  # Informa à interface web se os módulos de imagem e voz estão prontos
def status():
    """Diz para a interface quais recursos estão prontos (imagem, voz)."""
    return jsonify({"imagem": imagem.status(), "voz": voz.status()})  # Consulta status em cada módulo

@app.get("/imagens/<name>")  # Serve uma imagem PNG gerada a partir de workspace/imagens/
def serve_image(name):
    if not re.fullmatch(r"[0-9a-f]{32}\.png", name):  # Valida formato estrito UUID.png para impedir path traversal
        abort(404)  # Bloqueia nomes fora do padrão
    return send_from_directory(IMAGES_DIR, name)  # Envia o arquivo PNG com segurança

# Palavras-chave explícitas que ativam geração de imagem imediatamente sem consultar o LLM
IMAGE_WORDS = ("gere uma imagem", "gerar uma imagem", "gere a imagem", "crie uma imagem", "criar uma imagem",
               "desenhe", "desenha ", "ilustração", "ilustracao", "faça uma imagem", "faca uma imagem",
               "gera uma imagem", "foto de", "logotipo", "wallpaper", "pintura de")

def ollama_once(model, system, user, predict=200, keep_alive="30m"):  # Chamada única (sem streaming) ao Ollama
    r = requests.post(f"{OLLAMA_URL}/api/chat", json={  # Envia system + user para /api/chat
        "model": model, "stream": False, "think": False,  # think=False evita resposta vazia em modelos qwen3
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"num_ctx": 2048, "num_predict": predict, "temperature": 0.3}, "keep_alive": keep_alive},
        timeout=(15, 180))  # Timeout de conexão (15s) e leitura (180s)
    r.raise_for_status()  # Verifica erro HTTP
    content = r.json().get("message", {}).get("content", "")  # Extrai o texto gerado
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S | re.I).strip()  # Remove qualquer bloco <think> residual

def wants_image(prompt, model):  # Roteador que decide se o pedido do usuário quer gerar uma imagem
    """Roteador do agente: palavras-chave primeiro (rápido); na dúvida, pergunta ao LLM."""
    low = prompt.lower()  # Normaliza para minúsculas
    if any(w in low for w in IMAGE_WORDS):  # Checagem instantânea por frases diretas
        return True
    if not any(w in low for w in ("imagem", "foto", "desenho", "arte ", "ícone", "icone", "banner", "logo")):  # Sem pista visual
        return False  # Evita chamar o LLM à toa
    try:  # Caso ambíguo (ex.: "explique o que é uma imagem"): pede classificação curta ao LLM
        answer = ollama_once(model, "Classifique o pedido. Responda apenas IMAGEM se o usuário quer que uma imagem "
                             "seja gerada, ou TEXTO se quer código, explicação ou texto.", prompt, predict=5)
        return answer.upper().startswith("IMAGEM")  # Só gera imagem se o modelo classificar como IMAGEM
    except requests.RequestException:  # Se o Ollama falhar na classificação
        return False  # Segue como texto normal

IMAGE_PROMPT_MODEL = os.getenv("IMAGE_PROMPT_MODEL", "")  # Modelo opcional dedicado apenas a traduzir prompts de imagem
QUALITY_TAGS = "highly detailed, sharp focus, vibrant colors, professional composition"  # Tags de qualidade anexadas ao prompt
# Instrução para o LLM traduzir descrições de imagem PT -> EN fielmente para o Stable Diffusion
TRANSLATE_SYSTEM = ("You translate image descriptions from Portuguese to English for Stable Diffusion. "
                    "Translate faithfully: keep every subject, object, style and color. Do NOT add emotions, "
                    "details or objects that are not in the text. Output only comma-separated English keywords, "
                    "one line, no explanations.")
# Exemplos few-shot que ensinam modelos pequenos o formato exato esperado pelo SD-Turbo
TRANSLATE_EXAMPLES = [
    ("um gato astronauta flutuando no espaço, ilustração digital colorida",
     "an astronaut cat wearing a space suit, floating in outer space, stars, colorful digital illustration"),
    ("logo minimalista de uma cafeteria chamada Grão, tons de marrom",
     "minimalist logo for a coffee shop named Grão, coffee bean icon, brown tones, flat vector design"),
    ("foto de uma praia ao pôr do sol com coqueiros",
     "photo of a beach at sunset, palm trees, golden hour lighting, realistic photography"),
]
# Regex que remove o comando do usuário ("por favor gere uma imagem de...") deixando só o sujeito
REQUEST_PREFIX = re.compile(r"^\s*(por favor[,]?\s*)?(gere|gera|gerar|crie|cria|criar|fa[çc]a|desenhe|desenha|"
                            r"quero|me (mostre|d[eê]))\s+(uma?\s+)?(imagem|foto|ilustra[çc][ãa]o|desenho|arte|"
                            r"pintura)?\s*(de|do|da|com)?\s*", re.IGNORECASE)
# Regex para detectar se o modelo devolveu texto ainda em português em vez de inglês
PT_WORDS = re.compile(r"\b(um|uma|de|do|da|com|no|na|em|que|imagem|não)\b|[ãõçáéíóúâêô]", re.IGNORECASE)

def build_image_prompt(prompt, model):  # Converte pedido em português em prompt otimizado em inglês para o SD-Turbo
    """Pedido em português → prompt em inglês: limpa o pedido, o LLM só traduz, o código acrescenta qualidade."""
    subject = REQUEST_PREFIX.sub("", prompt.strip()).strip(" .!") or prompt.strip()  # Remove verbos de pedido
    messages = [{"role": "system", "content": TRANSLATE_SYSTEM}]  # Inicia conversa com instrução de tradução
    for pt, en in TRANSLATE_EXAMPLES:  # Injeta os exemplos few-shot
        messages += [{"role": "user", "content": pt}, {"role": "assistant", "content": en}]
    messages.append({"role": "user", "content": subject})  # Adiciona o sujeito real do usuário
    english = ""  # Armazenará a tradução validada
    for _ in range(2):  # Tenta até 2 vezes caso a primeira resposta venha em português
        try:  # Chama o Ollama com keep_alive=0 para liberar VRAM para o Stable Diffusion logo em seguida
            r = requests.post(f"{OLLAMA_URL}/api/chat", json={
                "model": IMAGE_PROMPT_MODEL or model, "stream": False, "think": False, "messages": messages,
                "options": {"num_ctx": 2048, "num_predict": 100, "temperature": 0.1},
                "keep_alive": 0}, timeout=(15, 180))  # keep_alive=0 descarrega o LLM da placa de vídeo
            r.raise_for_status()  # Verifica erro HTTP
            text = re.sub(r"<think>.*?</think>", "", r.json().get("message", {}).get("content", ""), flags=re.S | re.I).strip().strip('"')  # Limpa resposta
            text = text.splitlines()[0].strip() if text else ""  # Mantém apenas a primeira linha
        except requests.RequestException:  # Se falhar a comunicação com o Ollama
            break  # Sai do loop e usa o fallback
        if text and len(PT_WORDS.findall(text)) <= 1:  # Aceita se a saída estiver efetivamente em inglês
            english = text
            break
    base = english or subject  # Se a tradução falhar, usa o sujeito limpo original
    return f"{base}, {QUALITY_TAGS}"  # Anexa tags de qualidade visual

def sse(obj):  # Formata um dicionário Python como evento Server-Sent Events (SSE)
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

def save_messages(chat_id, model, prompt, answer, image=None):  # Persiste pergunta e resposta no banco SQLite
    timestamp = now()  # Marca de tempo única para o turno
    with db() as conn:  # Abre transação no banco
        count = conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,)).fetchone()[0]  # Verifica se é a 1ª mensagem
        conn.execute("INSERT INTO messages (chat_id,role,content,created_at) VALUES (?,?,?,?)",  # Salva mensagem do usuário
                     (chat_id, "user", prompt, timestamp))
        conn.execute("INSERT INTO messages (chat_id,role,content,image,created_at) VALUES (?,?,?,?,?)",  # Salva resposta do assistente
                     (chat_id, "assistant", answer, image, timestamp))
        if count == 0:  # Na primeira mensagem, usa o início do prompt como título da conversa
            title = prompt.replace("\n", " ")[:52] + ("…" if len(prompt) > 52 else "")  # Trunca título em 52 chars
            conn.execute("UPDATE chats SET title=?,model=?,updated_at=? WHERE id=?", (title, model, timestamp, chat_id))
        else:  # Nas demais mensagens, apenas atualiza modelo e data de modificação
            conn.execute("UPDATE chats SET model=?,updated_at=? WHERE id=?", (model, timestamp, chat_id))

def create_image(prompt, model, size):  # Orquestra tradução do prompt, geração PNG e gravação em workspace/imagens/
    """Pedido em português → prompt em inglês → imagem salva. Devolve (nome_arquivo, texto_resposta)."""
    sd_prompt = build_image_prompt(prompt, model)  # Traduz e enriquece o prompt
    png, width, height = imagem.generate(sd_prompt, size)  # Gera os bytes PNG via SD-Turbo ou WebUI
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)  # Garante que workspace/imagens/ exista
    name = uuid.uuid4().hex + ".png"  # Gera nome único hexadecimal para o arquivo
    (IMAGES_DIR / name).write_bytes(png)  # Salva o arquivo PNG no disco
    answer = (f"Imagem gerada ({width}×{height}), salva em workspace/imagens/{name}.\n\n"  # Mensagem exibida no chat
              f"Prompt usado:\n```text\n{sd_prompt}\n```")
    return name, answer  # Retorna o nome do arquivo e o texto de confirmação

def image_stream(chat_id, model, prompt, size):  # Gerador SSE que transmite progresso e resultado da geração de imagem
    try:  # Captura erros de rede, dependência ou inferência para enviar amigavelmente via SSE
        yield sse({"status": "Gerando imagem… (a primeira vez baixa o modelo, ~2,6 GB)"})  # Status inicial na UI
        name, answer = create_image(prompt, model, size)  # Gera e salva a imagem
        save_messages(chat_id, model, prompt, answer, name)  # Registra turno no SQLite com referência à imagem
        yield sse({"token": answer, "image": name})  # Envia texto + nome do arquivo para renderizar a imagem
        yield sse({"done": True, "model": model, "chat_id": chat_id})  # Sinaliza fim do stream
    except requests.RequestException as exc:  # Erro de rede (ex.: WebUI externo fora do ar)
        yield sse({"error": f"Falha na API de imagem: {exc}"})
    except ImportError:  # Bibliotecas de imagem não instaladas
        yield sse({"error": "Gerador de imagem não instalado. Rode: pip install -r requirements-imagem.txt"})
    except Exception as exc:  # Qualquer outro erro inesperado
        yield sse({"error": f"Falha ao gerar imagem: {exc}"})

@app.post("/api/generate")  # Endpoint principal do chat: roteia entre imagem, pesquisa web ou código/texto (SSE)
def generate():
    data = request.get_json(silent=True) or {}  # Lê payload JSON da requisição
    prompt = str(data.get("prompt", "")).strip()  # Extrai e limpa o prompt do usuário
    model = str(data.get("model") or DEFAULT_MODEL).strip()  # Extrai o modelo selecionado
    chat_id = str(data.get("chat_id") or "").strip()  # Extrai o ID da conversa ativa
    if not prompt: return jsonify({"error": "Digite uma solicitação antes de gerar."}), 400  # Valida prompt vazio
    if len(prompt) > 12000: return jsonify({"error": "A solicitação é muito longa (máximo de 12.000 caracteres)."}), 400  # Limite de tamanho
    if not model or len(model) > 100: return jsonify({"error": "Nome de modelo inválido."}), 400  # Valida nome do modelo
    with db() as conn:  # Valida se o chat existe e carrega o histórico de mensagens
        chat = conn.execute("SELECT id FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat: return jsonify({"error": "Conversa não encontrada. Crie uma nova conversa."}), 404
        history = conn.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()
    mode = str(data.get("mode") or "auto")  # Modo escolhido na interface: auto, codigo, imagem ou web
    if mode == "imagem" or (mode == "auto" and wants_image(prompt, model)):  # Roteia para geração de imagem
        size = str(data.get("size") or "quadrado")  # Formato desejado (quadrado, paisagem ou retrato)
        return Response(stream_with_context(image_stream(chat_id, model, prompt, size)), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # Retorna stream SSE da imagem
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]  # Inicia contexto com o papel de engenheiro de software
    messages.extend({"role": m["role"], "content": m["content"]} for m in history[-6:])  # Inclui últimas 6 mensagens de histórico
    # Detecta quando o usuário pede um site completo em arquivo único HTML/CSS/JS para reforçar o formato em modelos pequenos
    lower_prompt = prompt.lower()
    asks_web_stack = ("html" in lower_prompt and "css" in lower_prompt and
                      ("javascript" in lower_prompt or " js" in lower_prompt or "js " in lower_prompt))
    asks_to_build_site = any(word in lower_prompt for word in ("crie um site", "criar um site", "crie um portfólio", "crie um portfolio", "crie um portifolio", "site html", "página html", "pagina html"))
    asks_single_file = any(word in lower_prompt for word in ("junto", "único", "unico", "mesmo arquivo", "num código só", "um código só", "tudo junto"))
    if asks_to_build_site or (asks_web_stack and asks_single_file):  # Anexa instrução reforçada de bloco HTML único
        prompt_for_model = prompt + "\n\nINSTRUÇÃO DE FORMATO E ENTREGA: produza o site funcionando, não descreva um projeto. Responda com EXATAMENTE UM bloco ```html contendo o documento completo, CSS dentro de <style> e JavaScript dentro de <script>. Não gere blocos CSS/JS separados, não entregue apenas especificações, não repita seções e não invente URLs. Inclua conteúdo, layout responsivo, cores solicitadas e interações funcionais."
    else:  # Para pedidos normais, mantém o prompt original intacto
        prompt_for_model = prompt
    use_web = mode == "web" or (mode == "auto" and busca.needs_search(prompt))  # Decide se vai pesquisar na internet

    def generate_stream():  # Gerador SSE que faz busca opcional e transmite tokens do Ollama em tempo real
        full_answer = ""  # Acumula a resposta completa para salvar no banco ao final
        results = []  # Armazena resultados da pesquisa web, se houver
        try:  # Captura falhas de rede/Ollama para informar via SSE
            user_content = prompt_for_model  # Conteúdo padrão enviado ao modelo
            if use_web:  # Se a pesquisa na internet foi ativada
                yield sse({"status": "Pesquisando na internet…"})  # Mostra status na interface
                results = busca.search(prompt)  # Executa busca (atalhos ao vivo ou DuckDuckGo + lxml)
                if results:  # Se encontrou resultados
                    user_content = busca.context_for_model(results, prompt_for_model)  # Monta prompt com dados encontrados
                    messages[0] = {"role": "system", "content": busca.SEARCH_SYSTEM}  # Troca papel para assistente de pesquisa
                else:  # Se estiver sem internet ou sem resultados
                    yield sse({"status": "Sem resultados da internet; respondendo com o que o modelo sabe…"})
            messages.append({"role": "user", "content": user_content})  # Anexa a pergunta atual ao contexto
            with requests.post(f"{OLLAMA_URL}/api/chat", json={  # Chama o Ollama em modo streaming
                "model": model, "messages": messages, "stream": True,
                "options": {"num_ctx": NUM_CTX, "num_predict": NUM_PREDICT, "temperature": 0.2},
                "keep_alive": "30m"}, stream=True, timeout=(15, 600)) as response:
                response.raise_for_status()  # Verifica se o Ollama aceitou a requisição
                for line in response.iter_lines(decode_unicode=True):  # Lê cada linha JSON enviada pelo Ollama
                    if not line: continue  # Ignora linhas vazias
                    packet = json.loads(line)  # Decodifica o pacote JSON
                    token = packet.get("message", {}).get("content", "")  # Extrai o próximo pedaço de texto
                    if token:  # Se há texto novo
                        full_answer += token  # Acumula na resposta final
                        yield "data: " + json.dumps({"token": token}, ensure_ascii=False) + "\n\n"  # Envia token ao navegador
                    if packet.get("done"):  # Encerra quando o Ollama sinaliza conclusão
                        break
            if not full_answer:  # Se o modelo terminou sem gerar nenhum texto
                yield "data: " + json.dumps({"error": "O modelo não retornou conteúdo. Tente novamente."}, ensure_ascii=False) + "\n\n"
                return
            if results:  # Anexa lista clicável/legível de fontes ao final da resposta quando houve busca
                fontes = busca.sources_markdown(results)
                full_answer += fontes
                yield sse({"token": fontes})
            save_messages(chat_id, model, prompt, full_answer)  # Salva pergunta e resposta no SQLite
            yield "data: " + json.dumps({"done": True, "model": model, "chat_id": chat_id}, ensure_ascii=False) + "\n\n"  # Finaliza stream
        except requests.ConnectionError:  # Ollama não está rodando
            yield "data: " + json.dumps({"error": "Não foi possível conectar ao Ollama. Verifique se ele está aberto."}, ensure_ascii=False) + "\n\n"
        except requests.Timeout:  # Tempo limite excedido
            yield "data: " + json.dumps({"error": "O Ollama excedeu o tempo limite. Tente uma solicitação menor."}, ensure_ascii=False) + "\n\n"
        except requests.RequestException as exc:  # Outros erros HTTP do Ollama
            yield "data: " + json.dumps({"error": f"Falha na comunicação com o Ollama: {exc}"}, ensure_ascii=False) + "\n\n"
        except Exception as exc:  # Erro genérico de processamento
            yield "data: " + json.dumps({"error": f"Falha ao processar a resposta: {exc}"}, ensure_ascii=False) + "\n\n"
    return Response(stream_with_context(generate_stream()), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

def ask_llm(model, messages, predict=320, temperature=0.3):  # Chamada síncrona ao Ollama usada pelo modo voz
    r = requests.post(f"{OLLAMA_URL}/api/chat", json={  # Envia histórico + pergunta sem streaming
        "model": model, "messages": messages, "stream": False, "think": False,  # think=False garante resposta rápida em qwen3
        "options": {"num_ctx": NUM_CTX, "num_predict": predict, "temperature": temperature}, "keep_alive": "30m"},
        timeout=(15, 300))  # Timeout de leitura generoso para CPU/modelos maiores
    r.raise_for_status()  # Verifica erro HTTP
    content = r.json().get("message", {}).get("content", "")  # Lê o conteúdo retornado
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S | re.I).strip()  # Remove eventuais tags <think>

@app.post("/api/voice")  # Endpoint da conversa por voz: áudio WAV -> Whisper -> (busca/imagem/LLM) -> Piper WAV
def voice_turn():
    """Uma rodada da conversa por voz: áudio → texto → (busca/imagem) → resposta → áudio."""
    audio = request.files.get("audio")  # Arquivo WAV 16 kHz enviado pelo static/voz.js
    chat_id = str(request.form.get("chat_id") or "")  # ID da conversa ativa
    model = str(request.form.get("model") or DEFAULT_MODEL)[:100]  # Modelo Ollama escolhido
    if not audio:  # Valida se o áudio chegou no formulário multipart
        return jsonify({"error": "Nenhum áudio recebido."}), 400
    with db() as conn:  # Valida conversa e carrega histórico recente
        if not conn.execute("SELECT id FROM chats WHERE id=?", (chat_id,)).fetchone():
            return jsonify({"error": "Conversa não encontrada."}), 404
        history = conn.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()
    try:  # Transcreve a fala do usuário usando Whisper local na CPU
        text = voz.transcribe(audio.read())
    except ImportError:  # Se faster-whisper/piper não estiverem instalados
        return jsonify({"error": "Módulo de voz não instalado. Rode: pip install -r requirements.txt"}), 503
    if len(text) < 2:  # Se captou apenas ruído ou silêncio, devolve vazio para o navegador continuar ouvindo
        return jsonify({"text": "", "answer": "", "audio": None})

    image_name, results = None, []  # Inicializa variáveis de saída (imagem opcional e fontes de busca)
    try:  # Decide entre gerar imagem, pesquisar na web ou conversar direto
        if wants_image(text, model):  # Se o usuário pediu uma imagem por voz
            image_name, answer = create_image(text, model, "quadrado")  # Gera e salva a imagem
            spoken = "Pronto, gerei a imagem. Ela está no chat."  # Frase curta falada pelo Piper
        else:  # Conversa normal ou pesquisa na internet por voz
            use_search = busca.needs_search(text)  # Verifica se precisa buscar dados atuais
            if use_search:  # Executa busca enxuta (até 4 resultados)
                results = busca.search(text, max_results=4)
            system_prompt = voz.VOICE_SEARCH_SYSTEM if results else voz.VOICE_SYSTEM  # Escolhe prompt alinhado à fala
            messages = [{"role": "system", "content": system_prompt}]  # Inicia contexto do turno
            for m in history[-4:]:  # Inclui até 4 mensagens anteriores já limpas de HTML/código para não poluir a fala
                clean_hist = voz.clean_for_speech(m["content"])[:400]  # Limita cada item do histórico a 400 chars
                if clean_hist:  # Só adiciona se sobrou texto útil
                    messages.append({"role": m["role"], "content": clean_hist})
            if results:  # Monta contexto curto e limpo específico para resposta falada
                user_content = busca.context_for_voice(results, text)
            elif use_search:  # Se a pesquisa não retornou resultados (ex.: sem internet)
                user_content = (f"{text}\n\n(A pesquisa na internet não retornou resultados agora. "
                                "Responda brevemente se souber ou avise em uma frase que não foi possível pesquisar.)")
            else:  # Pergunta falada comum sem busca
                user_content = text
            messages.append({"role": "user", "content": user_content})  # Adiciona o turno atual
            raw_spoken = ask_llm(model, messages, predict=320, temperature=0.25 if results else 0.4)  # Gera resposta curta
            spoken = voz.clean_for_speech(raw_spoken) or "Desculpe, não consegui formular uma resposta agora. Pode repetir?"  # Higieniza para fala
            answer = spoken + (busca.sources_markdown(results) if results else "")  # No chat, mantém as fontes abaixo da resposta
    except requests.RequestException as exc:  # Erro ao falar com o Ollama
        return jsonify({"error": f"Falha ao falar com o Ollama: {exc}", "text": text}), 502
    save_messages(chat_id, model, text, answer, image_name)  # Salva o turno de voz no histórico SQLite
    wav = voz.speak(spoken)  # Sintetiza a resposta limpa em áudio WAV via Piper
    return jsonify({"text": text, "answer": answer, "image": image_name,  # Devolve transcrição, resposta e áudio base64
                    "audio": base64.b64encode(wav).decode()})

@app.post("/api/save")  # Salva um trecho de código como novo arquivo dentro de workspace/ (nunca sobrescreve)
def save_file():
    data=request.get_json(silent=True) or {}  # Lê caminho relativo e conteúdo do JSON
    relative_path=str(data.get("path","")).strip()  # Caminho informado pelo usuário
    content=data.get("content","")  # Texto/código a gravar
    if not relative_path or not isinstance(content,str): return jsonify({"error":"Informe o caminho e o conteúdo do arquivo."}),400  # Valida entrada
    if len(relative_path)>240 or len(content)>500000: return jsonify({"error":"Caminho ou conteúdo excede o limite permitido."}),400  # Limite de segurança
    rel=Path(relative_path)  # Converte string em objeto Path
    if rel.is_absolute() or ".." in rel.parts or not rel.parts: return jsonify({"error":"Caminho inválido. Use um caminho relativo dentro de workspace/."}),400  # Bloqueia path traversal
    destination=(WORKSPACE/rel).resolve()  # Resolve o caminho absoluto final
    if destination!=WORKSPACE and WORKSPACE not in destination.parents: return jsonify({"error":"Por segurança, só é permitido salvar dentro de workspace/."}),403  # Garante confinamento em workspace/
    try:  # Tenta criar subpastas e gravar o arquivo de forma exclusiva
        destination.parent.mkdir(parents=True,exist_ok=True)  # Cria subdiretórios necessários dentro de workspace/
        with destination.open("x", encoding="utf-8", newline="") as file:  # Modo "x" falha se o arquivo já existir (nunca sobrescreve)
            file.write(content)  # Escreve o conteúdo UTF-8
        return jsonify({"saved":True,"path":rel.as_posix()}),201  # Retorna 201 Created com caminho salvo
    except FileExistsError:  # Se já existe um arquivo com esse nome
        return jsonify({"error":f"O arquivo workspace/{rel.as_posix()} já existe. Escolha outro nome para preservar o arquivo anterior."}),409  # Retorna 409 Conflict
    except OSError as exc: return jsonify({"error":f"Não foi possível salvar o arquivo: {exc}"}),500  # Erro de sistema de arquivos

init_db()  # Garante que conversas.db e suas tabelas existam ao importar/iniciar o app
WORKSPACE.mkdir(exist_ok=True)  # Garante que a pasta workspace/ exista

if __name__=="__main__":  # Executa o servidor Flask apenas quando chamado diretamente (python app.py)
    app.run(host="127.0.0.1",port=5000,debug=False)  # Escuta somente localmente na porta 5000
