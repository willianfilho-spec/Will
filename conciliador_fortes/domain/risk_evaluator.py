"""Gatilhos de segunda revisão.

Um item exige segunda confirmação, por pessoa diferente de quem revisou,
quando qualquer gatilho abaixo dispara.
"""

from __future__ import annotations

from domain.money import formatar_br
from parsers.comum import normalizar


def avaliar(valor_centavos: int, historico: str, natureza: str, decisao_duplicidade: str,
            limite_centavos: int, termos_socios: list[str]) -> list[str]:
    motivos = []
    if abs(valor_centavos) >= limite_centavos:
        motivos.append(f"valor igual ou acima do limite de revisão ({formatar_br(limite_centavos)})")
    h = normalizar(historico)
    if natureza == "socio" or any(normalizar(t) in h for t in termos_socios if t.strip()):
        motivos.append("movimento com sócio")
    if natureza == "incerta":
        motivos.append("natureza incerta")
    if decisao_duplicidade == "manter":
        motivos.append("possível duplicidade mantida")
    return motivos
