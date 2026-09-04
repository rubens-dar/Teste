from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from leadhunter.http import fetch, fetch_json
from leadhunter.models import (
    ADDRESS, CNPJ, Evidence, FANTASIA, Lead, RAZAO,
)
from leadhunter.normalize import find_cnpjs, valid_cnpj

SRC = "mercadolivre"
API = "https://api.mercadolibre.com"

# A razao social aparece ora no JSON embutido da pagina, ora no bloco legal em HTML.
RAZAO_PATTERNS = [
    re.compile(r'"(?:business_name|legal_name|corporate_name|razao_social)"\s*:\s*"([^"]{4,120})"', re.I),
    re.compile(r"Raz[aã]o\s*social[^A-Za-z0-9]{0,20}([A-ZÀ-Ú0-9][^<>\n\r|]{3,110})", re.I),
    re.compile(r"Denomina[cç][aã]o\s*social[^A-Za-z0-9]{0,20}([A-ZÀ-Ú0-9][^<>\n\r|]{3,110})", re.I),
]


def _clean_razao(raw: str) -> str:
    txt = unquote(raw or "").replace("\\u0026", "&").replace("&amp;", "&")
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip(" : -")
    if len(txt) < 4 or len(txt) > 120:
        return ""
    if txt.lower().startswith(("informa", "dados", "vendedor", "cnpj")):
        return ""
    return txt


def parse_profile_url(url: str) -> dict:
    """Extrai nickname ou seller_id de qualquer formato de link do Mercado Livre."""
    out = {"nickname": "", "seller_id": ""}
    if not url:
        return out
    parts = urlsplit(url.strip())
    path = unquote(parts.path or "")

    cust = re.search(r"_CustId_(\d+)", url)
    if cust:
        out["seller_id"] = cust.group(1)
        return out
    seller = re.search(r"[?&]seller_id=(\d+)", url)
    if seller:
        out["seller_id"] = seller.group(1)
        return out

    match = re.search(r"/(?:perfil|pagina)/([^/?#]+)", path)
    if match:
        out["nickname"] = match.group(1).strip()
        return out
    if parts.netloc.startswith("loja.") or parts.netloc.startswith("tienda."):
        slug = path.strip("/").split("/")[0]
        if slug:
            out["nickname"] = slug
    return out


def resolve_seller(lead: Lead) -> dict | None:
    """Descobre o seller_id a partir do link ou do nome e devolve o usuario da API."""
    parsed = parse_profile_url(lead.perfil_url)
    seller_id = lead.seller_id or parsed["seller_id"]
    nickname = parsed["nickname"] or lead.nickname

    if not seller_id and nickname:
        data = fetch_json(f"{API}/sites/MLB/search", params={"nickname": nickname, "limit": 1})
        if data and data.get("seller"):
            seller_id = str(data["seller"].get("id") or "")
    if not seller_id and lead.nome_ml:
        data = fetch_json(f"{API}/sites/MLB/search", params={"nickname": lead.nome_ml, "limit": 1})
        if data and data.get("seller"):
            seller_id = str(data["seller"].get("id") or "")
    if not seller_id:
        return None

    user = fetch_json(f"{API}/users/{seller_id}")
    if not user or user.get("error"):
        return {"id": seller_id}
    return user


def seller_item_urls(seller_id: str, limit: int = 3) -> list[str]:
    data = fetch_json(
        f"{API}/sites/MLB/search", params={"seller_id": seller_id, "limit": limit}
    )
    if not data:
        return []
    return [it["permalink"] for it in data.get("results", []) if it.get("permalink")]


def _legal_from_html(html: str, url: str) -> list[Evidence]:
    out: list[Evidence] = []
    for cnpj in find_cnpjs(html):
        # 03.361.252/0001-34 e o CNPJ do proprio Mercado Livre, presente no rodape.
        if cnpj == "03361252000134":
            continue
        out.append(Evidence(CNPJ, cnpj, SRC, 0.95, url, "bloco legal do anuncio/perfil"))
    for pattern in RAZAO_PATTERNS:
        for match in pattern.finditer(html):
            razao = _clean_razao(match.group(1))
            if razao and "mercadolivre" not in razao.lower().replace(" ", ""):
                out.append(Evidence(RAZAO, razao, SRC, 0.9, url))
                break
        if any(e.kind == RAZAO for e in out):
            break
    return out


def enrich(lead: Lead) -> tuple[list[Evidence], list[str]]:
    evidences: list[Evidence] = []
    errors: list[str] = []

    user = resolve_seller(lead)
    if not user:
        errors.append("vendedor nao localizado na API do Mercado Livre")
        return evidences, errors

    lead.seller_id = str(user.get("id") or lead.seller_id)
    if user.get("nickname"):
        lead.nickname = user["nickname"]
        evidences.append(Evidence(FANTASIA, user["nickname"], SRC, 0.5, "", "nickname ML"))
    if not lead.perfil_url and user.get("permalink"):
        lead.perfil_url = user["permalink"]

    address = user.get("address") or {}
    if address.get("city"):
        lead.cidade = address["city"]
        uf = address.get("state") or ""
        evidences.append(
            Evidence(ADDRESS, f"{address['city']}/{uf}".strip("/"), SRC, 0.4, "", "endereco ML")
        )

    pages: list[str] = []
    if lead.perfil_url:
        pages.append(lead.perfil_url)
    if lead.nickname:
        pages.append(f"https://www.mercadolivre.com.br/perfil/{lead.nickname}")
    pages.extend(seller_item_urls(lead.seller_id))

    seen: set[str] = set()
    for url in pages:
        if url in seen:
            continue
        seen.add(url)
        status, html = fetch(url)
        if status != 200 or not html:
            continue
        found = _legal_from_html(html, url)
        evidences.extend(found)
        if any(e.kind == CNPJ for e in found):
            break

    if not any(e.kind == CNPJ for e in evidences):
        errors.append("CNPJ nao exposto nas paginas do Mercado Livre")
    return evidences, errors


def cnpj_from_evidences(evidences: list[Evidence]) -> str:
    for ev in evidences:
        if ev.kind == CNPJ and valid_cnpj(ev.value):
            return ev.value
    return ""
