from __future__ import annotations

import re
import unicodedata

DDDS = {
    "11", "12", "13", "14", "15", "16", "17", "18", "19",
    "21", "22", "24", "27", "28",
    "31", "32", "33", "34", "35", "37", "38",
    "41", "42", "43", "44", "45", "46", "47", "48", "49",
    "51", "53", "54", "55",
    "61", "62", "63", "64", "65", "66", "67", "68", "69",
    "71", "73", "74", "75", "77", "79",
    "81", "82", "83", "84", "85", "86", "87", "88", "89",
    "91", "92", "93", "94", "95", "96", "97", "98", "99",
}

LEGAL_SUFFIXES = [
    "ltda me", "ltda epp", "sociedade limitada", "eireli", "ltda", "me", "epp",
    "mei", "s a", "sa", "s/a", "cia", "e cia", "empresa individual",
    "unipessoal", "sociedade unipessoal", "microempreendedor individual",
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
CNPJ_RE = re.compile(r"\b\d{2}[.\s]?\d{3}[.\s]?\d{3}[/\s]?\d{4}[-\s]?\d{2}\b")
PHONE_RE = re.compile(
    r"(?:\+?55[\s.\-]?)?(?:\(?\d{2}\)?[\s.\-]?)?(?:9[\s.\-]?)?\d{4}[\s.\-]?\d{4}\b"
)
WHATSAPP_LINK_RE = re.compile(
    r"(?:wa\.me/|api\.whatsapp\.com/send\?(?:[^\"'\s]*&)?phone=|"
    r"web\.whatsapp\.com/send\?(?:[^\"'\s]*&)?phone=|whatsapp://send\?phone=)"
    r"\+?(\d{10,15})",
    re.I,
)
INSTAGRAM_RE = re.compile(
    r"instagram\.com/(?!p/|reel/|reels/|explore/|stories/|accounts/)"
    r"([A-Za-z0-9_.]{2,30})",
    re.I,
)
# "FULANO DE TAL 12345678901" -> razao social de MEI/empresario individual.
EI_NAME_RE = re.compile(r"^(.{5,}?)[\s\-]*(\d{11})$")

EMAIL_JUNK_DOMAINS = {
    "example.com", "email.com", "dominio.com", "seudominio.com.br", "sentry.io",
    "sentry-next.wixpress.com", "wixpress.com", "wix.com", "godaddy.com",
    "schema.org", "w3.org", "google.com", "googlemail.com", "facebook.com",
    "instagram.com", "mercadolivre.com.br", "mercadolibre.com", "olx.com.br",
    "shopify.com", "squarespace.com", "cloudflare.com", "jquery.com",
    "bootstrapcdn.com", "fontawesome.com", "gstatic.com", "adobe.com",
}
EMAIL_JUNK_PREFIXES = ("noreply", "no-reply", "nao-responda", "naoresponda", "postmaster",
                       "abuse", "mailer-daemon", "wordpress", "u003e", "example")
EMAIL_JUNK_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js",
                       ".woff", ".ttf", ".ico", ".webmanifest")

