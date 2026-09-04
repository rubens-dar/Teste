from __future__ import annotations

import re
import sqlite3

from leadhunter.config import CONFIG
from leadhunter.http import fetch_json
from leadhunter.models import (
    ADDRESS, CNPJ, EMAIL, Evidence, FANTASIA, OWNER, PHONE, RAZAO,
)
from leadhunter.normalize import (
    digits, is_personal_email, normalize_phone, owner_from_company_name, slug_name,
    valid_cnpj,
)

SRC = "receita_federal"

# Qualificacoes do QSA que indicam quem realmente comanda a empresa.
QUALIF_PRIORITY = (
    "administrador", "socio-administrador", "socio administrador",
    "titular", "presidente", "diretor", "socio", "acionista",
)


def _rank_qualif(qualif: str) -> int:
    txt = (qualif or "").lower()
    for i, term in enumerate(QUALIF_PRIORITY):
        if term in txt:
            return i
    return len(QUALIF_PRIORITY)


def _from_brasilapi(payload: dict) -> dict:
    phones = []
    for key in ("ddd_telefone_1", "ddd_telefone_2"):
        if payload.get(key):
            phones.append(str(payload[key]))
    socios = [
        {"nome": s.get("nome_socio") or s.get("nome") or "",
         "qualificacao": s.get("qualificacao_socio") or ""}
        for s in payload.get("qsa") or []
    ]
    endereco = " ".join(str(payload.get(k) or "") for k in
                        ("descricao_tipo_de_logradouro", "logradouro", "numero", "bairro"))
    return {
        "cnpj": digits(str(payload.get("cnpj") or "")),
        "razao_social": payload.get("razao_social") or "",
        "nome_fantasia": payload.get("nome_fantasia") or "",
        "situacao": payload.get("descricao_situacao_cadastral") or "",
        "cnae": payload.get("cnae_fiscal_descricao") or "",
        "natureza_juridica": str(payload.get("natureza_juridica") or ""),
        "telefones": phones,
        "email": payload.get("email") or "",
        "socios": socios,
        "endereco": re.sub(r"\s+", " ", endereco).strip(),
        "municipio": payload.get("municipio") or "",
        "uf": payload.get("uf") or "",
    }


def _from_cnpjws(payload: dict) -> dict:
    est = payload.get("estabelecimento") or {}
    phones = []
    for ddd_key, tel_key in (("ddd1", "telefone1"), ("ddd2", "telefone2")):
        if est.get(tel_key):
            phones.append(f"{est.get(ddd_key) or ''}{est[tel_key]}")
    socios = [
        {"nome": s.get("nome") or "",
         "qualificacao": (s.get("qualificacao_socio") or {}).get("descricao", "")}
        for s in payload.get("socios") or []
    ]
    cidade = (est.get("cidade") or {}).get("nome", "")
    endereco = " ".join(str(est.get(k) or "") for k in
                        ("tipo_logradouro", "logradouro", "numero", "bairro"))
    return {
        "cnpj": digits(str(est.get("cnpj") or payload.get("cnpj") or "")),
        "razao_social": payload.get("razao_social") or "",
        "nome_fantasia": est.get("nome_fantasia") or "",
        "situacao": est.get("situacao_cadastral") or "",
        "cnae": (est.get("atividade_principal") or {}).get("descricao", ""),
        "natureza_juridica": (payload.get("natureza_juridica") or {}).get("descricao", ""),
        "telefones": phones,
        "email": est.get("email") or "",
        "socios": socios,
        "endereco": re.sub(r"\s+", " ", endereco).strip(),
        "municipio": cidade,
        "uf": (est.get("estado") or {}).get("sigla", ""),
    }


def lookup_cnpj(cnpj: str) -> dict | None:
    """Consulta o cadastro da Receita com fallback entre provedores."""
    num = digits(cnpj)
    if not valid_cnpj(num):
        return None

    payload = fetch_json(f"https://brasilapi.com.br/api/cnpj/v1/{num}")
    if payload and payload.get("razao_social"):
        return _from_brasilapi(payload)

    payload = fetch_json(f"https://minhareceita.org/{num}")
    if payload and payload.get("razao_social"):
        return _from_brasilapi(payload)

    headers = {"x_api_token": CONFIG.cnpjws_token} if CONFIG.cnpjws_token else None
    base = "https://comercial.cnpj.ws/cnpj" if CONFIG.cnpjws_token else "https://publica.cnpj.ws/cnpj"
    payload = fetch_json(f"{base}/{num}", headers=headers)
    if payload and payload.get("razao_social"):
        return _from_cnpjws(payload)
    return None


