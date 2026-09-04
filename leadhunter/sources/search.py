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
}
# Agregadores que expoem CNPJ na propria URL ou no titulo.
CNPJ_DIRECTORIES = (
    "cnpj.biz", "econodata.com.br", "casadosdados.com.br", "consultasocio.com",
    "empresascnpj.com", "cnpja.com", "cnpj.info", "empresaqui.com.br", "cnpjs.rocks",
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