PERSONAL_EMAIL_DOMAINS = {
    "gmail.com", "hotmail.com", "outlook.com", "outlook.com.br", "yahoo.com",
    "yahoo.com.br", "live.com", "bol.com.br", "uol.com.br", "terra.com.br",
    "icloud.com", "msn.com", "globo.com", "ig.com.br",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def slug_name(name: str) -> str:
    """Forma canonica de um nome de empresa, para comparacao fuzzy."""
    txt = strip_accents(name or "").lower()
    txt = re.sub(r"[^a-z0-9\s]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
        txt = re.sub(rf"\b{re.escape(suffix)}\b", " ", txt)
    txt = re.sub(r"\b\d{11,14}\b", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def valid_cnpj(raw: str) -> bool:
    num = digits(raw)
    if len(num) != 14 or len(set(num)) == 1:
        return False
    for size in (12, 13):
        weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-size:]
        total = sum(int(d) * w for d, w in zip(num[:size], weights))
        check = 11 - (total % 11)
        check = 0 if check >= 10 else check
        if int(num[size]) != check:
            return False
    return True


def format_cnpj(raw: str) -> str:
    n = digits(raw)
    if len(n) != 14:
        return raw
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"


def find_cnpjs(text: str) -> list[str]:
    """CNPJs validos encontrados no texto, sem duplicatas, em ordem de aparicao."""
    out: list[str] = []
    for match in CNPJ_RE.finditer(text or ""):
        num = digits(match.group(0))
        if valid_cnpj(num) and num not in out:
            out.append(num)
    return out


def normalize_phone(raw: str, default_ddd: str = "48") -> tuple[str, str] | None:
    """Devolve (E164, tipo) onde tipo e 'movel' ou 'fixo'. None se invalido."""
    num = digits(raw)
    if not num:
        return None
    if num.startswith("0800") or num.startswith("0300"):
        return None
    num = num.lstrip("0")
    if len(num) > 11 and num.startswith("55"):
        num = num[2:]
    if len(num) in (8, 9):
        num = default_ddd + num
    if len(num) not in (10, 11):
        return None

    ddd, rest = num[:2], num[2:]
    if ddd not in DDDS:
        return None
    if len(set(rest)) <= 2:
        return None
    if rest in ("12345678", "123456789", "999999999", "000000000"):
        return None

    if len(rest) == 9:
        if rest[0] != "9":
            return None
        kind = "movel"
    else:
        if rest[0] == "9":
            # fixo nunca comeca com 9: e um celular sem o nono digito
            return None
        if rest[0] not in "2345":
            return None
        kind = "fixo"
    return f"+55{ddd}{rest}", kind


def pretty_phone(e164: str) -> str:
    n = digits(e164)
    if n.startswith("55"):
        n = n[2:]
    if len(n) == 11:
        return f"({n[:2]}) {n[2:7]}-{n[7:]}"
    if len(n) == 10:
        return f"({n[:2]}) {n[2:6]}-{n[6:]}"
    return e164


def find_phones(text: str, default_ddd: str = "48") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    cleaned = CNPJ_RE.sub(" ", text or "")
    cleaned = re.sub(r"\b\d{5}[-\s]?\d{3}\b", " ", cleaned)  # CEP
    for match in PHONE_RE.finditer(cleaned):
        parsed = normalize_phone(match.group(0), default_ddd)
        if parsed and parsed[0] not in seen:
            seen.add(parsed[0])
            out.append(parsed)
    return out


def find_whatsapp_links(html: str) -> list[str]:
    out: list[str] = []
    for match in WHATSAPP_LINK_RE.finditer(html or ""):
        parsed = normalize_phone(match.group(1))
        if parsed and parsed[0] not in out:
            out.append(parsed[0])
    return out


def clean_email(candidate: str) -> str | None:
    email = (candidate or "").strip().strip(".,;:<>()[]\"'").lower()
    if not EMAIL_RE.fullmatch(email):
        return None
    if email.endswith(EMAIL_JUNK_SUFFIXES):
        return None
    local, _, domain = email.partition("@")
    if domain in EMAIL_JUNK_DOMAINS or any(domain.endswith("." + d) for d in EMAIL_JUNK_DOMAINS):
        return None
    if local.startswith(EMAIL_JUNK_PREFIXES):
        return None
    if len(local) > 64 or re.fullmatch(r"[0-9a-f]{16,}", local):
        return None
    return email


def find_emails(text: str) -> list[str]:
    out: list[str] = []
    for match in EMAIL_RE.finditer(text or ""):
        email = clean_email(match.group(0))
        if email and email not in out:
            out.append(email)
    return out


def find_instagram(html: str) -> list[str]:
    blocked = {"mercadolivre", "mercadolibre", "instagram", "meta", "facebook"}
    out: list[str] = []
    for match in INSTAGRAM_RE.finditer(html or ""):
        handle = match.group(1).strip(".").lower()
        if handle in blocked or len(handle) < 3 or handle in out:
            continue
        out.append(handle)
    return out


def owner_from_company_name(razao_social: str) -> str | None:
    """MEI/empresario individual: a razao social e o nome do dono + CPF."""
    txt = (razao_social or "").strip()
    match = EI_NAME_RE.match(txt)
    if not match:
        return None
    name = re.sub(r"\s+", " ", match.group(1)).strip(" -")
    if len(name.split()) < 2:
        return None
    return name.title()


def is_personal_email(email: str) -> bool:
    return email.split("@")[-1] in PERSONAL_EMAIL_DOMAINS
