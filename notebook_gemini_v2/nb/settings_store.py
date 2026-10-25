"""Configurações salvas pela própria tela (chave e modelos), em data/config.json.
O arquivo fica só no computador do usuário e é ignorado pelo Git."""
import json
import os
from pathlib import Path

FILE_NAME = "config.json"
ALLOWED = ("api_key", "embedding_model", "gemini_model")


def _path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def load(data_dir: Path) -> dict[str, str]:
    try:
        data = json.loads(_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if k in ALLOWED and isinstance(v, str)} if isinstance(data, dict) else {}


def save(data_dir: Path, **updates: str) -> None:
    unknown = set(updates) - set(ALLOWED)
    if unknown:
        raise ValueError(f"Chaves de configuração desconhecidas: {sorted(unknown)}")
    data = {**load(data_dir), **updates}
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # no Windows é ignorado; em Linux/Mac restringe ao dono
    except OSError:
        pass
    tmp.replace(path)  # troca atômica: nunca deixa o arquivo pela metade


def mask_key(key: str) -> str:
    if not key:
        return "(nenhuma)"
    return f"{key[:4]}…{key[-3:]} ({len(key)} caracteres)" if len(key) > 10 else "(curta demais para ser válida)"
