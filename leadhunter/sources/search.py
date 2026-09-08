from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup

from leadhunter.config import CONFIG
from leadhunter.http import fetch, fetch_json

SRC = "busca"

# Dominios que nunca sao o site proprio da empresa.
AGGREGATORS = {
    "mercadolivre.com.br", "mercadolibre.com", "produto.mercadolivre.com.br",
    "olx.com.br", "americanas.com.br", "magazineluiza.com.br", "shopee.com.br",
    "amazon.com.br", "elo7.com.br", "enjoei.com.br", "aliexpress.com",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "pinterest.com", "reclameaqui.com.br",
    "cnpj.biz", "econodata.com.br", "casadosdados.com.br", "cnpja.com",
    "consultasocio.com", "empresascnpj.com", "cnpj.info", "solutudo.com.br",
    "apontador.com.br", "telelistas.net", "guiamais.com.br", "encontraempresa.com.br",
    "google.com", "bing.com", "duckduckgo.com", "wikipedia.org", "jusbrasil.com.br",
    "gov.br", "sintegraws.com.br", "empresaqui.com.br", "cnpjs.rocks",
    "inteligen.com.br", "cnpjcheck.com.br", "situacaocadastral.info",
    "empresasdobrasil.com", "basecadastral.com.br", "cnpjrocks.com",
    "consultascnpj.com", "normasabnt.org", "cnpjtransparencia.com.br",
    "serasaexperian.com.br", "diariocidade.com", "descubraonline.com",
}
# Agregadores que expoem CNPJ na propria URL ou no titulo.
CNPJ_DIRECTORIES = (
    "cnpj.biz", "econodata.com.br", "casadosdados.com.br", "consultasocio.com",
    "empresascnpj.com", "cnpja.com", "cnpj.info", "empresaqui.com.br", "cnpjs.rocks",
    "inteligen.com.br", "cnpjcheck.com.br", "situacaocadastral.info",
    "empresasdobrasil.com", "basecadastral.com.br", "cnpjrocks.com",
    "consultascnpj.com", "normasabnt.org", "cnpjtransparencia.com.br",
)


def root_domain(url: str) -> str:
    host = urlsplit(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_aggregator(url: str) -> bool:
    host = root_domain(url)
    return any(host == d or host.endswith("." + d) for d in AGGREGATORS)


def _ddg(query: str, limit: int) -> list[dict]:
    status, html = fetch(
        "https://html.duckduckgo.com/html/",
        method="POST",
        params={"q": query, "kl": "br-pt"},
    )
    if status != 200 or not html:
        status, html = fetch("https://lite.duckduckgo.com/lite/", params={"q": query})
    if status != 200 or not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for anchor in soup.select("a.result__a, a.result-link"):
        href = anchor.get("href", "")
        if "duckduckgo.com/l/" in href or href.startswith("//duckduckgo.com/l/"):
            qs = parse_qs(urlsplit(href).query)
            href = unquote(qs.get("uddg", [""])[0])
        if not href.startswith("http"):
            continue
        container = anchor.find_parent(["div", "tr", "table"])
        snippet = ""
        if container:
            node = container.select_one(".result__snippet, .result-snippet")
            snippet = node.get_text(" ", strip=True) if node else ""
        out.append({"title": anchor.get_text(" ", strip=True), "url": href, "snippet": snippet})
        if len(out) >= limit:
            break
    return out


def _serpapi(query: str, limit: int) -> list[dict]:
    data = fetch_json("https://serpapi.com/search.json", params={
        "q": query, "api_key": CONFIG.serpapi_key, "google_domain": "google.com.br",
        "gl": "br", "hl": "pt-br", "num": limit,
    })
    if not data:
        return []
    return [
        {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
        for r in data.get("organic_results", [])[:limit]
    ]


def _google_cse(query: str, limit: int) -> list[dict]:
    data = fetch_json("https://www.googleapis.com/customsearch/v1", params={
        "key": CONFIG.google_cse_key, "cx": CONFIG.google_cse_cx, "q": query,
        "gl": "br", "hl": "pt-BR", "num": min(limit, 10),
    })
    if not data:
        return []
    return [
        {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
        for r in data.get("items", [])[:limit]
    ]


def _brave(query: str, limit: int) -> list[dict]:
    data = fetch_json(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "country": "br", "search_lang": "pt", "count": limit},
        headers={"X-Subscription-Token": CONFIG.brave_key, "Accept": "application/json"},
    )
    if not data:
        return []
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""),
         "snippet": r.get("description", "")}
        for r in (data.get("web") or {}).get("results", [])[:limit]
    ]


def search(query: str, limit: int = 10) -> list[dict]:
    provider = CONFIG.search_provider
    fns = {"serpapi": _serpapi, "google_cse": _google_cse, "brave": _brave, "duckduckgo": _ddg}
    results = fns[provider](query, limit)
    if not results and provider != "duckduckgo":
        results = _ddg(query, limit)
    return results


