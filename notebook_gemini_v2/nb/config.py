"""Configuração lida do ambiente (.env). Nada aqui contém segredos fixos."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md", ".csv")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_bytes: int
    gemini_api_key: str
    gemini_model: str

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


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR") or PROJECT_DIR / "data")
    return Settings(
        data_dir=data_dir,
        max_upload_bytes=_max_upload_bytes(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
    )
