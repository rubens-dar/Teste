import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leadhunter.normalize import (  # noqa: E402
    clean_email, find_cnpjs, find_emails, find_instagram, find_phones,
    find_whatsapp_links, normalize_phone, owner_from_company_name, pretty_phone,
    slug_name, valid_cnpj,
)
from leadhunter.sources.mercadolivre import parse_profile_url  # noqa: E402


def test_valid_cnpj():
    assert valid_cnpj("03.361.252/0001-34")
    assert valid_cnpj("47960950000121")
    assert not valid_cnpj("03361252000135")
    assert not valid_cnpj("11111111111111")
    assert not valid_cnpj("123")


def test_find_cnpjs_ignora_numeros_invalidos():
    text = "CNPJ 03.361.252/0001-34 e o falso 11.111.111/1111-11 e CEP 88701-000"
    assert find_cnpjs(text) == ["03361252000134"]


def test_normalize_phone_celular_e_fixo():
    assert normalize_phone("(48) 99912-3456") == ("+5548999123456", "movel")
    assert normalize_phone("+55 48 3622-1234") == ("+554836221234", "fixo")
    assert normalize_phone("99912-3456", default_ddd="48") == ("+5548999123456", "movel")
    assert normalize_phone("0800 123 4567") is None
    assert normalize_phone("(99) 11111-1111") is None
    assert normalize_phone("12345") is None


def test_normalize_phone_rejeita_ddd_inexistente():
    assert normalize_phone("(20) 3622-1234") is None


def test_pretty_phone():
    assert pretty_phone("+5548999123456") == "(48) 99912-3456"
    assert pretty_phone("+554836221234") == "(48) 3622-1234"


def test_find_phones_ignora_cnpj_e_cep():
    text = "CNPJ 03.361.252/0001-34 - CEP 88701-000 - Fone (48) 3622-1234"
    assert find_phones(text) == [("+554836221234", "fixo")]


def test_find_whatsapp_links():
    html = '<a href="https://wa.me/5548999123456">Zap</a> ' \
           '<a href="https://api.whatsapp.com/send?phone=554836221234&text=oi">.</a>'
    assert find_whatsapp_links(html) == ["+5548999123456", "+554836221234"]


def test_clean_email_filtra_lixo():
    assert clean_email("Contato@Loja.com.BR ") == "contato@loja.com.br"
    assert clean_email("noreply@loja.com.br") is None
    assert clean_email("a@sentry.io") is None
    assert clean_email("logo@2x.png") is None


def test_find_emails():
    assert find_emails("fale com vendas@loja.com.br ou noreply@loja.com.br") \
        == ["vendas@loja.com.br"]


def test_find_instagram_ignora_posts():
    html = '<a href="https://instagram.com/lojatubarao">i</a>' \
           '<a href="https://www.instagram.com/p/Cabc123/">post</a>'
    assert find_instagram(html) == ["lojatubarao"]


def test_owner_from_company_name():
    assert owner_from_company_name("JOAO CARLOS DA SILVA 12345678901") == "Joao Carlos Da Silva"
    assert owner_from_company_name("LOJA DO JOAO LTDA") is None


def test_slug_name_remove_sufixo_legal():
    assert slug_name("Comércio de Peças Tubarão LTDA ME") == "comercio de pecas tubarao"
    assert slug_name("AUTO PECAS SUL EIRELI") == "auto pecas sul"


def test_parse_profile_url():
    assert parse_profile_url("https://www.mercadolivre.com.br/perfil/LOJATUBARAO") == \
        {"nickname": "LOJATUBARAO", "seller_id": ""}
    assert parse_profile_url("https://lista.mercadolivre.com.br/_CustId_123456789") == \
        {"nickname": "", "seller_id": "123456789"}
    assert parse_profile_url("https://loja.mercadolivre.com.br/minha-loja")["nickname"] == "minha-loja"
    assert parse_profile_url("")["nickname"] == ""
