"""Motor determinístico de regras por prioridade.

Mesma entrada, mesma saída: as regras são avaliadas em ordem de prioridade
(menor número primeiro; empate pelo id) e vence a primeira que casar.
Regra nunca aprova sozinha: gera uma proposta que alguém revisa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from parsers.comum import normalizar


@dataclass(frozen=True)
class Regra:
    id: int
    prioridade: int
    nome: str
    tipo_padrao: str          # contem | igual | regex
    padrao: str
    sentido: str              # entrada | saida | ambos
    conta_contrapartida: str
    historico: str | None = None
    natureza: str = "normal"
    valor_min_centavos: int | None = None
    valor_max_centavos: int | None = None

    def casa(self, historico: str, valor_centavos: int) -> bool:
        if self.sentido == "entrada" and valor_centavos < 0:
            return False
        if self.sentido == "saida" and valor_centavos > 0:
            return False
        absv = abs(valor_centavos)
        if self.valor_min_centavos is not None and absv < self.valor_min_centavos:
            return False
        if self.valor_max_centavos is not None and absv > self.valor_max_centavos:
            return False
        h = normalizar(historico)
        if self.tipo_padrao == "contem":
            return normalizar(self.padrao) in h
        if self.tipo_padrao == "igual":
            return normalizar(self.padrao) == h
        if self.tipo_padrao == "regex":
            return re.search(self.padrao, h) is not None
        raise ValueError(f"tipo de padrão desconhecido: {self.tipo_padrao}")


def validar_regex(padrao: str) -> None:
    try:
        re.compile(padrao)
    except re.error as exc:
        raise ValueError(f"expressão regular inválida: {exc}") from exc


def ordenar(regras: list[Regra]) -> list[Regra]:
    return sorted(regras, key=lambda r: (r.prioridade, r.id))


def encontrar(regras: list[Regra], historico: str, valor_centavos: int) -> Regra | None:
    for r in ordenar(regras):
        if r.casa(historico, valor_centavos):
            return r
    return None


def partidas(valor_centavos: int, conta_banco: str, contrapartida: str) -> tuple[str, str]:
    """(débito, crédito). Entrada no banco debita o banco; saída credita."""
    if valor_centavos > 0:
        return conta_banco, contrapartida
    return contrapartida, conta_banco