def cnpj_candidates_from_results(results: list[dict]) -> list[str]:
    """Diretorios de CNPJ carregam o numero na URL ou no snippet."""
    from leadhunter.normalize import find_cnpjs, valid_cnpj

    out: list[str] = []
    for res in results:
        host = root_domain(res["url"])
        blob = f"{res['url']} {res.get('title', '')} {res.get('snippet', '')}"
        if any(host.endswith(d) for d in CNPJ_DIRECTORIES):
            for raw in re.findall(r"\b\d{14}\b", res["url"]):
                if valid_cnpj(raw) and raw not in out:
                    out.append(raw)
        for cnpj in find_cnpjs(blob):
            if cnpj not in out:
                out.append(cnpj)
    return out


def official_sites(results: list[dict], limit: int = 3) -> list[str]:
    out: list[str] = []
    for res in results:
        url = res["url"]
        if is_aggregator(url):
            continue
        host = root_domain(url)
        if host and host not in [root_domain(u) for u in out]:
            out.append(f"https://{host}")
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Dono a partir do snippet do buscador
#
# Os diretorios de CNPJ escrevem o quadro societario direto na descricao que o
# buscador indexa ("Fulano de Tal (Socio-Administrador)"). Isso da o nome do dono
# sem gastar consulta na Receita -- e continua funcionando quando a API esta fora.
# ---------------------------------------------------------------------------

_WORD = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ']+"
_LINK = r"(?:[Dd][AaEeOo][Ss]?|[Ee])"
_FULL_NAME = rf"{_WORD}(?:\s+(?:{_LINK}\s+)?{_WORD}){{1,4}}"
_QUALIF = (
    r"(?:S[oó]cio[\s\-]?Administrador[ae]?|Administrador[ae]?|S[oó]cio[\s\-]?Gerente"
    r"|Titular|Empres[aá]ri[ao](?:\s+Individual)?|S[oó]ci[ao])"
)

_OWNER_PATTERNS = (
    re.compile(rf"({_FULL_NAME})\s*[\(\[]\s*({_QUALIF})", re.UNICODE),
    re.compile(rf"({_FULL_NAME})\s*[-–—]\s*({_QUALIF})\b", re.UNICODE),
    re.compile(rf"({_FULL_NAME})\s+como\s+(?:[oa]\s+)?({_QUALIF})\b", re.UNICODE),
    re.compile(rf"({_QUALIF})\s*[:\-–—]\s*({_FULL_NAME})", re.UNICODE),
)

# Palavras que denunciam que o trecho casado e razao social ou rotulo de pagina,
# nao nome de pessoa.
_NOT_A_PERSON = {
    "ltda", "me", "epp", "eireli", "sa", "s/a", "cnpj", "cpf", "comercio", "comércio",
    "industria", "indústria", "empresa", "empresas", "consulta", "situacao", "situação",
    "cadastral", "razao", "razão", "social", "quadro", "societario", "societário",
    "endereco", "endereço", "telefone", "email", "e-mail", "atividade", "capital",
    "matriz", "filial", "socios", "sócios", "socio", "sócio", "administrador",
    "atualizado", "receita", "federal", "simples", "nacional", "porte", "natureza",
}


def _qualif_rank(qualif: str) -> float:
    low = qualif.lower()
    if "administrador" in low or "gerente" in low:
        return 0.62
    if "titular" in low or "empres" in low:
        return 0.58
    return 0.5


def _looks_like_person(name: str) -> bool:
    words = name.split()
    if not 2 <= len(words) <= 6:
        return False
    return not any(w.lower().strip(".,") in _NOT_A_PERSON for w in words)


def owners_from_results(results: list[dict]) -> list[tuple[str, float, str]]:
    """Extrai (nome, confianca, url) do quadro societario citado nos snippets.

    So confia em diretorio de CNPJ: em site qualquer, "Fulano - Administrador"
    pode ser qualquer pessoa citada na pagina.
    """
    from leadhunter.normalize import slug_name

    best: dict[str, tuple[str, float, str]] = {}
    for res in results:
        host = root_domain(res.get("url", ""))
        if not any(host == d or host.endswith("." + d) for d in CNPJ_DIRECTORIES):
            continue
        blob = f"{res.get('title', '')}. {res.get('snippet', '')}"
        for pattern in _OWNER_PATTERNS:
            for match in pattern.finditer(blob):
                first, second = match.group(1), match.group(2)
                name, qualif = (second, first) if re.fullmatch(_QUALIF, first) else (first, second)
                name = re.sub(r"\s+", " ", name).strip(" -:")
                if not _looks_like_person(name):
                    continue
                conf = _qualif_rank(qualif)
                key = slug_name(name)
                if key not in best or conf > best[key][1]:
                    best[key] = (name.title(), conf, res.get("url", ""))
    return sorted(best.values(), key=lambda item: -item[1])
