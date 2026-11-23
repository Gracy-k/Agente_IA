@echo off
REM Oculta a repeticao dos comandos na tela para manter a saida limpa
REM Isola variaveis de ambiente locais e ativa expansao atrasada (!VAR!) dentro de loops
setlocal enabledelayedexpansion
REM Muda a pagina de codigo do console Windows para UTF-8 (suporte a acentos)
chcp 65001 >nul

REM ============================================================================
REM  iniciar_e_testar.bat — Inicia Ollama + CodeLocal (Flask) e testa tudo
REM ============================================================================

REM Entra na pasta onde este arquivo .bat esta salvo (mesmo mudando de drive)
cd /d "%~dp0"
REM Define a URL padrao do servidor local do Ollama
set "OLLAMA_URL=http://127.0.0.1:11434"
REM Define a URL padrao do servidor web Flask do CodeLocal
set "APP_URL=http://127.0.0.1:5000"
REM Define o caminho completo do interpretador Python dentro do ambiente virtual .venv
set "PYTHON=%~dp0.venv\Scripts\python.exe"

REM Exibe linha em branco e cabecalho do script
echo.
echo === CodeLocal: Inicializacao e Teste Automatico ===
echo.

REM 1. Verifica se o ambiente virtual .venv foi criado
if not exist "%PYTHON%" (
    REM Informa erro caso o python.exe do .venv nao exista
    echo [ERRO] Ambiente virtual nao encontrado em: %PYTHON%
    REM Mostra os comandos necessarios para criar o ambiente virtual
    echo        Crie com:
    echo          py -3.12 -m venv .venv
    echo          .venv\Scripts\pip install -r requirements.txt
    REM Encerra pulando para o rotulo de falha
    goto :fail
)
REM Confirma que o Python do ambiente virtual foi localizado
echo [OK]   Python encontrado: %PYTHON%

REM 2. Testa se o Ollama ja esta respondendo na porta 11434
curl -fsS "%OLLAMA_URL%/api/tags" >nul 2>&1
REM Se errorlevel >= 1, o Ollama ainda nao esta rodando
if errorlevel 1 (
    REM Verifica se o executavel "ollama" existe no PATH do sistema
    where ollama >nul 2>&1
    REM Se nao encontrar o comando ollama, aborta com erro
    if errorlevel 1 (
        echo [ERRO] Comando "ollama" nao encontrado no PATH. Instale o Ollama primeiro.
        goto :fail
    )
    REM Avisa que vai iniciar o Ollama em segundo plano
    echo [INFO] Iniciando Ollama em segundo plano...
    REM Sobe "ollama serve" em background redirecionando logs para ollama.log
    start "" /B cmd /c "ollama serve > "%~dp0ollama.log" 2>&1"
    REM Flag para controlar quando o Ollama ficar pronto
    set "OLLAMA_OK=0"
    REM Aguarda ate 20 segundos testando a API do Ollama a cada 1 segundo
    for /L %%i in (1,1,20) do (
        REM So continua testando enquanto ainda nao respondeu
        if "!OLLAMA_OK!"=="0" (
            REM Pausa ~1 segundo usando ping local (funciona mesmo sem entrada interativa)
            ping -n 2 127.0.0.1 >nul
            REM Se /api/tags responder HTTP 200, marca OLLAMA_OK=1
            curl -fsS "%OLLAMA_URL%/api/tags" >nul 2>&1 && set "OLLAMA_OK=1"
        )
    )
    REM Se apos 20 segundos nao respondeu, falha e aponta o arquivo de log
    if "!OLLAMA_OK!"=="0" (
        echo [ERRO] Ollama nao respondeu em %OLLAMA_URL%. Veja ollama.log
        goto :fail
    )
    REM Confirma que o Ollama subiu com sucesso
    echo [OK]   Ollama iniciado em %OLLAMA_URL%
) else (
    REM Informa que o Ollama ja estava ativo antes do script rodar
    echo [OK]   Ollama ja esta rodando em %OLLAMA_URL%
)

