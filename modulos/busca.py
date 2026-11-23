"""Pesquisa na internet pelo DuckDuckGo (gratuito, sem chave de API).

Fluxo: o app percebe que a pergunta precisa de informação atual → busca os 5 primeiros
resultados → entrega os resumos ao modelo → o modelo responde citando as fontes [1], [2]...
"""
import re  # Expressões regulares para detectar intenção de busca e limpar textos/consultas

# Palavras-chave que indicam que o usuário quer dados atuais ou uma pesquisa na internet
SEARCH_WORDS = (
    "pesquise", "pesquisa ", "pesquisar", "procure", "busque", "buscar na internet", "na internet", "na web",
    "google", "notícia", "noticia", "hoje", "agora", "atual", "atualmente", "último", "ultimo", "última",
    "ultima", "recente", "cotação", "cotacao", "preço", "preco", "quanto custa", "clima", "previsão",
    "previsao", "placar", "resultado do jogo", "lançamento", "lancamento", "quem ganhou", "quem é o atual",
    "2025", "2026", "2027",
)
# Regex para remover comandos iniciais ("por favor pesquise na internet sobre...") antes de consultar o buscador
CLEAN_PREFIX = re.compile(r"^\s*(por favor[,]?\s*)?(p?esquis\w*|procur\w*|busc\w*)\s+((n|d)?[ao]s?\s+)?(internet|web|google)?\s*(sobre|por|como)?\s*",
                          re.IGNORECASE)


# ---------- Ferramentas rápidas: dados ao vivo que as páginas só mostram via JavaScript ----------
# Mapa de nomes de moedas em português para seus códigos ISO usados na AwesomeAPI
CURRENCIES = {"dólar": "USD", "dolar": "USD", "euro": "EUR", "libra": "GBP", "bitcoin": "BTC", "iene": "JPY",
              "peso argentino": "ARS"}
# Tabela de códigos climáticos WMO (Open-Meteo) traduzidos para português do Brasil
WEATHER_CODES = {0: "céu limpo", 1: "poucas nuvens", 2: "parcialmente nublado", 3: "nublado", 45: "neblina",
                 48: "neblina", 51: "garoa", 53: "garoa", 55: "garoa forte", 61: "chuva fraca", 63: "chuva",
                 65: "chuva forte", 80: "pancadas de chuva", 81: "pancadas de chuva", 82: "temporal",
                 95: "trovoadas", 96: "trovoadas com granizo", 99: "trovoadas com granizo"}


def _currency(low):  # Consulta cotação ao vivo de moedas em relação ao Real (BRL) via AwesomeAPI
    import requests  # Importação local para manter o módulo leve
    codes = sorted({code for name, code in CURRENCIES.items() if name in low})  # Detecta moedas citadas na pergunta
    if not codes or not any(w in low for w in ("cotação", "cotacao", "quanto", "valor", "preço", "preco", "hoje")):  # Confirma intenção de cotação
        return None  # Não é pergunta de cotação
    try:  # Tenta consultar a API gratuita AwesomeAPI
        pairs = ",".join(f"{c}-BRL" for c in codes)  # Monta os pares de moeda (ex.: USD-BRL,EUR-BRL)
        data = requests.get(f"https://economia.awesomeapi.com.br/json/last/{pairs}", timeout=6).json()  # Faz requisição com timeout curto
        lines = [f"{v['name']}: compra R$ {float(v['bid']):.4f}, venda R$ {float(v['ask']):.4f}, "  # Formata valores de compra/venda
                 f"variação {v['pctChange']}% (atualizado em {v['create_date']})" for v in data.values()]  # Inclui variação e horário
        return "Cotação ao vivo (AwesomeAPI): " + "; ".join(lines)  # Retorna resumo pronto para o LLM
    except Exception:  # Se a API falhar ou estiver sem internet
        return None  # Deixa seguir para a busca comum


