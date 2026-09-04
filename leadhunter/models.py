from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

# Tipos de evidencia coletada por uma fonte.
CNPJ = "cnpj"
RAZAO = "razao_social"
FANTASIA = "nome_fantasia"
OWNER = "proprietario"
PHONE = "telefone"
WHATSAPP = "whatsapp"
EMAIL = "email"
WEBSITE = "site"
INSTAGRAM = "instagram"
ADDRESS = "endereco"


@dataclass
class Evidence:
    kind: str
    value: str
    source: str
    confidence: float
    url: str = ""
    note: str = ""
    # True quando o dado pertence a pessoa fisica do dono, nao a empresa.
    personal: bool = False

    def key(self) -> tuple[str, str]:
        return (self.kind, self.value.lower())


@dataclass
class Lead:
    row: int
    nome_ml: str = ""
    perfil_url: str = ""
    seller_id: str = ""
    nickname: str = ""
    cidade: str = ""
    uf: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def label(self) -> str:
        return self.nome_ml or self.nickname or self.perfil_url or f"linha {self.row}"


@dataclass
class Result:
    lead: Lead
    evidences: list[Evidence] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    score: float = 0.0
    tier: str = "D"

    def add(self, ev: Evidence | None) -> None:
        if ev is None or not ev.value:
            return
        for existing in self.evidences:
            if existing.key() == ev.key():
                if ev.confidence > existing.confidence:
                    existing.confidence = ev.confidence
                    existing.source = ev.source
                    existing.url = ev.url
                if ev.personal:
                    existing.personal = True
                return
        self.evidences.append(ev)

    def extend(self, evs) -> None:
        for ev in evs or []:
            self.add(ev)

    def of(self, kind: str) -> list[Evidence]:
        return sorted(
            [e for e in self.evidences if e.kind == kind],
            key=lambda e: (-e.confidence, e.value),
        )

    def first(self, kind: str, default: str = "") -> str:
        found = self.of(kind)
        return found[0].value if found else default

    def sources(self) -> list[str]:
        seen: list[str] = []
        for e in self.evidences:
            if e.source not in seen:
                seen.append(e.source)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead": asdict(self.lead),
            "score": self.score,
            "tier": self.tier,
            "evidences": [asdict(e) for e in self.evidences],
            "errors": self.errors,
        }
