"""Monta uma base SQLite local com todas as empresas de um municipio.

Usa os dados abertos do CNPJ da Receita Federal. E um download pesado (varios GB),
feito uma unica vez: depois disso a resolucao nome -> CNPJ fica offline, instantanea
e muito mais precisa do que depender de buscador.

    python scripts/build_receita_local.py --municipio Tubarao --uf SC
"""
from __future__ import annotations

import argparse
import csv
import io
import sqlite3
import sys
import zipfile
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leadhunter.config import CONFIG  # noqa: E402
from leadhunter.normalize import slug_name, strip_accents  # noqa: E402

BASE = "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj"
CHUNK = 1 << 20
csv.field_size_limit(1 << 24)


def latest_release() -> str:
    today = date.today()
    for back in range(0, 8):
        year, month = divmod(today.year * 12 + today.month - 1 - back, 12)
        tag = f"{year}-{month + 1:02d}"
        resp = requests.head(f"{BASE}/{tag}/Municipios.zip", timeout=30, allow_redirects=True)
        if resp.status_code == 200:
            return tag
    raise SystemExit("Nao encontrei uma publicacao recente dos dados abertos do CNPJ.")


def download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  (cache) {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(CHUNK):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    pct = 100 * done / total
                    print(f"\r  {dest.name}: {pct:5.1f}%", end="", flush=True)
    print()
    tmp.rename(dest)
    return dest


def rows_of(zip_path: Path):
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            with zf.open(name) as raw:
                stream = io.TextIOWrapper(raw, encoding="latin-1", errors="replace")
                yield from csv.reader(stream, delimiter=";", quotechar='"')


def municipio_code(tag: str, cache: Path, municipio: str) -> str:
    path = download(f"{BASE}/{tag}/Municipios.zip", cache / "Municipios.zip")
    target = strip_accents(municipio).upper().strip()
    for row in rows_of(path):
        if len(row) >= 2 and strip_accents(row[1]).upper().strip() == target:
            return row[0]
    raise SystemExit(f"Municipio '{municipio}' nao encontrado na tabela da Receita.")


def build(municipio: str, uf: str, cache: Path, db_path: Path) -> None:
    tag = latest_release()
    print(f"Publicacao: {tag}")
    code = municipio_code(tag, cache, municipio)
    print(f"Codigo do municipio {municipio}/{uf}: {code}")

    estabelecimentos: dict[str, dict] = {}
    print("\nEstabelecimentos (filtrando pelo municipio)")
    for i in range(10):
        path = download(f"{BASE}/{tag}/Estabelecimentos{i}.zip", cache / f"Estabelecimentos{i}.zip")
        for row in rows_of(path):
            if len(row) < 28 or row[20] != code or (uf and row[19] != uf.upper()):
                continue
            cnpj = f"{row[0]}{row[1]}{row[2]}"
            estabelecimentos[row[0]] = estabelecimentos.get(row[0]) or {}
            estabelecimentos[row[0]][cnpj] = {
                "cnpj": cnpj,
                "matriz": row[3] == "1",
                "nome_fantasia": row[4].strip(),
                "situacao": row[5],
                "telefone1": f"{row[21]}{row[22]}".strip(),
                "telefone2": f"{row[23]}{row[24]}".strip(),
                "email": row[27].strip().lower(),
                "municipio": municipio,
                "uf": row[19],
            }
        print(f"  acumulado: {sum(len(v) for v in estabelecimentos.values())} estabelecimentos")

    basicos = set(estabelecimentos)
    if not basicos:
        raise SystemExit("Nenhum estabelecimento encontrado. Confira o nome do municipio.")

    razoes: dict[str, str] = {}
    print("\nEmpresas (razao social)")
    for i in range(10):
        path = download(f"{BASE}/{tag}/Empresas{i}.zip", cache / f"Empresas{i}.zip")
        for row in rows_of(path):
            if len(row) >= 2 and row[0] in basicos:
                razoes[row[0]] = row[1].strip()
        print(f"  acumulado: {len(razoes)} razoes sociais")

    socios: list[tuple] = []
    print("\nSocios")
    for i in range(10):
        path = download(f"{BASE}/{tag}/Socios{i}.zip", cache / f"Socios{i}.zip")
        for row in rows_of(path):
            if len(row) >= 5 and row[0] in basicos:
                socios.append((row[0], row[2].strip(), row[4]))
        print(f"  acumulado: {len(socios)} socios")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE empresas (cnpj TEXT PRIMARY KEY, cnpj_basico TEXT, razao_social TEXT,"
            " nome_fantasia TEXT, slug_razao TEXT, slug_fantasia TEXT, situacao TEXT,"
            " telefone1 TEXT, telefone2 TEXT, email TEXT, municipio TEXT, uf TEXT)"
        )
        conn.execute(
            "CREATE TABLE socios (cnpj_basico TEXT, nome TEXT, qualificacao TEXT)"
        )
        payload = []
        for basico, unidades in estabelecimentos.items():
            razao = razoes.get(basico, "")
            for cnpj, est in unidades.items():
                payload.append((
                    cnpj, basico, razao, est["nome_fantasia"],
                    slug_name(razao), slug_name(est["nome_fantasia"]),
                    est["situacao"], est["telefone1"], est["telefone2"], est["email"],
                    est["municipio"], est["uf"],
                ))
        conn.executemany("INSERT OR REPLACE INTO empresas VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", payload)
        conn.executemany("INSERT INTO socios VALUES (?,?,?)", socios)
        conn.execute("CREATE INDEX idx_razao ON empresas(slug_razao)")
        conn.execute("CREATE INDEX idx_fantasia ON empresas(slug_fantasia)")
        conn.execute("CREATE INDEX idx_socios ON socios(cnpj_basico)")

    print(f"\nBase pronta: {db_path} ({len(payload)} empresas, {len(socios)} socios)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--municipio", default=CONFIG.cidade)
    parser.add_argument("--uf", default=CONFIG.uf)
    parser.add_argument("--cache", default="data/receita/zips")
    parser.add_argument("--db", default=str(CONFIG.receita_db))
    args = parser.parse_args()
    build(args.municipio, args.uf, Path(args.cache), Path(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
