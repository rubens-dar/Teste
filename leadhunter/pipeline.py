from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from rapidfuzz import fuzz

from leadhunter.config import CONFIG
from leadhunter.models import (
    CNPJ, Evidence, FANTASIA, Lead, OWNER, PHONE, RAZAO, Result, WEBSITE, WHATSAPP,
)
from leadhunter.normalize import digits, slug_name
from leadhunter.scoring import score
from leadhunter.sources import gmaps, mercadolivre, receita, social, website
from leadhunter.sources.search import cnpj_candidates_from_results, official_sites, search

log = logging.getLogger("leadhunter")

NAME_MATCH_STRICT = 82
NAME_MATCH_LOOSE = 68


def _is_mobile(e164: str) -> bool:
    num = digits(e164)
    return len(num) == 13 and num.startswith("55") and num[4] == "9"


def _name_similarity(a: str, b: str) -> int:
    sa, sb = slug_name(a), slug_name(b)
    if not sa or not sb:
        return 0
    return max(fuzz.token_set_ratio(sa, sb), fuzz.partial_ratio(sa, sb))


def _confirm_cnpj(candidate: str, lead: Lead, aliases: list[str]) -> tuple[dict, float] | None:
    """So aceita um CNPJ achado por nome se cidade e nome baterem com o cadastro."""
    data = receita.lookup_cnpj(candidate)
    if not data:
        return None

    cidade_ok = True
    if lead.cidade and data.get("municipio"):
        cidade_ok = slug_name(lead.cidade)[:6] in slug_name(data["municipio"])
    if lead.uf and data.get("uf") and lead.uf.upper() != data["uf"].upper():
        cidade_ok = False
    if not cidade_ok:
        return None

    best = max(
        (max(_name_similarity(alias, data.get("razao_social", "")),
             _name_similarity(alias, data.get("nome_fantasia", "")))
         for alias in aliases if alias),
        default=0,
    )
    if best >= NAME_MATCH_STRICT:
        return data, 0.9
    if best >= NAME_MATCH_LOOSE:
        return data, 0.65
    return None


def _resolve_cnpj_by_name(lead: Lead, aliases: list[str], res: Result) -> dict | None:
    for hit in receita.search_local_db(aliases[0], lead.cidade, lead.uf):
        confirmed = _confirm_cnpj(hit["cnpj"], lead, aliases)
        if confirmed:
            data, conf = confirmed
            res.add(Evidence(CNPJ, data["cnpj"], "base_local_receita", conf, "",
                             f"match {hit['match']}% por nome"))
            return data

    queries = [
        f'"{aliases[0]}" {lead.cidade} {lead.uf} CNPJ',
        f'{aliases[0]} {lead.cidade} CNPJ',
    ]
    seen: list[str] = []
    for query in queries:
        results = search(query, limit=10)
        for candidate in cnpj_candidates_from_results(results):
            if candidate in seen:
                continue
            seen.append(candidate)
            confirmed = _confirm_cnpj(candidate, lead, aliases)
            if confirmed:
                data, conf = confirmed
                res.add(Evidence(CNPJ, data["cnpj"], "busca_diretorios", conf, "",
                                 f"encontrado via busca: {query}"))
                return data
        if seen and len(seen) > 8:
            break
    return None


def process(lead: Lead) -> Result:
    res = Result(lead=lead)

    ml_evidences, ml_errors = mercadolivre.enrich(lead)
    res.extend(ml_evidences)
    res.errors.extend(ml_errors)

    aliases = [a for a in (lead.nome_ml, lead.nickname, res.first(RAZAO), res.first(FANTASIA)) if a]
    if not aliases:
        res.errors.append("lead sem nome utilizavel")
        score(res)
        return res

    cnpj = res.first(CNPJ)
    data = None
    if cnpj:
        data = receita.lookup_cnpj(cnpj)
        if not data:
            res.errors.append(f"CNPJ {cnpj} nao retornou dados na Receita")
    if not data:
        data = _resolve_cnpj_by_name(lead, aliases, res)
    if data:
        res.extend(receita.to_evidences(data))
    else:
        res.errors.append("CNPJ nao identificado")

    empresa = res.first(RAZAO) or res.first(FANTASIA) or aliases[0]
    owner = res.first(OWNER)

    try:
        res.extend(gmaps.enrich(res.first(FANTASIA) or empresa, lead.cidade, lead.uf))
    except Exception as exc:
        res.errors.append(f"google maps: {exc}")

    sites = [e.value for e in res.of(WEBSITE)]
    try:
        results = search(f'"{empresa}" {lead.cidade} {lead.uf}', limit=10)
        for site in official_sites(results):
            if site not in sites:
                sites.append(site)
    except Exception as exc:
        res.errors.append(f"busca de site: {exc}")

    for site in sites[:2]:
        try:
            res.extend(website.enrich(site))
        except Exception as exc:
            res.errors.append(f"site {site}: {exc}")

    try:
        res.extend(social.find_social(empresa, lead.cidade, owner))
    except Exception as exc:
        res.errors.append(f"redes sociais: {exc}")

    # Celular brasileiro e, na pratica, WhatsApp: promove todo movel a candidato.
    known = {e.value for e in res.of(WHATSAPP)}
    for ev in res.of(PHONE):
        if _is_mobile(ev.value) and ev.value not in known:
            res.add(Evidence(WHATSAPP, ev.value, ev.source, max(ev.confidence - 0.15, 0.3),
                             ev.url, f"celular ({ev.note})" if ev.note else "celular"))

    score(res)
    return res


def run(leads: list[Lead], workers: int | None = None) -> list[Result]:
    workers = workers or CONFIG.workers
    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process, lead): lead for lead in leads}
        for done in as_completed(futures):
            lead = futures[done]
            try:
                res = done.result()
            except Exception as exc:
                log.exception("falha no lead %s", lead.label())
                res = Result(lead=lead, errors=[f"erro inesperado: {exc}"])
                score(res)
            results.append(res)
            log.info("[%s] %s -> tier %s (score %.0f)",
                     lead.row, lead.label()[:40], res.tier, res.score)
    results.sort(key=lambda r: r.lead.row)
    return results
