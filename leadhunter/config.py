import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass
class Config:
    serpapi_key: str = field(default_factory=lambda: os.getenv("SERPAPI_KEY", "").strip())
    google_cse_key: str = field(default_factory=lambda: os.getenv("GOOGLE_CSE_KEY", "").strip())
    google_cse_cx: str = field(default_factory=lambda: os.getenv("GOOGLE_CSE_CX", "").strip())
    brave_key: str = field(default_factory=lambda: os.getenv("BRAVE_SEARCH_KEY", "").strip())
    google_maps_key: str = field(default_factory=lambda: os.getenv("GOOGLE_MAPS_KEY", "").strip())
    cnpjws_token: str = field(default_factory=lambda: os.getenv("CNPJWS_TOKEN", "").strip())

    workers: int = field(default_factory=lambda: _int("LH_WORKERS", 4))
    rate_limit: float = field(default_factory=lambda: _float("LH_RATE_LIMIT", 1.0))
    timeout: int = field(default_factory=lambda: _int("LH_TIMEOUT", 25))

    default_ddd: str = field(default_factory=lambda: os.getenv("LH_DEFAULT_DDD", "48").strip())
    cidade: str = field(default_factory=lambda: os.getenv("LH_CIDADE", "Tubarao").strip())
    uf: str = field(default_factory=lambda: os.getenv("LH_UF", "SC").strip())

    cache_path: Path = ROOT / ".cache" / "http.sqlite"
    receita_db: Path = ROOT / "data" / "receita" / "cnpj_local.sqlite"

    @property
    def search_provider(self) -> str:
        if self.serpapi_key:
            return "serpapi"
        if self.google_cse_key and self.google_cse_cx:
            return "google_cse"
        if self.brave_key:
            return "brave"
        return "duckduckgo"


CONFIG = Config()
