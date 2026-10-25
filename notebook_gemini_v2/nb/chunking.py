"""Divide páginas em trechos (chunks) sem nunca atravessar a fronteira de página,
para que cada trecho tenha uma página exata."""
import re
from collections import Counter
from dataclasses import dataclass

MAX_CHARS = 1200
MIN_CHARS = 40
OVERLAP = 150

# Início de dispositivo normativo: o trecho tende a começar nesses pontos.
_STRUCTURE = re.compile(
    r"^(?:Art\.\s*\d+|§\s*\d+|Parágrafo\s+[ÚUúu]nico|CAPÍTULO|SEÇÃO|Seção|TÍTULO|[IVXL]+\s*[-–]\s|[a-z]\)\s)"
)


@dataclass(frozen=True)
class Chunk:
    page_number: int | None
    text: str


def find_boilerplate(pages: list[tuple[int | None, str]]) -> set[str]:
    """Linhas curtas que se repetem na maioria das páginas (cabeçalho, rodapé, nº de página)."""
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for _, text in pages:
        counts.update({_signature(ln) for ln in text.splitlines() if ln.strip() and len(ln) < 200})
    limit = max(3, int(len(pages) * 0.6))
    return {sig for sig, n in counts.items() if n >= limit}


def _signature(line: str) -> str:
    return re.sub(r"\d+", "#", " ".join(line.split()))


def chunk_pages(pages: list[tuple[int | None, str]]) -> list[Chunk]:
    boiler = find_boilerplate(pages)
    chunks: list[Chunk] = []
    for number, text in pages:
        lines = [ln for ln in text.splitlines() if ln.strip() and _signature(ln) not in boiler]
        for piece in _pack(_blocks(lines)):
            if len(piece) >= MIN_CHARS:
                chunks.append(Chunk(number, piece))
    return chunks


def _blocks(lines: list[str]) -> list[str]:
    """Agrupa linhas em blocos; um novo bloco começa em cada dispositivo normativo."""
    blocks: list[list[str]] = []
    for ln in lines:
        ln = " ".join(ln.split())
        if not blocks or _STRUCTURE.match(ln):
            blocks.append([ln])
        else:
            blocks[-1].append(ln)
    return [" ".join(b) for b in blocks]


def _pack(blocks: list[str]) -> list[str]:
    """Junta blocos consecutivos até MAX_CHARS; divide os que passam disso."""
    out: list[str] = []
    current = ""
    for block in blocks:
        for part in _split_long(block):
            if current and len(current) + 1 + len(part) > MAX_CHARS:
                out.append(current)
                current = part
            else:
                current = f"{current} {part}".strip()
    if current:
        out.append(current)
    return out


def _split_long(block: str) -> list[str]:
    if len(block) <= MAX_CHARS:
        return [block]
    sentences = re.split(r"(?<=[.;:])\s+", block)
    parts: list[str] = []
    current = ""
    for sent in sentences:
        while len(sent) > MAX_CHARS:  # sem pontuação: corta no espaço mais próximo, com sobreposição
            cut = sent.rfind(" ", 0, MAX_CHARS)
            cut = cut if cut > MAX_CHARS // 2 else MAX_CHARS
            if current:
                parts.append(current)
                current = ""
            parts.append(sent[:cut])
            sent = sent[max(cut - OVERLAP, 0):].lstrip()
            if len(sent) <= OVERLAP:
                break
        if current and len(current) + 1 + len(sent) > MAX_CHARS:
            parts.append(current)
            current = sent
        else:
            current = f"{current} {sent}".strip()
    if current:
        parts.append(current)
    return parts
