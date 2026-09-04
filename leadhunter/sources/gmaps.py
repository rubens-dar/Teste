from __future__ import annotations

import json

from leadhunter.config import CONFIG
from leadhunter.http import fetch
from leadhunter.models import ADDRESS, Evidence, PHONE, WEBSITE, WHATSAPP
from leadhunter.normalize import normalize_phone, slug_name

SRC = "google_maps"
ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELDS = (
    "places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
    "places.internationalPhoneNumber,places.websiteUri,places.googleMapsUri"
)


def enrich(nome: str, cidade: str, uf: str) -> list[Evidence]:
    """Perfil do Google Business costuma trazer o telefone que a empresa realmente atende."""
    if not CONFIG.google_maps_key or not nome:
        return []

    query = f"{nome} {cidade} {uf}".strip()
    status, body = fetch(
        ENDPOINT,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": CONFIG.google_maps_key,
            "X-Goog-FieldMask": FIELDS,
        },
        json_body={
            "textQuery": query,
            "languageCode": "pt-BR",
            "regionCode": "BR",
            "maxResultCount": 3,
        },
    )
    if status != 200 or not body:
        return []
    try:
        places = json.loads(body).get("places", [])
    except json.JSONDecodeError:
        return []

    target = slug_name(nome)
    out: list[Evidence] = []
    for place in places:
        display = (place.get("displayName") or {}).get("text", "")
        address = place.get("formattedAddress", "")
        # So aceita o lugar se o nome bater e o endereco for da cidade certa.
        if cidade and cidade.lower()[:5] not in slug_name(address):
            continue
        from rapidfuzz import fuzz

        score = fuzz.token_set_ratio(target, slug_name(display))
        if score < 70:
            continue

        confidence = 0.85 if score >= 85 else 0.7
        maps_url = place.get("googleMapsUri", "")
        raw_phone = place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber") or ""
        parsed = normalize_phone(raw_phone, CONFIG.default_ddd)
        if parsed:
            number, kind = parsed
            out.append(Evidence(PHONE, number, SRC, confidence, maps_url,
                                f"{display} ({kind})"))
            if kind == "movel":
                out.append(Evidence(WHATSAPP, number, SRC, confidence - 0.1, maps_url,
                                    "celular do perfil no Google"))
        if place.get("websiteUri"):
            out.append(Evidence(WEBSITE, place["websiteUri"], SRC, confidence, maps_url))
        if address:
            out.append(Evidence(ADDRESS, address, SRC, 0.7, maps_url))
        break
    return out
