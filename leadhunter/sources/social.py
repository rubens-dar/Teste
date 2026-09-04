from __future__ import annotations

import re

from leadhunter.config import CONFIG
from leadhunter.http import fetch
from leadhunter.models import EMAIL, Evidence, INSTAGRAM, PHONE, WHATSAPP
from leadhunter.normalize import (
    find_emails, find_instagram, find_phones, find_whatsapp_links, is_personal_email,
    slug_name,
)
from leadhunter.sources.search import search

SRC = "social"
BIO_RE = re.compile(r'"biography"\s*:\s*"([^"]{0,600})"')
OG_DESC_RE = re.compile(r'<meta[^>]+property="og:description"[^>]+content="([^"]{0,600})"', re.I)


def _evidences_from_text(text: str, url: str, note: str, confidence: float) -> list[Evidence]:
    out: list[Evidence] = []
    for number in find_whatsapp_links(text):
        out.append(Evidence(WHATSAPP, number, SRC, confidence, url, note))
        out.append(Evidence(PHONE, number, SRC, confidence - 0.05, url, note))
    for number, kind in find_phones(text, CONFIG.default_ddd)[:3]:
        out.append(Evidence(PHONE, number, SRC, confidence - 0.15, url, f"{note} ({kind})"))
        if kind == "movel":
            out.append(Evidence(WHATSAPP, number, SRC, confidence - 0.2, url, note))
    for email in find_emails(text)[:2]:
        out.append(Evidence(EMAIL, email, SRC, confidence - 0.1, url, note,
                            personal=is_personal_email(email)))
    return out


def instagram_profile(handle: str) -> list[Evidence]:
    """A bio do Instagram e onde a maioria das lojas pequenas publica o WhatsApp."""
    if not handle:
        return []
    url = f"https://www.instagram.com/{handle}/"
    status, html = fetch(url)
    if status != 200 or not html:
        return []

    bio = ""
    match = BIO_RE.search(html) or OG_DESC_RE.search(html)
    if match:
        bio = match.group(1).encode().decode("unicode_escape", errors="ignore")
    blob = bio or html[:200000]
    out = [Evidence(INSTAGRAM, handle, SRC, 0.8, url)]
    out.extend(_evidences_from_text(blob, url, "bio do Instagram", 0.8))
    return out


def find_social(nome: str, cidade: str, owner: str = "") -> list[Evidence]:
    out: list[Evidence] = []
    target = slug_name(nome)

    results = search(f'"{nome}" {cidade} instagram', limit=8)
    handles: list[str] = []
    for res in results:
        blob = f"{res['url']} {res.get('title', '')} {res.get('snippet', '')}"
        for handle in find_instagram(blob):
            if handle not in handles:
                handles.append(handle)
        # O snippet da busca ja costuma conter o telefone que esta na bio.
        if "instagram.com" in res["url"]:
            out.extend(_evidences_from_text(
                res.get("snippet", ""), res["url"], "snippet do Instagram", 0.6))

    from rapidfuzz import fuzz

    handles.sort(key=lambda h: -fuzz.partial_ratio(target, h.replace(".", " ").replace("_", " ")))
    for handle in handles[:2]:
        out.extend(instagram_profile(handle))

    if owner:
        for res in search(f'"{owner}" {cidade} site:linkedin.com/in', limit=5):
            if "linkedin.com/in" in res["url"]:
                out.append(Evidence(
                    "linkedin", res["url"], SRC, 0.6, res["url"], res.get("title", "")))
                break
    return out
