from __future__ import annotations

from leadhunter.models import CNPJ, EMAIL, INSTAGRAM, OWNER, PHONE, Result, WEBSITE, WHATSAPP


def score(res: Result) -> None:
    owners = res.of(OWNER)
    whats = res.of(WHATSAPP)
    phones = res.of(PHONE)
    emails = res.of(EMAIL)

    total = 0.0
    if res.of(CNPJ):
        total += 10
    if owners:
        total += 30 * max(e.confidence for e in owners)
    if whats:
        total += 35 * max(e.confidence for e in whats)
    if phones:
        total += 20 * max(e.confidence for e in phones)
    if emails:
        total += 15 * max(e.confidence for e in emails)
        if any(e.personal for e in emails):
            total += 5
    if res.of(WEBSITE) or res.of(INSTAGRAM):
        total += 5

    res.score = min(total, 100.0)

    has_contact = bool(whats or phones or emails)
    if owners and whats:
        res.tier = "A"
    elif owners and has_contact:
        res.tier = "B"
    elif has_contact:
        res.tier = "C"
    else:
        res.tier = "D"