REM 3. Testa se o servidor Flask (app.py) ja esta respondendo na porta 5000
curl -fsS "%APP_URL%/api/models" >nul 2>&1
REM Se errorlevel >= 1, o servidor Flask ainda nao esta rodando
if errorlevel 1 (
    REM Avisa que vai iniciar o servidor CodeLocal em segundo plano
    echo [INFO] Iniciando servidor CodeLocal ^(app.py^) em segundo plano...
    REM Sobe app.py em background redirecionando logs para codelocal.log
    start "" /B cmd /c ""%PYTHON%" "%~dp0app.py" > "%~dp0codelocal.log" 2>&1"
    REM Flag para controlar quando o Flask ficar pronto
    set "APP_OK=0"
    REM Aguarda ate 30 segundos testando /api/models a cada 1 segundo
    for /L %%i in (1,1,30) do (
        REM So testa enquanto o servidor ainda nao respondeu
        if "!APP_OK!"=="0" (
            REM Pausa ~1 segundo usando ping local
            ping -n 2 127.0.0.1 >nul
            REM Se /api/models responder HTTP 200, marca APP_OK=1
            curl -fsS "%APP_URL%/api/models" >nul 2>&1 && set "APP_OK=1"
        )
    )
    REM Se apos 30 segundos o Flask nao respondeu, aborta e indica codelocal.log
    if "!APP_OK!"=="0" (
        echo [ERRO] CodeLocal nao respondeu em %APP_URL%. Veja codelocal.log
        goto :fail
    )
    REM Confirma que o servidor CodeLocal iniciou
    echo [OK]   CodeLocal iniciado em %APP_URL%
) else (
    REM Informa que o servidor CodeLocal ja estava ativo
    echo [OK]   CodeLocal ja esta rodando em %APP_URL%
)

REM 4. Executa a bateria de testes Python embutida no final deste proprio arquivo .bat
echo.
echo [INFO] Executando testes ponta a ponta em %APP_URL%...
REM Le este arquivo (%~f0), extrai tudo apos o marcador #__PYTHON_TESTS__ e executa no Python do .venv
"%PYTHON%" -c "import sys; code = open(sys.argv[1], encoding='utf-8').read().rsplit('#__PYTHON_TESTS__', 1)[1]; exec(compile(code, sys.argv[1], 'exec'))" "%~f0"
REM Se qualquer assercao Python falhar (codigo de saida != 0), vai para :fail
if errorlevel 1 goto :fail

REM Exibe resumo de sucesso e o endereco para abrir no navegador
echo.
echo [OK]   Todos os testes passaram!
echo [INFO] Acesse o CodeLocal no navegador: %APP_URL%
echo.
REM Pausa a janela apenas se aberto por duplo clique no Explorer (e sem a flag --nopause)
echo %CMDCMDLINE% | find /i "/c" >nul && if /i not "%~1"=="--nopause" pause
REM Encerra o script com codigo 0 (sucesso) antes do bloco Python
exit /b 0

REM Rotulo executado em caso de erro em qualquer etapa
:fail
echo.
echo [ERRO] Falha durante a inicializacao ou testes.
REM Mantem a janela aberta no duplo clique para permitir ler o erro
echo %CMDCMDLINE% | find /i "/c" >nul && if /i not "%~1"=="--nopause" pause
REM Encerra o script com codigo 1 (falha)
exit /b 1

REM #__PYTHON_TESTS__
import base64  # Decodifica o audio WAV retornado em base64 pelo /api/voice
import io  # Empacota os bytes WAV em memoria para envio multipart
import json  # Decodifica os eventos JSON enviados pelo stream SSE
import os  # Le a variavel de ambiente APP_URL definida pelo .bat
import re  # Valida que a resposta falada nao contem tags HTML
import sys  # Permite encerrar com erro (sys.exit(1)) se algum teste falhar
import requests  # Cliente HTTP para chamar as rotas da API do CodeLocal

APP_URL = os.environ["APP_URL"].rstrip("/")  # URL base do servidor Flask em teste

def check(cond, msg):  # Funcao auxiliar de assercao que imprime [OK] ou aborta com [ERRO]
    if not cond:  # Se a condicao falhar
        print(f"[ERRO] {msg}", file=sys.stderr)  # Mostra o erro no stderr
        sys.exit(1)  # Retorna codigo de erro para o .bat
    print(f"[OK]   {msg}")  # Imprime confirmacao de sucesso

# Teste 1: Verifica conexao com o Ollama e lista de modelos instalados
r = requests.get(f"{APP_URL}/api/models", timeout=15)  # Consulta /api/models
check(r.status_code == 200, f"GET /api/models -> HTTP {r.status_code}")  # Garante HTTP 200
models = r.json().get("models", [])  # Extrai lista de modelos disponiveis
check(len(models) > 0, "Modelos no Ollama: " + ", ".join(models[:4]))  # Garante ao menos 1 modelo instalado
model = next((m for m in models if "instruct" in m or "chat" in m), models[0])  # Prefere modelo instruct/chat
print(f"[INFO] Modelo selecionado para os testes: {model}")  # Exibe o modelo escolhido

