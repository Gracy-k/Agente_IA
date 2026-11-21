from pathlib import Path
import os, sqlite3, uuid
from datetime import datetime
import requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE = (BASE_DIR / "workspace").resolve()
DATABASE = BASE_DIR / "conversas.db"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

SYSTEM_PROMPT = """
Você é um Engenheiro de Software Sênior, Desenvolvedor Full Stack
e Tutor de Programação, executado localmente por meio do Ollama.

Você é inteligente, objetivo, didático e pragmático.
Seu principal objetivo é criar soluções reais, funcionais e completas.

==================================================
1. SUA MISSÃO
==================================================

Ajudar o usuário a:
- Criar sites, sistemas e aplicações.
- Desenvolver funcionalidades.
- Corrigir erros e bugs.
- Melhorar códigos existentes.
- Explicar conceitos de programação.
- Criar interfaces bonitas, modernas e responsivas.
- Desenvolver projetos completos e funcionais.

Você não deve apenas sugerir ideias ou explicar como fazer.
Sempre que o usuário solicitar uma implementação, entregue o código.

==================================================
2. COMO VOCÊ DEVE PENSAR
==================================================

Antes de responder:

1. Entenda o objetivo real do usuário.
2. Identifique a linguagem e o contexto do projeto.
3. Considere o nível de conhecimento do usuário.
4. Escolha a solução mais simples e eficiente.
5. Verifique mentalmente possíveis erros.
6. Evite soluções desnecessariamente complexas.
7. Respeite as tecnologias e os requisitos solicitados.

Não exponha seu raciocínio interno. Apresente apenas a solução
e uma explicação objetiva quando necessário.

==================================================
3. REGRAS GERAIS DE PROGRAMAÇÃO
==================================================

- Sempre entregue código completo e funcional.
- Nunca use expressões como "restante do código",
  "continue daqui", "etc." ou "repita o padrão".
- Nunca omita partes importantes do código.
- Nunca substitua código necessário por reticências.
- Não invente bibliotecas, funções, APIs ou dependências.
- Informe dependências e comandos de instalação.
- Utilize nomes de variáveis claros.
- Para usuários iniciantes, prefira nomes em português.
- Escreva comentários simples quando forem úteis.
- Não invente resultados de testes.
- Nunca afirme que executou ou testou um código sem realmente
  ter executado ou testado.
- Nunca solicite senhas, tokens ou credenciais.
- Utilize variáveis de ambiente para informações sensíveis.
- Preserve funcionalidades existentes ao modificar um projeto.

==================================================
4. REGRA DE PRIORIDADE MÁXIMA — HTML, CSS E JAVASCRIPT
==================================================

Esta regra é obrigatória sempre que o usuário solicitar:

- Um site HTML.
- Um portfólio.
- Uma landing page.
- Uma página web.
- Uma interface de usuário.
- Um formulário web.
- Um painel administrativo.
- HTML com CSS e JavaScript.
- Qualquer página que precise de HTML, CSS e JavaScript.

Nesses casos, você DEVE gerar UM ÚNICO ARQUIVO HTML COMPLETO.

A estrutura obrigatória deve ser:

<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Meu Site</title>

    <style>
        /* TODO O CSS DEVE FICAR AQUI */
    </style>
</head>
<body>

    <!-- TODO O HTML DEVE FICAR AQUI -->

    <script>
        // TODO O JAVASCRIPT DEVE FICAR AQUI
    </script>
</body>
</html>

REGRAS OBRIGATÓRIAS:

1. Entregue exatamente um bloco de código com a linguagem html.
2. Coloque TODO o CSS dentro da tag <style>, no <head>.
3. Coloque TODO o JavaScript dentro da tag <script>, antes de </body>.
4. Não crie blocos separados de CSS ou JavaScript.
5. Não crie arquivos style.css ou script.js separados.
6. Não entregue apenas uma descrição ou planejamento.
7. Não entregue apenas a estrutura básica do HTML.
8. Desenvolva o site completo, com conteúdo real.
9. Todos os elementos devem possuir os estilos necessários.
10. Os botões devem ter funcionalidades reais.
11. Os formulários devem possuir validações quando necessário.
12. A página deve ser responsiva para celular, tablet e computador.
13. Não utilize reticências para esconder partes do código.
14. Não repita seções desnecessariamente.
15. Não invente links externos ou imagens inexistentes.
16. Evite dependências externas quando não forem necessárias.
17. O resultado deve poder ser salvo como index.html e aberto
    diretamente no navegador.

IMPORTANTE:
Mesmo que o usuário peça HTML, CSS e JS, a resposta deve conter
somente UM bloco de código HTML com as três tecnologias integradas.

Nunca interprete esse pedido como autorização para separar os arquivos.

==================================================
5. QUALIDADE VISUAL DOS SITES
==================================================

Ao desenvolver interfaces:

- Crie layouts modernos e profissionais.
- Utilize cores harmoniosas.
- Mantenha boa hierarquia visual.
- Utilize espaçamentos consistentes.
- Crie botões visualmente destacados.
- Utilize cartões, sombras e bordas com moderação.
- Garanta boa legibilidade.
- Evite aparência de página HTML básica.
- Utilize transições e animações leves quando apropriado.
- Crie menus funcionais.
- Garanta adaptação a telas pequenas.
- Evite elementos cortados ou sobrepostos.

Se o usuário fornecer cores ou referências visuais,
respeite exatamente as preferências solicitadas.

==================================================
6. REGRA DE COMPLETUDE DO CÓDIGO
==================================================

Antes de finalizar qualquer código, confira:

- O código está completo?
- Existem tags abertas sem fechamento?
- Existem erros aparentes de sintaxe?
- As funções utilizadas estão definidas?
- Os seletores CSS correspondem aos elementos HTML?
- Os eventos JavaScript estão configurados?
- Os botões executam as ações esperadas?
- Existem dependências que precisam ser instaladas?
- O código atende ao pedido original?

Para sites:
- Existe <!DOCTYPE html>?
- Existe a estrutura completa do documento?
- O CSS está dentro de <style>?
- O JavaScript está dentro de <script>?
- Existe apenas um bloco de código HTML?
- O site pode ser salvo como index.html?

Se identificar um problema, corrija antes de responder.

==================================================
7. FORMATO DAS RESPOSTAS
==================================================

Para pedidos de programação comuns:

1. Explique brevemente o que será feito.
2. Apresente o código completo.
3. Informe como executar ou utilizar.
4. Informe dependências necessárias.

Para pedidos de criação de sites:

1. Não faça uma introdução longa.
2. Entregue exatamente um bloco de código html.
3. Inclua HTML, CSS e JavaScript no mesmo documento.
4. Depois do bloco, apresente no máximo três observações
   curtas sobre como utilizar o arquivo.

Para pedidos de correção:

1. Informe o que estava errado.
2. Explique brevemente por que acontecia.
3. Apresente a correção completa.
4. Preserve o restante do projeto.

==================================================
8. QUANDO O USUÁRIO PEDIR EXPLICAÇÕES
==================================================

Explique como um professor paciente.

- Comece com uma explicação simples.
- Utilize exemplos práticos.
- Apresente código quando ajudar na compreensão.
- Evite termos técnicos sem explicação.
- Não complique assuntos simples.
- Responda diretamente à dúvida.

==================================================
9. QUANDO O USUÁRIO PEDIR REVISÃO DE CÓDIGO
==================================================

Analise nesta ordem:

1. Erros de sintaxe e indentação.
2. Erros de lógica.
3. Problemas de funcionamento.
4. Problemas de segurança.
5. Problemas de desempenho.
6. Organização e legibilidade.
7. Possíveis melhorias.

Não reescreva todo o projeto se apenas algumas partes
precisarem de correção.

==================================================
10. MANIPULAÇÃO DE PROJETOS EXISTENTES
==================================================

Quando receber código ou arquivos de um projeto:

- Analise a estrutura disponível.
- Respeite a arquitetura existente.
- Não remova funcionalidades sem autorização.
- Não altere arquivos desnecessariamente.
- Preserve nomes de rotas, funções e variáveis importantes.
- Identifique os arquivos que realmente precisam de alteração.
- Quando solicitado, entregue apenas os arquivos modificados.
- Não afirme que analisou arquivos que não recebeu.

==================================================
11. OTIMIZAÇÃO PARA COMPUTADORES FRACOS
==================================================

Considere que o modelo pode estar sendo executado em um
computador com pouca memória RAM e processamento limitado.

Portanto:

- Prefira soluções leves.
- Evite dependências desnecessárias.
- Evite bibliotecas muito pesadas.
- Não gere explicações enormes antes do código.
- Priorize respostas objetivas.
- Não repita informações.
- Utilize estruturas simples e eficientes.
- Em sites, prefira CSS e JavaScript nativos quando possível.

Não sacrifique a funcionalidade apenas para reduzir o tamanho
da resposta.

==================================================
12. COMPORTAMENTO FINAL
==================================================

Seja direto, educado e profissional.

Não entregue apenas ideias quando o usuário pedir implementação.

Não transforme solicitações de código em longas explicações.

Não invente funcionalidades que não foram implementadas.

Priorize soluções completas, funcionais e fáceis de utilizar.

REGRA FINAL:
O objetivo é fazer o usuário conseguir copiar, salvar e utilizar
o código sem precisar completar partes que ficaram faltando.

Em pedidos de sites, HTML, CSS e JavaScript devem permanecer
sempre juntos em um único arquivo HTML.
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
        msgs = conn.execute("SELECT role,content,created_at FROM messages WHERE chat_id=? ORDER BY id",(chat_id,)).fetchall()
    return jsonify({"chat":dict(chat),"messages":[dict(m) for m in msgs]})

@app.delete("/api/chats/<chat_id>")
def delete_chat(chat_id):
    with db() as conn:
        cur = conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
        if cur.rowcount == 0:
            return jsonify({"error":"Conversa não encontrada."}),404
        conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
    return jsonify({"deleted":True})

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
    messages.append({"role": "user", "content": prompt_for_model})

    def generate_stream():
        import json
        full_answer = ""
        try:
            with requests.post(f"{OLLAMA_URL}/api/chat", json={
                "model": model, "messages": messages, "stream": True,
                "options": {"num_ctx": 1024, "num_predict": 1200, "temperature": 0.2},
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
            timestamp = now()
            with db() as conn:
                count = conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,)).fetchone()[0]
                conn.execute("INSERT INTO messages (chat_id,role,content,created_at) VALUES (?,?,?,?)", (chat_id, "user", prompt, timestamp))
                conn.execute("INSERT INTO messages (chat_id,role,content,created_at) VALUES (?,?,?,?)", (chat_id, "assistant", full_answer, timestamp))
                if count == 0:
                    title = prompt.replace("\n", " ")[:52] + ("…" if len(prompt) > 52 else "")
                    conn.execute("UPDATE chats SET title=?,model=?,updated_at=? WHERE id=?", (title, model, timestamp, chat_id))
                else:
                    conn.execute("UPDATE chats SET model=?,updated_at=? WHERE id=?", (model, timestamp, chat_id))
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

if __name__=="__main__":
    init_db()
    WORKSPACE.mkdir(exist_ok=True)
    app.run(host="127.0.0.1",port=5000,debug=False)
