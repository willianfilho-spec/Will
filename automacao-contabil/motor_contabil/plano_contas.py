"""Plano de contas parametrizável por escritório/empresa.

Arquivo CSV com cabeçalho: codigo;descricao;tipo[;codigo_exportacao]
  - tipo: A (analítica, aceita lançamento) ou S (sintética, só agrupa).
  - codigo_exportacao (opcional): o código que o sistema contábil de destino
    espera (ex.: código reduzido). Se vazio, exporta o próprio `codigo`.

Não se presume que o código de um escritório vale para outro: cada empresa
tem o seu arquivo.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Conta:
    codigo: str
    descricao: str
    analitica: bool
    codigo_exportacao: str


class PlanoDeContas:
    def __init__(self, contas: list[Conta]):
        self._contas = {c.codigo: c for c in contas}

    @classmethod
    def carregar(cls, caminho: str | Path) -> "PlanoDeContas":
        texto = Path(caminho).read_text(encoding="utf-8-sig")
        delimitador = ";" if texto.count(";") >= texto.count(",") else ","
        contas = []
        for linha in csv.DictReader(texto.splitlines(), delimiter=delimitador):
            codigo = (linha.get("codigo") or "").strip()
            if not codigo:
                continue
            contas.append(
                Conta(
                    codigo=codigo,
                    descricao=(linha.get("descricao") or "").strip(),
                    analitica=(linha.get("tipo") or "A").strip().upper() == "A",
                    codigo_exportacao=(linha.get("codigo_exportacao") or "").strip()
                    or codigo,
                )
            )
        return cls(contas)

    @classmethod
    def carregar_fortes(cls, caminho: str | Path) -> "PlanoDeContas":
        """Lê o plano de contas como o Fortes Contábil o exporta em CSV.

        Formato conferido em um arquivo real: sem cabeçalho, campos entre
        aspas, separador ponto e vírgula, na ordem
        classificação;descrição;reduzido;...  Só as contas com código
        reduzido aceitam lançamento; as demais são tratadas como sintéticas.
        """
        bruto = Path(caminho).read_bytes()
        try:
            texto = bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = bruto.decode("cp1252")
        contas = []
        for numero, campos in enumerate(csv.reader(texto.splitlines(), delimiter=";"), start=1):
            if not campos or not campos[0].strip():
                continue
            if len(campos) < 3:
                raise ValueError(
                    f"{Path(caminho).name}, linha {numero}: esperados ao menos 3 campos "
                    "(classificação, descrição, reduzido). Exporte o plano de novo pelo Fortes."
                )
            codigo, descricao, reduzido = (c.strip() for c in campos[:3])
            if reduzido and not reduzido.isdigit():
                raise ValueError(
                    f"{Path(caminho).name}, linha {numero}: código reduzido {reduzido!r} não é numérico"
                )
            contas.append(
                Conta(
                    codigo=codigo,
                    descricao=descricao,
                    analitica=bool(reduzido),
                    codigo_exportacao=reduzido or codigo,
                )
            )
        if not contas:
            raise ValueError(f"{Path(caminho).name}: nenhuma conta encontrada")
        reduzidos = [c.codigo_exportacao for c in contas if c.analitica]
        repetidos = sorted({r for r in reduzidos if reduzidos.count(r) > 1})
        if repetidos:
            raise ValueError(
                f"{Path(caminho).name}: código reduzido repetido no plano: {', '.join(repetidos)}"
            )
        return cls(contas)

    def por_reduzido(self, reduzido: str) -> Conta | None:
        """Conta analítica com esse código de exportação (o reduzido do Fortes)."""
        for conta in self._contas.values():
            if conta.analitica and conta.codigo_exportacao == str(reduzido):
                return conta
        return None

    def get(self, codigo: str | None) -> Conta | None:
        return self._contas.get(codigo or "")

    def analiticas(self) -> list[Conta]:
        return [c for c in self._contas.values() if c.analitica]

    def problema(self, codigo: str | None) -> str | None:
        """Motivo pelo qual a conta não pode receber lançamento, ou None."""
        if not codigo:
            return "conta não definida"
        conta = self.get(codigo)
        if conta is None:
            return f"conta {codigo} não existe no plano de contas"
        if not conta.analitica:
            return f"conta {codigo} é sintética e não aceita lançamento"
        return None