# Teste 2: Verifica disponibilidade dos modulos de imagem e voz
r = requests.get(f"{APP_URL}/api/status", timeout=30)  # Consulta /api/status
check(r.status_code == 200, f"GET /api/status -> HTTP {r.status_code}")  # Garante HTTP 200
st = r.json()  # Decodifica status retornado
print(f"[INFO] Status imagem: {st.get('imagem')}")  # Mostra status do SD-Turbo
print(f"[INFO] Status voz:    {st.get('voz')}")  # Mostra status do Whisper + Piper

# Teste 3: Cria uma conversa temporaria no SQLite para rodar os testes sem sujar historicos reais
r = requests.post(f"{APP_URL}/api/chats", json={"title": "Teste automatico", "model": model}, timeout=15)
check(r.status_code == 201, f"POST /api/chats -> HTTP {r.status_code}")  # Garante HTTP 201 Created
chat_id = r.json()["id"]  # Guarda o ID da conversa temporaria

try:  # Garante no bloco finally que a conversa temporaria sera apagada mesmo se um teste falhar
    # Teste 4: Chat de texto com pesquisa web via streaming SSE
    r = requests.post(
        f"{APP_URL}/api/generate",  # Rota de geracao em streaming
        json={"prompt": "Qual a cotação do dólar hoje?", "model": model, "chat_id": chat_id, "mode": "web"},  # Forca modo web
        stream=True,  # Ativa leitura incremental dos eventos SSE
        timeout=120,  # Timeout generoso para busca + inferencia local
    )
    check(r.status_code == 200, f"POST /api/generate (web) -> HTTP {r.status_code}")  # Garante HTTP 200
    tokens = []  # Acumula os pedacos de texto recebidos no stream
    for line in r.iter_lines(decode_unicode=True):  # Le linha por linha do SSE
        if line and line.startswith("data: "):  # Processa apenas linhas de dados SSE
            pkt = json.loads(line[6:])  # Decodifica o JSON apos "data: "
            if "error" in pkt:  # Falha imediatamente se o servidor reportar erro no stream
                check(False, f"Erro no stream: {pkt.get('error')}")
            if pkt.get("token"):  # Acumula cada token gerado
                tokens.append(pkt["token"])
            if pkt.get("done"):  # Encerra leitura ao receber o sinal de conclusao
                break
    ans = "".join(tokens).strip()  # Junta todos os tokens na resposta completa
    check(len(ans) > 15, f"Resposta chat recebida ({len(ans)} chars)")  # Garante resposta nao vazia
    print(f"[INFO] Previa chat: {ans.splitlines()[0][:140]}")  # Exibe primeira linha da resposta

    # Teste 5: Fluxo completo de voz com pesquisa (WAV -> Whisper -> Busca -> Ollama -> Piper WAV)
    if st.get("voz", {}).get("available"):  # So executa se Whisper e Piper estiverem disponiveis
        from modulos import voz  # Importa o sintetizador local para gerar o audio de entrada
        wav_in = voz.speak("Pesquise qual é a cotação do dólar hoje.")  # Gera fala de teste em WAV
        rv = requests.post(  # Envia o WAV para a rota /api/voice como o navegador faz
            f"{APP_URL}/api/voice",
            data={"chat_id": chat_id, "model": model},  # Metadados do turno
            files={"audio": ("fala.wav", io.BytesIO(wav_in), "audio/wav")},  # Arquivo WAV em memoria
            timeout=180,  # Timeout para transcricao + busca + LLM + sintese
        )
        check(rv.status_code == 200, f"POST /api/voice -> HTTP {rv.status_code}")  # Garante HTTP 200
        vd = rv.json()  # Decodifica resposta JSON da voz
        spoken = (vd.get("answer") or "").split("\n\nFontes:")[0].strip()  # Separa o trecho falado das fontes
        raw_wav = base64.b64decode(vd.get("audio") or "")  # Decodifica o audio WAV retornado
        check(bool(vd.get("text")), f"Whisper transcreveu: {vd.get('text')}")  # Confirma transcricao nao vazia
        check(len(spoken) > 10, f"Resposta falada: {spoken[:160]}")  # Confirma resposta falada valida
        check(not re.search(r"<[a-zA-Z][^>]*>", spoken), "Resposta de voz sem tags HTML")  # Garante ausencia de HTML
        check(len(raw_wav) > 1000, f"Audio WAV de resposta gerado ({len(raw_wav)} bytes)")  # Garante WAV valido
    else:  # Caso o modulo de voz nao esteja instalado
        print("[AVISO] Modulo de voz indisponivel — teste de /api/voice pulado.")
finally:  # Limpeza obrigatoria ao terminar os testes
    requests.delete(f"{APP_URL}/api/chats/{chat_id}", timeout=10)  # Remove a conversa temporaria do banco
    print("[OK]   Conversa de teste removida do banco.")  # Confirma limpeza
