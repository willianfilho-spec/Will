"""Validação das citações: o programa confere o que o modelo afirma contra os trechos
efetivamente recuperados. Nada aqui chama a rede.

Limite importante: provar que uma citação literal EXISTE no trecho não prova que o trecho
sustenta a conclusão. Quem decide isso continua sendo o leitor."""
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field

from .rag import Hit

TIPOS = ("documentada", "inferencia", "recomendacao")
MIN_QUOTE_CHARS = 15  # depois de normalizar; citações menores não provam nada
_MARKER = re.compile(r"F(\d+)", re.I)


def fold(text: str) -> str:
    """Normaliza para comparar texto literal: sem acentos, caixa, espaços, hífens e pontuação.
    Necessário porque PDFs trazem espaços indevidos ('efeti vada') e quebras de hífen."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", "", text)


@dataclass
class Claim:
    tipo: str
    texto: str
    fontes: list[str]
    trecho: str | None


@dataclass
class Parsed:
    ok: bool
    raw: str
    evidencia_suficiente: bool | None = None
    claims: list[Claim] = field(default_factory=list)
    divergencias: list[str] = field(default_factory=list)
    lacunas: str = ""
    error: str = ""


@dataclass
class SourceRef:
    label: str
    document_id: str
    document_name: str
    page_number: int | None
    chunk_id: int


@dataclass
class ClaimCheck:
    claim: Claim
    status: str
    notes: list[str]
    sources: list[SourceRef]


STATUS_LABEL = {
    "confirmada": "Citação literal confirmada no trecho citado",
    "outro_trecho": "Citação existe, mas em outro trecho que não o indicado",
    "nao_confirmada": "Citação NÃO encontrada nos trechos recuperados",
    "sem_fonte": "Afirmação documentada sem fonte ou sem citação literal",
    "inferencia": "Inferência (não é texto expresso da fonte)",
    "recomendacao": "Recomendação (não é texto expresso da fonte)",
    "formato_invalido": "Tipo de afirmação inválido; não verificada",
}


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.S | re.I)
    return m.group(1) if m else raw


def parse_response(raw: str) -> Parsed:
    try:
        data = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, TypeError):
        return Parsed(False, raw, error="A resposta não veio no formato estruturado esperado; nenhuma citação foi verificada.")
    if not isinstance(data, dict) or not isinstance(data.get("afirmacoes", []), list):
        return Parsed(False, raw, error="A resposta não tem o campo 'afirmacoes'; nenhuma citação foi verificada.")
    claims = []
    for item in data.get("afirmacoes", []):
        if not isinstance(item, dict) or not str(item.get("texto", "")).strip():
            continue
        fontes = item.get("fontes") or []
        if isinstance(fontes, str):
            fontes = [fontes]
        trecho = item.get("trecho")
        claims.append(Claim(
            tipo=str(item.get("tipo", "")).strip(),
            texto=str(item["texto"]).strip(),
            fontes=[str(f) for f in fontes],
            trecho=str(trecho).strip() if isinstance(trecho, str) and trecho.strip() else None,
        ))
    suficiente = data.get("evidencia_suficiente")
    div = data.get("divergencias") or []
    return Parsed(
        True, raw,
        evidencia_suficiente=suficiente if isinstance(suficiente, bool) else None,
        claims=claims,
        divergencias=[str(d) for d in div] if isinstance(div, list) else [str(div)],
        lacunas=str(data.get("lacunas") or "").strip(),
    )


def _tipo(raw: str) -> str | None:
    t = fold(raw)
    return t if t in TIPOS else None


def _quote_in(quote: str, chunk_text: str) -> bool:
    """Cada trecho da citação (separados por reticências) deve aparecer, em ordem."""
    segments = [fold(s) for s in re.split(r"\[?\s*(?:\.{3}|…)\s*\]?", quote)]
    segments = [s for s in segments if len(s) >= 8]
    if sum(len(s) for s in segments) < MIN_QUOTE_CHARS:
        return False
    haystack, pos = fold(chunk_text), 0
    for seg in segments:
        found = haystack.find(seg, pos)
        if found < 0:
            return False
        pos = found + len(seg)
    return True


def _resolve(markers: list[str], hits: list[Hit]) -> tuple[list[tuple[str, Hit]], list[str]]:
    resolved, invalid = [], []
    for m in markers:
        match = _MARKER.fullmatch(m.strip().strip("[]"))
        idx = int(match.group(1)) if match else 0
        if 1 <= idx <= len(hits):
            resolved.append((f"F{idx}", hits[idx - 1]))
        else:
            invalid.append(m)
    return resolved, invalid


_PAGE_MENTION = re.compile(r"\b(?:p[áa]g(?:ina)?s?\.?|p\.)\s*(\d+)", re.I)
_ART_MENTION = re.compile(r"\bart(?:igo)?s?\.?\s*(\d+)", re.I)
_PAR_MENTION = re.compile(r"§\s*(\d+)")


def _text_alerts(texto: str, cited: list[Hit]) -> list[str]:
    """Alertas sobre páginas, dispositivos e números escritos no texto da afirmação que não
    aparecem nos trechos citados. São avisos, não reprovações: o modelo pode ter calculado algo."""
    if not cited:
        return []
    alerts: list[str] = []
    body = " ".join(h.text for h in cited)
    pages = sorted({h.page_number for h in cited if h.page_number is not None})
    for m in _PAGE_MENTION.finditer(texto):
        if int(m.group(1)) not in pages:
            alerts.append(f"O texto menciona a página {m.group(1)}, mas os trechos citados estão em: {pages or 'sem página'}.")
    for m in _ART_MENTION.finditer(texto):
        if not re.search(rf"\bart(?:igo)?s?\.?\s*{m.group(1)}(?!\d)", body, re.I):
            alerts.append(f'O dispositivo "Art. {m.group(1)}" escrito no texto não aparece nos trechos citados.')
    for m in _PAR_MENTION.finditer(texto):
        if not re.search(rf"§\s*{m.group(1)}(?!\d)", body):
            alerts.append(f'O dispositivo "§ {m.group(1)}" escrito no texto não aparece nos trechos citados.')
    plain = _PAGE_MENTION.sub(" ", _ART_MENTION.sub(" ", _PAR_MENTION.sub(" ", texto)))
    for num in dict.fromkeys(re.findall(r"\d+(?:[.,]\d+)?", plain)):
        if not re.search(rf"(?<![\d.,]){re.escape(num)}(?![\d])", body):
            alerts.append(f"O número {num} escrito no texto não aparece nos trechos citados.")
    return alerts


def verify(parsed: Parsed, hits: list[Hit]) -> list[ClaimCheck]:
    checks: list[ClaimCheck] = []
    for claim in parsed.claims:
        resolved, invalid = _resolve(claim.fontes, hits)
        sources = [SourceRef(lab, h.document_id, h.document_name, h.page_number, h.chunk_id) for lab, h in resolved]
        notes = [f"Marcador {m} não corresponde a nenhum trecho recuperado." for m in invalid]
        tipo = _tipo(claim.tipo)
        if tipo is None:
            checks.append(ClaimCheck(claim, "formato_invalido", notes, sources))
            continue
        cited = [h for _, h in resolved]
        if tipo in ("inferencia", "recomendacao"):
            checks.append(ClaimCheck(claim, tipo, notes + _text_alerts(claim.texto, cited), sources))
            continue
        if not resolved or not claim.trecho:
            checks.append(ClaimCheck(claim, "sem_fonte", notes, sources))
            continue
        if any(_quote_in(claim.trecho, h.text) for h in cited):
            status = "confirmada"
        else:
            elsewhere = [f"F{i}" for i, h in enumerate(hits, 1) if h not in cited and _quote_in(claim.trecho, h.text)]
            if elsewhere:
                status = "outro_trecho"
                notes.append(f"A citação aparece em {', '.join(elsewhere)}, não em {', '.join(s.label for s in sources)}.")
            else:
                status = "nao_confirmada"
        checks.append(ClaimCheck(claim, status, notes + _text_alerts(claim.texto, cited), sources))
    return checks


def summarize(parsed: Parsed, checks: list[ClaimCheck]) -> dict:
    documented = [c for c in checks if _tipo(c.claim.tipo) == "documentada"]
    confirmed = [c for c in documented if c.status == "confirmada"]
    return {
        "documentadas": len(documented),
        "confirmadas": len(confirmed),
        "problemas": sum(1 for c in checks if c.status in ("outro_trecho", "nao_confirmada", "sem_fonte", "formato_invalido")),
        "alertas": sum(len(c.notes) for c in checks),
        "evidencia_suficiente": parsed.evidencia_suficiente,
        "nenhuma_confirmada": bool(documented) and not confirmed,
    }


def to_json(parsed: Parsed, checks: list[ClaimCheck], hits: list[Hit]) -> str:
    """Registro persistente: a pergunta pode ser auditada depois sem reexecutar o modelo."""
    return json.dumps({
        "parsed": {"ok": parsed.ok, "evidencia_suficiente": parsed.evidencia_suficiente,
                   "divergencias": parsed.divergencias, "lacunas": parsed.lacunas, "error": parsed.error},
        "checks": [{"claim": asdict(c.claim), "status": c.status, "notes": c.notes, "sources": [asdict(s) for s in c.sources]} for c in checks],
        "hits": [{"label": f"F{i}", **{k: getattr(h, k) for k in ("chunk_id", "document_id", "document_name", "page_number", "text", "score")}}
                 for i, h in enumerate(hits, 1)],
        "summary": summarize(parsed, checks),
    }, ensure_ascii=False)
