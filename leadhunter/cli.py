from __future__ import annotations

import argparse
import logging
from pathlib import Path

from leadhunter.config import CONFIG
from leadhunter.leads_io import load_leads, write_outputs
from leadhunter.models import CNPJ, EMAIL, OWNER, PHONE, WHATSAPP


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _summary(results) -> str:
    total = len(results) or 1
    tiers = {t: sum(1 for r in results if r.tier == t) for t in "ABCD"}

    def pct(n: int) -> str:
        return f"{n}/{len(results)} ({100 * n / total:.0f}%)"

    lines = [
        "",
        "=" * 62,
        "RESULTADO",
        "=" * 62,
        f"  CNPJ identificado .......... {pct(sum(1 for r in results if r.of(CNPJ)))}",
        f"  Proprietario identificado .. {pct(sum(1 for r in results if r.of(OWNER)))}",
        f"  WhatsApp ................... {pct(sum(1 for r in results if r.of(WHATSAPP)))}",
        f"  Telefone ................... {pct(sum(1 for r in results if r.of(PHONE)))}",
        f"  E-mail ..................... {pct(sum(1 for r in results if r.of(EMAIL)))}",
        f"  Algum contato .............. "
        f"{pct(sum(1 for r in results if r.of(WHATSAPP) or r.of(PHONE) or r.of(EMAIL)))}",
        "",
        f"  A (dono + WhatsApp) ........ {tiers['A']}",
        f"  B (dono + contato) ......... {tiers['B']}",
        f"  C (so contato da empresa) .. {tiers['C']}",
        f"  D (nada encontrado) ........ {tiers['D']}",
        "=" * 62,
    ]
    return "\n".join(lines)


def cmd_enrich(args) -> int:
    from leadhunter import pipeline

    leads = load_leads(args.input)
    if args.limit:
        leads = leads[: args.limit]
    logging.info("%d leads carregados | buscador: %s | Google Maps: %s",
                 len(leads), CONFIG.search_provider,
                 "sim" if CONFIG.google_maps_key else "nao")

    results = pipeline.run(leads, workers=args.workers)
    paths = write_outputs(results, Path(args.outdir))

    print(_summary(results))
    for label, path in paths.items():
        print(f"  {label:8} -> {path}")
    return 0


def cmd_cnpj(args) -> int:
    import json

    from leadhunter.sources import receita

    data = receita.lookup_cnpj(args.cnpj)
    if not data:
        print("CNPJ nao encontrado ou invalido")
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args) -> int:
    from leadhunter.http import fetch
    from leadhunter.sources.search import search

    print("Configuracao")
    print(f"  buscador ....... {CONFIG.search_provider}")
    print(f"  google maps .... {'configurado' if CONFIG.google_maps_key else 'ausente (opcional)'}")
    print(f"  base local RF .. {'sim' if CONFIG.receita_db.exists() else 'nao (opcional)'}")
    print(f"  workers ........ {CONFIG.workers} | rate limit {CONFIG.rate_limit}s/host")
    print("\nConectividade")

    checks = [
        ("API Mercado Livre", "https://api.mercadolibre.com/sites/MLB"),
        ("BrasilAPI (Receita)", "https://brasilapi.com.br/api/cnpj/v1/03361252000134"),
        ("MinhaReceita", "https://minhareceita.org/03361252000134"),
        ("Perfil Mercado Livre", "https://www.mercadolivre.com.br"),
    ]
    ok = True
    for name, url in checks:
        status, _ = fetch(url, cache_ttl=0)
        flag = "OK" if status == 200 else f"FALHOU ({status})"
        ok = ok and status == 200
        print(f"  {name:22} {flag}")

    results = search("teste tubarao sc", limit=3)
    print(f"  {'Buscador':22} {'OK' if results else 'FALHOU'} ({len(results)} resultados)")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="leadhunter",
        description="Enriquece vendedores do Mercado Livre com dono, WhatsApp, telefone e e-mail.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    enrich = sub.add_parser("enrich", help="processa uma planilha de leads")
    enrich.add_argument("input", help="CSV/XLSX local, URL de CSV ou link do Google Sheets")
    enrich.add_argument("-o", "--outdir", default="data/output")
    enrich.add_argument("-n", "--limit", type=int, default=0)
    enrich.add_argument("-w", "--workers", type=int, default=None)
    enrich.set_defaults(func=cmd_enrich)

    cnpj = sub.add_parser("cnpj", help="consulta um CNPJ na Receita")
    cnpj.add_argument("cnpj")
    cnpj.set_defaults(func=cmd_cnpj)

    doctor = sub.add_parser("doctor", help="verifica chaves e acesso as fontes")
    doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    _setup_logging(args.verbose)
    return args.func(args)