def to_evidences(data: dict) -> list[Evidence]:
    out: list[Evidence] = []
    url = f"https://brasilapi.com.br/api/cnpj/v1/{data['cnpj']}"

    if data.get("cnpj"):
        out.append(Evidence(CNPJ, data["cnpj"], SRC, 1.0, url))
    if data.get("razao_social"):
        out.append(Evidence(RAZAO, data["razao_social"], SRC, 1.0, url))
    if data.get("nome_fantasia"):
        out.append(Evidence(FANTASIA, data["nome_fantasia"], SRC, 0.95, url))
    if data.get("endereco"):
        endereco = f"{data['endereco']} - {data.get('municipio', '')}/{data.get('uf', '')}"
        out.append(Evidence(ADDRESS, endereco.strip(" -/"), SRC, 0.9, url))

    socios = sorted(data.get("socios") or [], key=lambda s: _rank_qualif(s.get("qualificacao", "")))
    for i, socio in enumerate(socios):
        nome = re.sub(r"\s+", " ", (socio.get("nome") or "")).strip()
        if len(nome.split()) < 2:
            continue
        out.append(Evidence(
            OWNER, nome.title(), SRC, 1.0 if i == 0 else 0.8, url,
            socio.get("qualificacao", ""), personal=True,
        ))

    if not socios:
        # MEI e empresario individual nao tem QSA: o dono esta na propria razao social.
        dono = owner_from_company_name(data.get("razao_social", ""))
        if dono:
            out.append(Evidence(
                OWNER, dono, SRC, 0.95, url, "MEI/empresario individual", personal=True,
            ))

    for raw in data.get("telefones") or []:
        parsed = normalize_phone(raw, CONFIG.default_ddd)
        if not parsed:
            continue
        number, kind = parsed
        # O telefone declarado na Receita costuma ser o do proprio dono.
        out.append(Evidence(PHONE, number, SRC, 0.9, url, f"telefone cadastral ({kind})"))

    email = (data.get("email") or "").strip().lower()
    if email and "@" in email:
        out.append(Evidence(
            EMAIL, email, SRC, 0.9, url, "e-mail cadastral",
            personal=is_personal_email(email),
        ))
    return out


def search_local_db(nome: str, cidade: str = "", uf: str = "") -> list[dict]:
    """Busca por nome na base local da Receita, quando ela foi construida."""
    db = CONFIG.receita_db
    if not db.exists():
        return []
    slug = slug_name(nome)
    if len(slug) < 4:
        return []
    tokens = [t for t in slug.split() if len(t) > 2][:4]
    if not tokens:
        return []

    where = " AND ".join(["(slug_razao LIKE ? OR slug_fantasia LIKE ?)"] * len(tokens))
    params: list[str] = []
    for token in tokens:
        params.extend([f"%{token}%", f"%{token}%"])
    sql = f"SELECT cnpj, razao_social, nome_fantasia, municipio, uf FROM empresas WHERE {where} LIMIT 40"

    with sqlite3.connect(db) as conn:
        rows = conn.execute(sql, params).fetchall()

    from rapidfuzz import fuzz

    scored = []
    for cnpj, razao, fantasia, municipio, estado in rows:
        best = max(
            fuzz.token_set_ratio(slug, slug_name(razao or "")),
            fuzz.token_set_ratio(slug, slug_name(fantasia or "")),
        )
        if uf and estado and uf.upper() != estado.upper():
            best -= 25
        scored.append({
            "cnpj": cnpj, "razao_social": razao, "nome_fantasia": fantasia,
            "municipio": municipio, "uf": estado, "match": best,
        })
    scored.sort(key=lambda r: -r["match"])
    return [r for r in scored if r["match"] >= 80][:3]
