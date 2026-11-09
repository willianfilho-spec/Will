"""Classificação determinística por regras aprovadas pelo contador.

Arquivo JSON:
{
  "conta_banco": "1.1.1.02.001",
  "regras": [
    {"id": "tarifa", "padrao": "TARIFA|TAR\\b", "sentido": "saida",
     "conta": "4.2.1.01", "historico": "Tarifa bancária"}
  ]
}

`padrao` é uma expressão regular aplicada ao texto normalizado (maiúsculas,
sem acentos). `sentido` é "entrada", "saida" ou "ambos". `campo` diz onde
procurar: "historico" (padrão, o texto do banco) ou "favorecido".

Por que o favorecido não entra por padrão: nomes de pessoas casam com
padrões por acidente. "FRANCISCO DAS CHAGAS" casaria com uma regra de DAS.

Se mais de uma regra casar e elas apontarem contas diferentes, o motor não
escolhe: o lançamento vai para revisão. A ordem das regras no arquivo não
decide conflito, porque isso esconderia erros de parametrização.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .modelo import Classificacao, Transacao
from .texto import normalizar


@dataclass(frozen=True)
class Regra:
    id: str
    padrao: re.Pattern[str]
    sentido: str
    conta: str
    historico: str | None
    campo: str = "historico"

    def casa(self, t: Transacao) -> bool:
        if self.sentido not in ("ambos", t.sentido):
            return False
        texto = t.favorecido if self.campo == "favorecido" else t.historico
        return bool(texto) and bool(self.padrao.search(normalizar(texto)))


@dataclass
class ConjuntoDeRegras:
    conta_banco: str
    regras: list[Regra]

    @classmethod
    def carregar(cls, caminho: str | Path) -> "ConjuntoDeRegras":
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        regras = []
        ids = set()
        for bruta in dados.get("regras", []):
            if bruta["id"] in ids:
                raise ValueError(f"regra repetida: {bruta['id']}")
            ids.add(bruta["id"])
            sentido = bruta.get("sentido", "ambos")
            if sentido not in ("entrada", "saida", "ambos"):
                raise ValueError(f"regra {bruta['id']}: sentido inválido {sentido!r}")
            campo = bruta.get("campo", "historico")
            if campo not in ("historico", "favorecido"):
                raise ValueError(f"regra {bruta['id']}: campo inválido {campo!r}")
            regras.append(
                Regra(
                    id=bruta["id"],
                    padrao=re.compile(bruta["padrao"], re.IGNORECASE),
                    sentido=sentido,
                    conta=bruta["conta"],
                    historico=bruta.get("historico"),
                    campo=campo,
                )
            )
        return cls(conta_banco=dados["conta_banco"], regras=regras)

    def classificar(self, t: Transacao) -> Classificacao:
        casadas = [r for r in self.regras if r.casa(t)]
        if not casadas:
            return Classificacao(None, None, "nenhuma", "nenhuma regra reconhece o histórico")
        contas = {r.conta for r in casadas}
        if len(contas) > 1:
            ids = ", ".join(r.id for r in casadas)
            return Classificacao(None, None, "nenhuma", f"regras conflitantes: {ids}")
        regra = casadas[0]
        return Classificacao(regra.conta, regra.historico, f"regra:{regra.id}")
