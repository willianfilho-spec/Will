"""Interface opcional de sugestão por IA. Desativada (config.ENABLE_AI = False).

Contrato, para quando for ligada:
- recebe só o histórico, o valor e a lista de contas analíticas da empresa ativa
  (nunca dados de outra empresa);
- devolve no máximo uma sugestão com justificativa, ou None;
- a sugestão entra como origem 'ia' e passa pela mesma revisão humana de
  qualquer item. A IA nunca classifica, aprova, confirma ou exporta.
"""

from __future__ import annotations

from dataclasses import dataclass

import config


@dataclass(frozen=True)
class Sugestao:
    conta_contrapartida: str
    justificativa: str
    confianca: float


def disponivel() -> bool:
    return bool(config.ENABLE_AI)


def sugerir(historico: str, valor_centavos: int, contas: list[dict]) -> Sugestao | None:
    if not disponivel():
        return None
    raise NotImplementedError(
        "Integração de IA não implementada no MVP. Implemente aqui respeitando o contrato do módulo."
    )
