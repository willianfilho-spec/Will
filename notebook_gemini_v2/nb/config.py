"""Configuração lida do ambiente (.env). Nada aqui contém segredos fixos."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from . import settings_store

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".pptx", ".txt", ".md", ".csv")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_bytes: int
    gemini_api_key: str
    gemini_model: str
    embedding_model: str
    embedding_dim: int
    top_k: int
    key_source: str = ""  # "tela", ".env" ou "" (ausente)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "notebook.db"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"


def _max_upload_bytes() -> int:
    raw = os.getenv("MAX_UPLOAD_MB", "50").strip()
    try:
        mb = float(raw)
    except ValueError:
        mb = 50.0
    return int(max(mb, 0.1) * 1024 * 1024)


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default
    return min(max(value, low), high)


def _clean_key(raw: str) -> str:
    """Remove aspas e espaços colados por engano; o texto de exemplo do .env.example conta como ausente."""
    key = raw.strip().strip("\"'").strip()
    return "" if key.lower().startswith("cole_") else key


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR") or PROJECT_DIR / "data")
    saved = settings_store.load(data_dir)  # o que foi salvo pela tela vale mais que o .env
    env_key = _clean_key(os.getenv("GEMINI_API_KEY", ""))
    saved_key = _clean_key(saved.get("api_key", ""))
    return Settings(
        data_dir=data_dir,
        max_upload_bytes=_max_upload_bytes(),
        gemini_api_key=saved_key or env_key,
        gemini_model=saved.get("gemini_model") or os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        embedding_model=saved.get("embedding_model") or os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001").strip(),
        embedding_dim=_int_env("EMBEDDING_DIM", 768, 32, 3072),
        top_k=_int_env("TOP_K", 6, 1, 30),
        key_source="tela" if saved_key else (".env" if env_key else ""),
    )
