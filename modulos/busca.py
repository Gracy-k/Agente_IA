"""Pesquisa na internet pelo DuckDuckGo (gratuito, sem chave de API).

Fluxo: o app percebe que a pergunta precisa de informação atual → busca os 5 primeiros
resultados → entrega os resumos ao modelo → o modelo responde citando as fontes [1], [2]...
"""
import re

SEARCH_WORDS = (
    "pesquise", "pesquisa ", "pesquisar", "procure", "busque", "buscar na internet", "na internet", "na web",
    "google", "notícia", "noticia", "hoje", "agora", "atual", "atualmente", "último", "ultimo", "última",
    "ultima", "recente", "cotação", "cotacao", "preço", "preco", "quanto custa", "clima", "previsão",
    "previsao", "placar", "resultado do jogo", "lançamento", "lancamento", "quem ganhou", "quem é o atual",
    "2025", "2026", "2027",
)
CLEAN_PREFIX = re.compile(r"^\s*(por favor[,]?\s*)?(p?esquis\w*|procur\w*|busc\w*)\s+((n|d)?[ao]s?\s+)?(internet|web|google)?\s*(sobre|por|como)?\s*",
                          re.IGNORECASE)


# ---------- Ferramentas rápidas: dados ao vivo que as páginas só mostram via JavaScript ----------
CURRENCIES = {"dólar": "USD", "dolar": "USD", "euro": "EUR", "libra": "GBP", "bitcoin": "BTC", "iene": "JPY",
              "peso argentino": "ARS"}
WEATHER_CODES = {0: "céu limpo", 1: "poucas nuvens", 2: "parcialmente nublado", 3: "nublado", 45: "neblina",
                 48: "neblina", 51: "garoa", 53: "garoa", 55: "garoa forte", 61: "chuva fraca", 63: "chuva",
                 65: "chuva forte", 80: "pancadas de chuva", 81: "pancadas de chuva", 82: "temporal",
                 95: "trovoadas", 96: "trovoadas com granizo", 99: "trovoadas com granizo"}


def _currency(low):
    import requests
    codes = sorted({code for name, code in CURRENCIES.items() if name in low})
    if not codes or not any(w in low for w in ("cotação", "cotacao", "quanto", "valor", "preço", "preco", "hoje")):
        return None
    try:
        pairs = ",".join(f"{c}-BRL" for c in codes)
        data = requests.get(f"https://economia.awesomeapi.com.br/json/last/{pairs}", timeout=6).json()
        lines = [f"{v['name']}: compra R$ {float(v['bid']):.4f}, venda R$ {float(v['ask']):.4f}, "
                 f"variação {v['pctChange']}% (atualizado em {v['create_date']})" for v in data.values()]
        return "Cotação ao vivo (AwesomeAPI): " + "; ".join(lines)
    except Exception:
        return None


def _weather(text):
    import requests
    low = text.lower().rstrip("?!. ")
    if not any(w in low for w in ("clima", "previsão do tempo", "previsao do tempo", "temperatura", "vai chover",
                                  "chuva", "tempo em", "tempo hoje")):
        return None
    # cidade = palavras depois de "em/no/na/para", parando em "hoje", "amanhã" ou "agora"
    match = re.search(r"\b(?:em|no|na|para)\s+([a-zà-ú]+(?:\s+(?!hoje|amanhã|agora)[a-zà-ú]+){0,3})", low)
    city = match.group(1) if match else "são paulo"
    city = re.split(r"\s+(?:hoje|amanhã|amanha|agora)\b", city)[0].title()
    try:
        geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                           params={"name": city, "count": 1, "language": "pt", "countryCode": "BR"}, timeout=6).json()
        if not geo.get("results"):
            geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                               params={"name": city, "count": 1, "language": "pt"}, timeout=6).json()
        place = geo["results"][0]
        w = requests.get("https://api.open-meteo.com/v1/forecast", timeout=6, params={
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto", "forecast_days": 2,
            "current": "temperature_2m,weather_code,relative_humidity_2m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"}).json()
        cur, day = w["current"], w["daily"]
        return (f"Clima ao vivo em {place['name']} ({place.get('admin1', '')}) via Open-Meteo: agora "
                f"{cur['temperature_2m']}°C, {WEATHER_CODES.get(cur['weather_code'], 'tempo variável')}, umidade "
                f"{cur['relative_humidity_2m']}%. Hoje: mínima {day['temperature_2m_min'][0]}°C, máxima "
                f"{day['temperature_2m_max'][0]}°C, chance de chuva {day['precipitation_probability_max'][0]}%. "
                f"Amanhã: {day['temperature_2m_min'][1]}°C a {day['temperature_2m_max'][1]}°C, chance de chuva "
                f"{day['precipitation_probability_max'][1]}%.")
    except Exception:
        return None