def _weather(text):  # Consulta clima ao vivo e previsão de 2 dias via Open-Meteo
    import requests  # Importação local
    low = text.lower().rstrip("?!. ")  # Normaliza texto em minúsculas removendo pontuação final
    if not any(w in low for w in ("clima", "previsão do tempo", "previsao do tempo", "temperatura", "vai chover",  # Verifica palavras de clima
                                  "chuva", "tempo em", "tempo hoje")):
        return None  # Não é pergunta de clima
    # Extrai o nome da cidade depois de "em/no/na/para", parando antes de "hoje", "amanhã" ou "agora"
    match = re.search(r"\b(?:em|no|na|para)\s+([a-zà-ú]+(?:\s+(?!hoje|amanhã|agora)[a-zà-ú]+){0,3})", low)
    city = match.group(1) if match else "são paulo"  # Usa São Paulo como padrão se nenhuma cidade for citada
    city = re.split(r"\s+(?:hoje|amanhã|amanha|agora)\b", city)[0].title()  # Limpa advérbios de tempo e capitaliza o nome
    try:  # Tenta geocodificar a cidade e buscar a previsão
        geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",  # Busca primeiro no Brasil (countryCode=BR)
                           params={"name": city, "count": 1, "language": "pt", "countryCode": "BR"}, timeout=6).json()
        if not geo.get("results"):  # Se não encontrou no Brasil (ex.: cidade internacional)
            geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",  # Tenta busca global sem filtro de país
                               params={"name": city, "count": 1, "language": "pt"}, timeout=6).json()
        place = geo["results"][0]  # Pega o primeiro resultado com latitude e longitude
        w = requests.get("https://api.open-meteo.com/v1/forecast", timeout=6, params={  # Consulta clima atual + previsão de 2 dias
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": 2,
            "current": "temperature_2m,weather_code,relative_humidity_2m",  # Temperatura, condição e umidade agora
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"}).json()  # Máx/mín e chance de chuva
        cur, day = w["current"], w["daily"]  # Atalhos para os blocos atual e diário
        return (f"Clima ao vivo em {place['name']} ({place.get('admin1', '')}) via Open-Meteo: agora "  # Monta resumo factual
                f"{cur['temperature_2m']}°C, {WEATHER_CODES.get(cur['weather_code'], 'tempo variável')}, umidade "
                f"{cur['relative_humidity_2m']}%. Hoje: mínima {day['temperature_2m_min'][0]}°C, máxima "
                f"{day['temperature_2m_max'][0]}°C, chance de chuva {day['precipitation_probability_max'][0]}%. "
                f"Amanhã: {day['temperature_2m_min'][1]}°C a {day['temperature_2m_max'][1]}°C, chance de chuva "
                f"{day['precipitation_probability_max'][1]}%.")
    except Exception:  # Em caso de erro de rede ou cidade inexistente
        return None  # Deixa seguir para a busca comum


def quick_facts(text):  # Tenta responder instantaneamente perguntas de cotação ou clima
    """Respostas exatas e instantâneas para perguntas comuns (cotação e clima)."""
    return _currency(text.lower()) or _weather(text)  # Retorna o primeiro atalho que resolver


def needs_search(text):  # Decide se a pergunta precisa de pesquisa na internet
    low = text.lower()  # Converte para minúsculas para comparação insensível a maiúsculas
    return any(w in low for w in SEARCH_WORDS)  # Retorna True se encontrar qualquer gatilho


def search(query, max_results=5):  # Executa a busca (atalhos rápidos ou DuckDuckGo + leitura das páginas)
    """Devolve uma lista de {title, href, body}. Lista vazia se não houver internet."""
    from ddgs import DDGS  # Importa o cliente DuckDuckGo Search
    fact = quick_facts(query)  # Verifica primeiro se cotação ou clima já resolvem direto
    if fact:  # Ferramenta rápida resolveu: não precisa abrir páginas HTML
        return [{"title": fact.split(":")[0], "href": "https://economia.awesomeapi.com.br" if "AwesomeAPI" in fact
                 else "https://open-meteo.com", "body": fact}]  # Devolve no mesmo formato padrão dos resultados
    query = CLEAN_PREFIX.sub("", query).strip(" ?.!") or query  # Limpa prefixos como "pesquise sobre..."
    low = query.lower()  # Versão minúscula para detectar se é consulta de notícias
    news = any(w in low for w in ("notícia", "noticia", "quem ganhou", "placar", "resultado do jogo", "aconteceu"))  # Flag de notícias
    for region in ("br-pt", None, "br-pt"):  # Tenta até 3 vezes (o buscador pode oscilar momentaneamente)
        try:  # Protege contra erros de rede ou rate-limit
            kwargs = {"region": region} if region else {}  # Define região Brasil quando informada
            if news:  # Para notícias, usa o endpoint de notícias da última semana
                topic = re.sub(r"(?i)\b(quais|qual|as|os|últimas|ultimas|notícias|noticias|de|do|da|hoje|"  # Remove palavras genéricas
                               r"sobre|me|fale|recentes)\b", " ", query).strip() or query  # Mantém o assunto principal
                items = list(DDGS().news(f"{topic} notícias", timelimit="w", max_results=max_results,  # Busca notícias recentes
                                         **kwargs))[:max_results]  # Limita ao número máximo pedido
                results = [{"title": f"{n.get('title', '')} ({n.get('date', '')[:10]})", "href": n.get("url", ""),  # Padroniza campos
                            "body": n.get("body", "")} for n in items]
            else:  # Busca web comum
                results = list(DDGS().text(query, max_results=max_results, **kwargs))[:max_results]  # Busca páginas de texto
            if not results and news:  # Se a busca de notícias vier vazia, tenta busca comum como fallback
                results = list(DDGS().text(query, max_results=max_results, **kwargs))[:max_results]
            if results:  # Se encontrou resultados válidos
                return enrich(results, query)  # Lê e limpa o conteúdo real das primeiras páginas
        except Exception:  # Em caso de erro nesta tentativa
            pass  # Tenta a próxima região da lista
    return []  # Retorna lista vazia se estiver sem internet ou tudo falhar


# Prompt de sistema usado no chat de texto quando há pesquisa na internet
SEARCH_SYSTEM = ("Você é um assistente de pesquisa em português do Brasil. Você recebe dados atuais da internet "
                 "e responde de forma curta e direta usando esses dados, com números, datas e fontes [1].")

PAGE_CHARS = 1500  # Limite de caracteres lidos de cada página para o chat de texto
VOICE_SOURCE_CHARS = 420  # Limite mais curto por fonte para o modo voz (evita o LLM copiar texto bruto)

# Tags HTML estruturais/interativas que nunca contêm o texto principal do artigo
_DROP_TAGS = ("script", "style", "noscript", "svg", "iframe", "nav", "header", "footer", "aside",
              "form", "button", "select", "input", "menu", "dialog", "template", "head")
# Expressão regular para descartar linhas típicas de menus, avisos de cookies e publicidade
_NOISE_PATTERNS = re.compile(
    r"(?i)^(jump to content|pular para o conteúdo|ir para o conteúdo|seguir no google|publicidade|"
    r"anúncio|compartilhar|assine|cadastre-se|entrar|fazer login|aceitar cookies|política de privacidade|"
    r"voltar ao topo|leia também|veja também|foto:\s*divulgação|crédito:)"
)
# Trechos característicos de referências bibliográficas da Wikipédia e botões de sites de receitas
_NOISE_SUBSTRINGS = ("consultado em ", "cópia arquivada em ", "↑ ", "ver meu livro", "salvo em seu livro")


def _clean_text_block(raw):  # Limpa entidades HTML, comentários, tags soltas e marcadores [1]/[editar]
    import html  # Decodificador padrão de entidades HTML
    text = html.unescape(raw or "")  # Converte &amp;, &nbsp;, etc. em texto normal
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)  # Remove comentários HTML residuais
    text = re.sub(r"<[^>]+>", " ", text)  # Remove qualquer tag HTML restante
    text = re.sub(r"\[\d+\]|\[editar(?:\s*\|\s*editar código-fonte)?\]", "", text, flags=re.I)  # Limpa notas [1] e [editar]
    text = re.sub(r"\s+", " ", text).strip()  # Normaliza espaços e quebras de linha
    return text  # Retorna o bloco de texto limpo


def _is_useful_paragraph(p):  # Filtra fragmentos curtos, menus, breadcrumbs e referências inúteis
    if len(p) < 35:  # Ignora textos muito curtos (geralmente botões ou rótulos de UI)
        return False
    low = p.lower()  # Versão minúscula para comparar substrings de ruído
    if _NOISE_PATTERNS.match(p) or any(s in low for s in _NOISE_SUBSTRINGS):  # Descarta linhas de navegação/rodapé
        return False
    if p.count("|") >= 3 or p.count("»") >= 2 or p.count("•") >= 4:  # Descarta barras de menu e trilhas de navegação
        return False
    return True  # Parágrafo aprovado como conteúdo real


def _extract_with_lxml(raw_bytes, encoding):  # Faz parse estrutural do HTML com lxml e extrai só os parágrafos principais
    from lxml import html as lxml_html  # Parser HTML rápido já instalado como dependência do ddgs
    text_html = raw_bytes.decode(encoding or "utf-8", errors="replace")  # Decodifica bytes com a codificação correta
    doc = lxml_html.fromstring(text_html)  # Constrói a árvore DOM do documento HTML
    for comment in doc.xpath("//comment()"):  # Percorre todos os comentários HTML da página
        parent = comment.getparent()  # Obtém o nó pai do comentário
        if parent is not None:  # Se tiver pai válido
            parent.remove(comment)  # Remove o comentário da árvore
    # XPath unificado para remover scripts, estilos, menus, rodapés, formulários, referências e banners
    drop_xpath = (
        "//script|//style|//noscript|//svg|//iframe|//nav|//header|//footer|//aside|"
        "//form|//button|//select|//input|//menu|//dialog|//template|//head|"
        "//sup[contains(@class,'reference')]|"
        "//*[contains(@class,'reflist') or contains(@class,'references') or contains(@class,'navbox') "
        "or contains(@class,'infobox') or contains(@class,'mw-editsection') or contains(@class,'toc') "
        "or contains(@class,'cookie') or contains(@class,'breadcrumb') or contains(@class,'share') "
        "or contains(@class,'related') or contains(@class,'sidebar') or contains(@class,'newsletter')]|"
        "//*[@role='navigation' or @role='banner' or @role='contentinfo' or @aria-hidden='true']"
    )
    for node in doc.xpath(drop_xpath):  # Remove todos os nós de ruído encontrados
        parent = node.getparent()  # Obtém o elemento pai
        if parent is not None:  # Garante que o nó não é a raiz
            parent.remove(node)  # Exclui o nó da árvore DOM

    # Procura primeiro o contêiner principal do conteúdo (<article>, <main> ou #mw-content-text da Wikipédia)
    root = None  # Elemento raiz de onde vamos extrair os parágrafos
    for candidate in doc.xpath("//article|//main|//*[@id='mw-content-text']"):  # Testa candidatos principais
        if len(candidate.text_content().strip()) >= 200:  # Só aceita se tiver texto substancial
            root = candidate  # Define como raiz principal
            break  # Para no primeiro bloco principal válido
    if root is None:  # Se a página não usa <article>/<main>
        bodies = doc.xpath("//body")  # Busca a tag <body>
        root = bodies[0] if bodies else doc  # Usa <body> ou o documento inteiro como fallback

    paragraphs = []  # Lista de parágrafos limpos extraídos
    seen = set()  # Conjunto para evitar parágrafos duplicados
    for el in root.xpath(".//p|.//li|.//h2|.//h3"):  # Percorre parágrafos, itens e subtítulos do conteúdo
        p = _clean_text_block(" ".join(el.itertext()))  # Extrai e limpa o texto interno do elemento
        if _is_useful_paragraph(p) and p not in seen:  # Mantém apenas parágrafos úteis e únicos
            seen.add(p)  # Registra como já adicionado
            paragraphs.append(p)  # Adiciona à lista final
    if paragraphs:  # Se conseguiu extrair parágrafos estruturados
        return "\n".join(paragraphs)  # Retorna um parágrafo por linha
    return _clean_text_block(" ".join(root.itertext()))  # Fallback: texto geral limpo da raiz


def _page_text(url):  # Baixa uma página web e retorna apenas o texto limpo do conteúdo principal
    """Baixa uma página e devolve apenas parágrafos limpos do conteúdo principal (sem HTML, menus ou scripts)."""
    import requests  # Cliente HTTP
    try:  # Protege contra timeouts, SSL ou sites que bloqueiam bots
        r = requests.get(url, timeout=6, headers={  # Faz download rápido com cabeçalhos em português
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CodeLocal/1.0",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
        })
        r.raise_for_status()  # Ignora páginas com erro HTTP (403, 404, 500...)
        ctype = r.headers.get("Content-Type", "")  # Lê o tipo MIME retornado pelo servidor
        if "html" not in ctype.lower():  # Ignora PDFs, imagens e arquivos binários
            return ""
        # Corrige o padrão ISO-8859-1 do requests quando o servidor omite charset UTF-8 no header
        encoding = r.encoding if (r.encoding and r.encoding.lower() != "iso-8859-1") else (r.apparent_encoding or "utf-8")
        try:  # Tenta extração estrutural limpa via lxml
            return _extract_with_lxml(r.content, encoding)
        except Exception:  # Fallback seguro com regex caso o HTML seja malformado ou lxml falhe
            raw = r.content.decode(encoding, errors="replace")  # Decodifica com tolerância a caracteres inválidos
            raw = re.sub(r"<!--.*?-->", " ", raw, flags=re.S)  # Remove comentários HTML
            for tag in _DROP_TAGS:  # Remove blocos de scripts, estilos e menus
                raw = re.sub(rf"(?is)<{tag}[^>]*>.*?</{tag}>", " ", raw)
            return _clean_text_block(raw)  # Remove tags restantes e normaliza espaços
    except Exception:  # Qualquer erro de rede retorna string vazia (o snippet do DDG ainda será usado)
        return ""


def _relevant_part(text, query, size=PAGE_CHARS):  # Escolhe os parágrafos mais relevantes sem cortar palavras no meio
    """Seleciona os parágrafos mais relevantes sem cortar palavras no meio nem cair em rodapés."""
    if not text:  # Se não há texto extraído
        return ""
    paragraphs = [p.strip() for p in text.splitlines() if p.strip()]  # Separa em parágrafos não vazios
    if len(paragraphs) <= 1:  # Se só existe um bloco contínuo de texto
        if len(text) <= size:  # Se já cabe no limite
            return text
        cut = text[:size].rsplit(" ", 1)[0]  # Corta no último espaço inteiro antes do limite
        return cut.strip()

    words = [w for w in re.findall(r"\w{4,}", query.lower())]  # Extrai palavras-chave da pergunta (4+ letras)
    scored = []  # Lista de tuplas (pontuação, índice_original, parágrafo)
    for idx, p in enumerate(paragraphs):  # Avalia cada parágrafo
        low = p.lower()  # Converte para minúsculas
        hits = sum(min(low.count(w), 3) for w in words) if words else 0  # Conta ocorrências (com teto 3 por palavra)
        lead_bonus = max(0, 3 - idx)  # Dá bônus aos 3 primeiros parágrafos (onde geralmente está a definição/resumo)
        scored.append((hits + lead_bonus, idx, p))  # Armazena pontuação e posição original

    chosen_idx = set()  # Índices dos parágrafos selecionados
    total = 0  # Total de caracteres acumulados
    for _score, idx, p in sorted(scored, key=lambda x: (-x[0], x[1])):  # Ordena por maior pontuação e depois por ordem natural
        if total + len(p) + 1 > size and chosen_idx:  # Pula parágrafos que estouram o limite se já temos conteúdo
            continue
        chosen_idx.add(idx)  # Marca o parágrafo como escolhido
        total += len(p) + 1  # Atualiza contagem de caracteres
        if total >= size:  # Para assim que atingir o tamanho alvo
            break

    selected = "\n".join(paragraphs[i] for i in sorted(chosen_idx))  # Reordena os escolhidos na sequência original do texto
    if len(selected) > size:  # Garante que mesmo um único parágrafo muito longo respeite o limite
        selected = selected[:size].rsplit(" ", 1)[0].strip()  # Corta sem quebrar palavras
    return selected  # Devolve o recorte final limpo


def enrich(results, query, pages=2):  # Baixa e limpa em paralelo o conteúdo das primeiras páginas dos resultados
    """Lê o conteúdo das primeiras páginas (em paralelo) para o modelo ter dados de verdade."""
    from concurrent.futures import ThreadPoolExecutor  # Pool de threads para baixar páginas simultaneamente
    top = results[:pages]  # Seleciona apenas as primeiras N páginas para manter a busca rápida
    with ThreadPoolExecutor(max_workers=pages) as pool:  # Executa os downloads em paralelo
        texts = list(pool.map(lambda r: _page_text(r.get("href", "")), top))  # Extrai o texto limpo de cada URL
    for r, text in zip(top, texts):  # Associa cada texto extraído ao respectivo resultado
        if text:  # Só grava se a página devolveu conteúdo útil
            r["page"] = _relevant_part(text, query)  # Salva apenas os parágrafos mais relevantes
    return results  # Devolve a lista enriquecida


def context_for_model(results, question):  # Formata os resultados de busca para o chat de texto
    """Monta a mensagem para o modelo no chat de texto: pergunta → dados → instrução.
    Modelos pequenos prestam mais atenção no FIM do texto, por isso a instrução vem por último."""
    lines = []  # Linhas formatadas de cada fonte
    for i, r in enumerate(results, 1):  # Numera as fontes a partir de [1]
        snippet = _clean_text_block(r.get("page") or r.get("body", ""))  # Prefere texto limpo da página; senão usa resumo do DDG
        if snippet:  # Ignora fontes vazias
            lines.append(f"Fonte [{i}] ({r.get('title', '').strip()}): {snippet}")  # Monta linha com índice e título
    from datetime import date  # Importa data atual para situar o modelo no tempo
    return (f"Data de hoje: {date.today().strftime('%d/%m/%Y')}.\nPergunta: {question}\n\n"
            "Dados encontrados AGORA na internet:\n" + "\n".join(lines) + "\n\n"
            f"Com base nos dados acima, responda: {question}\n"
            "Explique com suas palavras, de forma organizada "
            "(em passos, se for receita ou tutorial), e cite a fonte entre colchetes, como [1].")


def context_for_voice(results, question):  # Formata um contexto enxuto e conversacional específico para o modo voz
    """Monta um resumo limpo e compacto para resposta FALADA (modo voz).
    Evita despejar texto bruto de páginas e alinha a instrução final ao estilo conversacional."""
    lines = []  # Lista de resumos curtos por fonte
    for r in results[:4]:  # Limita às 4 melhores fontes para não sobrecarregar modelos pequenos
        title = _clean_text_block(r.get("title", ""))  # Limpa o título da fonte
        body = _clean_text_block(r.get("body", ""))  # Limpa o resumo curto do buscador
        page = _clean_text_block(r.get("page", ""))  # Limpa o conteúdo extraído da página
        snippet = page if len(page) >= 80 else body  # Usa a página só se tiver conteúdo substancial; senão usa o resumo
        if len(snippet) > VOICE_SOURCE_CHARS:  # Corta trechos muito longos sem quebrar palavras
            snippet = snippet[:VOICE_SOURCE_CHARS].rsplit(" ", 1)[0].strip() + "."
        if snippet:  # Se houver texto útil
            prefix = f"{title}: " if title and not snippet.lower().startswith(title.lower()[:30]) else ""  # Evita repetir o título
            lines.append(f"- {prefix}{snippet}")  # Adiciona à lista de fatos
    from datetime import date  # Data atual para respostas temporais (hoje, agora...)
    return (f"Data de hoje: {date.today().strftime('%d/%m/%Y')}.\n"
            f"Pergunta falada pelo usuário: {question}\n\n"
            "Informações encontradas na internet:\n" + "\n".join(lines) + "\n\n"
            "INSTRUÇÕES PARA RESPOSTA POR VOZ:\n"
            "- Responda diretamente à pergunta em português do Brasil, com suas próprias palavras, "
            "como numa conversa falada natural.\n"
            "- Use de 2 a 4 frases curtas, claras e completas.\n"
            "- NÃO copie texto bruto dos sites, NÃO use listas, passos numerados, markdown, "
            "links, tags HTML nem marcações como [1].")


def sources_markdown(results):  # Gera o rodapé de fontes exibido no chat após respostas com pesquisa
    return "\n\nFontes:\n" + "\n".join(f"[{i}] {r.get('title', '')} — {r.get('href', '')}"  # Lista numerada [1] Título — URL
                                       for i, r in enumerate(results, 1))
