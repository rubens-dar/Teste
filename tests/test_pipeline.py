import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leadhunter.leads_io import load_leads, write_outputs  # noqa: E402
from leadhunter.models import (  # noqa: E402
    CNPJ, EMAIL, Evidence, Lead, OWNER, PHONE, Result, WHATSAPP,
)
from leadhunter.scoring import score  # noqa: E402
from leadhunter.sources.receita import to_evidences  # noqa: E402
from leadhunter.sources.search import cnpj_candidates_from_results, official_sites  # noqa: E402

SAMPLE = """Nome do Vendedor;Link do Perfil;Cidade;UF
LOJA TESTE TUBARAO;https://www.mercadolivre.com.br/perfil/LOJATESTE;Tubarao;SC
OUTRA LOJA;https://lista.mercadolivre.com.br/_CustId_987654321;Tubarao;SC
"""


def test_load_leads_csv_ponto_e_virgula(tmp_path):
    path = tmp_path / "leads.csv"
    path.write_text(SAMPLE, encoding="utf-8")
    leads = load_leads(str(path))
    assert len(leads) == 2
    assert leads[0].nome_ml == "LOJA TESTE TUBARAO"
    assert leads[0].perfil_url.endswith("LOJATESTE")
    assert leads[0].cidade == "Tubarao"


def test_result_deduplica_e_mantem_maior_confianca():
    res = Result(lead=Lead(row=2))
    res.add(Evidence(PHONE, "+5548999123456", "site", 0.6))
    res.add(Evidence(PHONE, "+5548999123456", "receita_federal", 0.9))
    assert len(res.of(PHONE)) == 1
    assert res.of(PHONE)[0].confidence == 0.9
    assert res.of(PHONE)[0].source == "receita_federal"


def test_receita_extrai_socio_telefone_e_email():
    data = {
        "cnpj": "03361252000134",
        "razao_social": "LOJA TESTE LTDA",
        "nome_fantasia": "LOJA TESTE",
        "telefones": ["48999123456", "4836221234"],
        "email": "joao@gmail.com",
        "socios": [
            {"nome": "MARIA DE SOUZA", "qualificacao": "22-Socio Pessoa Fisica"},
            {"nome": "JOAO DA SILVA", "qualificacao": "49-Socio-Administrador"},
        ],
        "endereco": "RUA X 100 CENTRO",
        "municipio": "TUBARAO",
        "uf": "SC",
    }
    evs = to_evidences(data)
    owners = [e for e in evs if e.kind == OWNER]
    assert owners[0].value == "Joao Da Silva"  # administrador vem primeiro
    assert {e.value for e in evs if e.kind == PHONE} == {"+5548999123456", "+554836221234"}
    email = next(e for e in evs if e.kind == EMAIL)
    assert email.personal is True


def test_receita_identifica_dono_de_mei_sem_qsa():
    data = {
        "cnpj": "03361252000134", "razao_social": "PEDRO HENRIQUE ALVES 12345678901",
        "nome_fantasia": "", "telefones": [], "email": "", "socios": [],
        "endereco": "", "municipio": "TUBARAO", "uf": "SC",
    }
    owners = [e for e in to_evidences(data) if e.kind == OWNER]
    assert owners and owners[0].value == "Pedro Henrique Alves"


def test_cnpj_candidates_from_results():
    results = [
        {"url": "https://cnpj.biz/03361252000134", "title": "Loja", "snippet": ""},
        {"url": "https://exemplo.com", "title": "x", "snippet": "CNPJ 47.960.950/0001-21"},
    ]
    assert cnpj_candidates_from_results(results) == ["03361252000134", "47960950000121"]


def test_official_sites_descarta_agregadores():
    results = [
        {"url": "https://www.mercadolivre.com.br/x", "title": "", "snippet": ""},
        {"url": "https://cnpj.biz/123", "title": "", "snippet": ""},
        {"url": "https://www.lojateste.com.br/contato", "title": "", "snippet": ""},
    ]
    assert official_sites(results) == ["https://lojateste.com.br"]


def test_scoring_tiers():
    res = Result(lead=Lead(row=2))
    res.add(Evidence(OWNER, "Joao Da Silva", "receita_federal", 1.0, personal=True))
    res.add(Evidence(WHATSAPP, "+5548999123456", "site", 0.95))
    score(res)
    assert res.tier == "A"

    only_company = Result(lead=Lead(row=3))
    only_company.add(Evidence(PHONE, "+554836221234", "site", 0.8))
    score(only_company)
    assert only_company.tier == "C"

    empty = Result(lead=Lead(row=4))
    score(empty)
    assert empty.tier == "D" and empty.score == 0


def test_write_outputs(tmp_path):
    res = Result(lead=Lead(row=2, nome_ml="LOJA TESTE"))
    res.add(Evidence(CNPJ, "03361252000134", "receita_federal", 1.0))
    res.add(Evidence(OWNER, "Joao Da Silva", "receita_federal", 1.0, personal=True))
    res.add(Evidence(WHATSAPP, "+5548999123456", "site", 0.95))
    score(res)

    paths = write_outputs([res], tmp_path)
    content = paths["csv"].read_text(encoding="utf-8-sig")
    assert "03.361.252/0001-34" in content
    assert "(48) 99912-3456" in content
    assert "Joao Da Silva" in content
    assert paths["json"].exists()


def test_owners_from_results_le_quadro_societario_do_snippet():
    from leadhunter.sources.search import owners_from_results

    results = [
        {"url": "https://cnpj.biz/06071442000105", "title": "Montri Comercio de Moveis LTDA",
         "snippet": "Socios: Enedio Batista da Silva Nasario (Socio-Administrador)"
                    " e Josue Cardoso Correa (Socio)."},
        {"url": "https://www.econodata.com.br/consulta-empresa/79692968000186-corremar",
         "title": "Corremar Moveis Ltda em Tubarao, SC",
         "snippet": "tem Arlan de Oliveira Mateus como Administrador."},
        # agregador que nao e diretorio de CNPJ nao pode virar fonte de dono
        {"url": "https://www.mercadolivre.com.br/loja/x", "title": "loja",
         "snippet": "Joao Ninguem (Socio-Administrador)"},
    ]
    achados = owners_from_results(results)
    nomes = [nome for nome, _, _ in achados]
    assert nomes[:2] == ["Enedio Batista Da Silva Nasario", "Arlan De Oliveira Mateus"]
    assert "Joao Ninguem" not in nomes
    # administrador tem que valer mais que socio comum
    assert achados[0][1] > achados[-1][1]
    assert achados[-1][0] == "Josue Cardoso Correa"


def test_owners_from_results_descarta_razao_social():
    from leadhunter.sources.search import owners_from_results

    results = [{
        "url": "https://cnpj.biz/79692968000186", "title": "Corremar",
        "snippet": "Corremar Moveis Ltda - Administrador nao informado. Quadro Societario: -",
    }]
    assert owners_from_results(results) == []