def quick_facts(text):
    """Respostas exatas e instantâneas para perguntas comuns (cotação e clima)."""
    return _currency(text.lower()) or _weather(text)


def needs_search(text):
    low = text.lower()
    return any(w in low for w in SEARCH_WORDS)


def search(query, max_results=5):
    """Devolve uma lista de {title, href, body}. Lista vazia se não houver internet."""
    from ddgs import DDGS
    fact = quick_facts(query)
    if fact:  # ferramenta rápida resolveu: não precisa abrir páginas
        return [{"title": fact.split(":")[0], "href": "https://economia.awesomeapi.com.br" if "AwesomeAPI" in fact
                 else "https://open-meteo.com", "body": fact}]
    query = CLEAN_PREFIX.sub("", query).strip(" ?.!") or query
    low = query.lower()
    news = any(w in low for w in ("notícia", "noticia", "quem ganhou", "placar", "resultado do jogo", "aconteceu"))
    for region in ("br-pt", None, "br-pt"):  # o buscador às vezes falha por instantes: tenta de novo
        try:
            kwargs = {"region": region} if region else {}
            if news:  # notícias trazem o fato no próprio resumo
                topic = re.sub(r"(?i)\b(quais|qual|as|os|últimas|ultimas|notícias|noticias|de|do|da|hoje|"
                               r"sobre|me|fale|recentes)\b", " ", query).strip() or query
                items = list(DDGS().news(f"{topic} notícias", timelimit="w", max_results=max_results,
                                         **kwargs))[:max_results]  # só da última semana
                results = [{"title": f"{n.get('title', '')} ({n.get('date', '')[:10]})", "href": n.get("url", ""),
                            "body": n.get("body", "")} for n in items]
            else:
                results = list(DDGS().text(query, max_results=max_results, **kwargs))[:max_results]
            if not results and news:  # sem notícias: tenta a busca comum
                results = list(DDGS().text(query, max_results=max_results, **kwargs))[:max_results]
            if results:
                return enrich(results, query)
        except Exception:
            pass
    return []


SEARCH_SYSTEM = ("Você é um assistente de pesquisa em português do Brasil. Você recebe dados atuais da internet "
                 "e responde de forma curta e direta usando esses dados, com números, datas e fontes [1].")

PAGE_CHARS = 1500  # quanto texto de cada página o modelo lê (pouco = rápido e cabe na memória)


def _page_text(url):
    """Baixa uma página e devolve só o texto (sem menus, scripts e estilos). Leve: sem navegador."""
    import html
    import requests
    try:
        r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0 (CodeLocal)"})
        r.raise_for_status()
        if "html" not in r.headers.get("Content-Type", ""):
            return ""
        page = re.sub(r"(?is)<(script|style|nav|header|footer|aside|noscript|svg)[^>]*>.*?</\1>", " ", r.text)
        text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", page))
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        return ""


def _relevant_part(text, query, size=PAGE_CHARS):
    """Pega o trecho da página onde as palavras da pergunta aparecem mais."""
    words = [w for w in re.findall(r"\w{4,}", query.lower())]
    if not words or len(text) <= size:
        return text[:size]
    low = text.lower()
    best, best_score = 0, -1
    for start in range(0, max(1, len(text) - size), size // 3):
        score = sum(low.count(w, start, start + size) for w in words)
        if score > best_score:
            best, best_score = start, score
    return text[best:best + size]


def enrich(results, query, pages=2):
    """Lê o conteúdo das primeiras páginas (em paralelo) para o modelo ter dados de verdade."""
    from concurrent.futures import ThreadPoolExecutor
    top = results[:pages]
    with ThreadPoolExecutor(max_workers=pages) as pool:
        texts = list(pool.map(lambda r: _page_text(r.get("href", "")), top))
    for r, text in zip(top, texts):
        if text:
            r["page"] = _relevant_part(text, query)
    return results


def context_for_model(results, question):
    """Monta a mensagem para o modelo: pergunta → dados → instrução.
    Modelos pequenos prestam mais atenção no FIM do texto, por isso a instrução vem por último."""
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"Fonte [{i}]: {r.get('page') or r.get('body', '')}")
    from datetime import date
    return (f"Data de hoje: {date.today().strftime('%d/%m/%Y')}.\nPergunta: {question}\n\n"
            "Dados encontrados AGORA na internet:\n" + "\n".join(lines) + "\n\n"
            f"Com base nos dados acima, responda: {question}\n"
            "Explique com suas palavras, de forma organizada "
            "(em passos, se for receita ou tutorial), e cite a fonte entre colchetes, como [1].")


def sources_markdown(results):
    return "\n\nFontes:\n" + "\n".join(f"[{i}] {r.get('title', '')} — {r.get('href', '')}"
                                       for i, r in enumerate(results, 1))
