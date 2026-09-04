from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from leadhunter.config import CONFIG
from leadhunter.http import fetch
from leadhunter.models import EMAIL, Evidence, INSTAGRAM, PHONE, WEBSITE, WHATSAPP
from leadhunter.normalize import (
    clean_email, find_emails, find_instagram, find_phones, find_whatsapp_links,
    is_personal_email, normalize_phone,
)

SRC = "site"
CONTACT_HINTS = re.compile(
    r"contato|contact|fale-?conosco|quem-?somos|sobre|atendimento|suporte|"
    r"institucional|empresa|onde-?estamos|localizacao",
    re.I,
)
NOISE_EXT = re.compile(r"\.(pdf|jpg|jpeg|png|gif|svg|zip|mp4|webp|css|js)(\?|$)", re.I)


def _internal_links(html: str, base: str, limit: int = 4) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    host = urlsplit(base).netloc
    found: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urljoin(base, href)
        if urlsplit(url).netloc != host or NOISE_EXT.search(url):
            continue
        text = anchor.get_text(" ", strip=True)
        if not (CONTACT_HINTS.search(url) or CONTACT_HINTS.search(text)):
            continue
        url = url.split("#")[0]
        if url not in found and url != base:
            found.append(url)
        if len(found) >= limit:
            break
    return found


def _extract(html: str, url: str) -> list[Evidence]:
    out: list[Evidence] = []
    soup = BeautifulSoup(html, "lxml")

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.lower().startswith("mailto:"):
            email = clean_email(href[7:].split("?")[0])
            if email:
                out.append(Evidence(EMAIL, email, SRC, 0.85, url, "link mailto",
                                    personal=is_personal_email(email)))
        elif href.lower().startswith("tel:"):
            parsed = normalize_phone(href[4:], CONFIG.default_ddd)
            if parsed:
                out.append(Evidence(PHONE, parsed[0], SRC, 0.85, url, f"link tel ({parsed[1]})"))

    for number in find_whatsapp_links(html):
        out.append(Evidence(WHATSAPP, number, SRC, 0.95, url, "link de WhatsApp no site"))
        out.append(Evidence(PHONE, number, SRC, 0.9, url, "link de WhatsApp no site"))

    text = soup.get_text(" ", strip=True)
    for email in find_emails(text)[:5]:
        out.append(Evidence(EMAIL, email, SRC, 0.7, url, "texto da pagina",
                            personal=is_personal_email(email)))
    for number, kind in find_phones(text, CONFIG.default_ddd)[:5]:
        out.append(Evidence(PHONE, number, SRC, 0.6, url, f"texto da pagina ({kind})"))
    for handle in find_instagram(html)[:2]:
        out.append(Evidence(INSTAGRAM, handle, SRC, 0.7, url))
    return out


def enrich(site_url: str) -> list[Evidence]:
    if not site_url:
        return []
    status, html = fetch(site_url)
    if status != 200 or not html:
        for scheme_host in (site_url.replace("https://", "http://"),
                            site_url.replace("https://", "https://www.")):
            status, html = fetch(scheme_host)
            if status == 200 and html:
                site_url = scheme_host
                break
    if status != 200 or not html:
        return []

    out = [Evidence(WEBSITE, site_url, SRC, 0.8, site_url)]
    out.extend(_extract(html, site_url))
    for page in _internal_links(html, site_url):
        sub_status, sub_html = fetch(page)
        if sub_status == 200 and sub_html:
            out.extend(_extract(sub_html, page))
    return out
