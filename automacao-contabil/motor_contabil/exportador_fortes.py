"""Exportação no leiaute de importação de lançamentos do Fortes Contábil.

O leiaute foi tirado de arquivos reais que o Fortes aceitou no escritório
(conciliação da primeira empresa do piloto, 2026), e não de memória:

    data;debito;credito;valor;historico;;;;

- sem cabeçalho;
- separador ponto e vírgula, com quatro campos vazios no fim (nove campos);
- data em dd/mm/aaaa;
- contas pelo código reduzido do plano (`codigo_exportacao`);
- valor positivo, com vírgula decimal e sem separador de milhar;
- histórico em maiúsculas, só ASCII, com até 118 caracteres;
- uma marca entre colchetes no fim do histórico identifica o lançamento e
  garante que não existam duas linhas iguais no arquivo;
- arquivo em ASCII, com fim de linha CRLF.

Se o Fortes de outra empresa usar um leiaute diferente, crie outra classe com
o mesmo método `escrever`; não adapte esta por suposição.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from .plano_contas import PlanoDeContas
from .texto import formatar_valor, normalizar

LIMITE_HISTORICO = 118
CAMPOS_VAZIOS_NO_FIM = 4


class ErroDeExportacao(ValueError):
    """O lote não pode ser exportado; a mensagem lista todos os problemas."""


def _ascii(texto: str) -> str:
    """Maiúsculas, sem acentos, sem ponto e vírgula e sem caractere fora do ASCII."""
    limpo = normalizar(texto).replace(";", ",")
    limpo = limpo.encode("ascii", "replace").decode("ascii")
    return re.sub(r"\s+", " ", limpo).strip()


class ExportadorFortes:
    def __init__(self, plano: PlanoDeContas, prefixo_marca: str = "EXT"):
        if not re.fullmatch(r"[A-Z0-9]{2,6}", prefixo_marca):
            raise ValueError("o prefixo da marca deve ter de 2 a 6 letras maiúsculas ou números")
        self.plano = plano
        self.prefixo_marca = prefixo_marca

    def _reduzido(self, codigo: str | None, papel: str, problemas: list[str], ref: str) -> str:
        conta = self.plano.get(codigo)
        if conta is None:
            problemas.append(f"{ref}: conta de {papel} {codigo!r} não existe no plano de contas")
            return ""
        if not conta.analitica:
            problemas.append(f"{ref}: conta de {papel} {codigo} é sintética")
            return ""
        if not conta.codigo_exportacao.isdigit():
            problemas.append(
                f"{ref}: conta de {papel} {codigo} está sem código reduzido numérico no plano"
            )
            return ""
        return conta.codigo_exportacao

    def _historico(self, texto: str, marca: str) -> str:
        espaco = LIMITE_HISTORICO - len(marca) - 1
        return f"{_ascii(texto)[:espaco].rstrip()} {marca}"

    def linhas(self, lancamentos: list[dict]) -> list[str]:
        """Monta as linhas do arquivo ou levanta ErroDeExportacao com tudo o que impede."""
        problemas: list[str] = []
        linhas: list[str] = []
        for item in lancamentos:
            data = date.fromisoformat(item["data"])
            ref = f"lançamento {item['chave'][:12]} de {data.strftime('%d/%m/%Y')}"
            valor = abs(Decimal(item["valor"]))
            if valor == 0:
                problemas.append(f"{ref}: valor zero")
            debito = self._reduzido(item["conta_debito"], "débito", problemas, ref)
            credito = self._reduzido(item["conta_credito"], "crédito", problemas, ref)
            if debito and debito == credito:
                problemas.append(f"{ref}: débito e crédito na mesma conta reduzida {debito}")
            marca = f"[{self.prefixo_marca}-{data.strftime('%Y%m')}-{item['chave'][:8].upper()}]"
            campos = [
                data.strftime("%d/%m/%Y"),
                debito,
                credito,
                formatar_valor(valor),
                self._historico(item["historico"], marca),
            ] + [""] * CAMPOS_VAZIOS_NO_FIM
            linhas.append(";".join(campos))
        repetidas = {linha for linha in linhas if linhas.count(linha) > 1}
        if repetidas:
            problemas.append(f"{len(repetidas)} linha(s) idêntica(s) no lote")
        if problemas:
            raise ErroDeExportacao(
                "O lote não foi exportado. Corrija e exporte de novo:\n- " + "\n- ".join(problemas)
            )
        return linhas

    def escrever(self, lancamentos: list[dict], destino: str | Path) -> None:
        linhas = self.linhas(lancamentos)
        conteudo = "".join(linha + "\r\n" for linha in linhas)
        Path(destino).write_bytes(conteudo.encode("ascii"))
