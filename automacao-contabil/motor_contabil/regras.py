"""Classificação determinística por regras aprovadas pelo contador.

Arquivo JSON:
{
  "conta_banco": "1.1.1.02.001",
  "regras": [
    {"id": "tarifa", "padrao": "TARIFA|TAR\\b", "sentido": "saida",
     "conta": "4.2.1.01", "historico": "Tarifa bancária"}
  ]
}

`documento` casa por CPF ou CNPJ completo, `raiz_cnpj` pelos oito primeiros
dígitos do CNPJ, e `padrao` por expressão regular sobre o histórico normalizado
(maiúsculas, sem acentos). Informe pelo menos um critério. A precedência é
documento, raiz e padrão. `sentido` é "entrada", "saida" ou "ambos".

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
from .texto import normalizar, normalizar_documento

PRECEDENCIA = {"documento": 0, "raiz_cnpj": 1, "padrao": 2}


@dataclass(frozen=True)
class Regra:
    id: str
    padrao: re.Pattern[str] | None
    sentido: str
    conta: str
    historico: str | None
    documento: str = ""
    raiz_cnpj: str | None = None
    forcar_pendente: bool = False
    motivo: str = ""

    def criterio(self, documento: str, historico: str, sentido: str) -> str | None:
        if self.sentido not in ("ambos", sentido):
            return None
        if self.documento and self.documento == documento:
            return "documento"
        if len(documento) == 14 and self.raiz_cnpj == documento[:8]:
            return "raiz_cnpj"
        if self.padrao is not None and self.padrao.search(historico):
            return "padrao"
        return None

    def casa(self, t: Transacao) -> bool:
        return self.criterio(normalizar_documento(t.documento), normalizar(t.historico),
                             t.sentido) is not None


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
            identificador = bruta["id"]
            if identificador in ids:
                raise ValueError(f"regra repetida: {identificador}")
            ids.add(identificador)
            sentido = bruta.get("sentido", "ambos")
            if sentido not in ("entrada", "saida", "ambos"):
                raise ValueError(f"regra {identificador}: use entrada, saida ou ambos em sentido.")
            documento = normalizar_documento(bruta.get("documento"))
            if "documento" in bruta and not documento:
                raise ValueError(
                    f"regra {identificador}: informe documento como texto com "
                    "11 dígitos para CPF ou 14 para CNPJ."
                )
            raiz = bruta.get("raiz_cnpj")
            if "raiz_cnpj" in bruta and (
                not isinstance(raiz, str) or not re.fullmatch(r"[0-9]{8}", raiz)
            ):
                raise ValueError(
                    f"regra {identificador}: informe os 8 primeiros dígitos do "
                    "CNPJ em raiz_cnpj, entre aspas e sem pontuação."
                )
            padrao = bruta.get("padrao")
            if padrao is None and not documento and raiz is None:
                raise ValueError(
                    f"regra {identificador}: informe documento, raiz_cnpj ou padrao."
                )
            forcar_pendente = bruta.get("forcar_pendente", False)
            motivo = bruta.get("motivo", "")
            if not isinstance(forcar_pendente, bool) or not isinstance(motivo, str):
                raise ValueError(
                    f"regra {identificador}: use true ou false em forcar_pendente "
                    "e escreva o motivo como texto."
                )
            regras.append(
                Regra(
                    id=identificador,
                    padrao=re.compile(padrao, re.IGNORECASE) if padrao is not None else None,
                    sentido=sentido,
                    conta=bruta["conta"],
                    historico=bruta.get("historico_padrao", bruta.get("historico")),
                    documento=documento,
                    raiz_cnpj=raiz,
                    forcar_pendente=forcar_pendente,
                    motivo=motivo.strip(),
                )
            )
        return cls(conta_banco=dados["conta_banco"], regras=regras)

    def classificar(self, t: Transacao) -> Classificacao:
        documento = normalizar_documento(t.documento)
        historico = normalizar(t.historico)
        sentido = t.sentido
        casadas = [
            (regra, criterio) for regra in self.regras
            if (criterio := regra.criterio(documento, historico, sentido)) is not None
        ]
        if not casadas:
            return Classificacao(None, None, "nenhuma", "nenhuma regra reconhece o histórico")
        contas = {regra.conta for regra, _ in casadas}
        if len(contas) > 1:
            ids = ", ".join(sorted(regra.id for regra, _ in casadas))
            return Classificacao(None, None, "nenhuma", f"regras conflitantes: {ids}")
        casadas.sort(key=lambda par: (PRECEDENCIA[par[1]], par[0].id))
        regra, criterio = casadas[0]
        motivos = tuple(
            f"regra {casada.id}: {casada.motivo or 'confira a contrapartida antes de aprovar.'}"
            for casada, _ in casadas if casada.forcar_pendente
        )
        return Classificacao(regra.conta, regra.historico, f"regra:{regra.id}",
                             criterio=criterio, motivos_revisao=motivos)
