"""Leitor das planilhas "Despesas extrato" (.xlsx) usadas pelo escritório.

Formato observado (maio a outubro de 2026):

    linha 1: EMPRESA: <nome>
    linha 2: DESPESAS
    linha 3: DATA | LANÇAMENTO BANCÁRIO | DESCRIÇÃO | VALOR | CAIXA/BANCO
    linhas seguintes: uma movimentação por linha, VALOR positivo
    última linha: =SUM(...) na coluna VALOR, sem data

Decisões:
  - O cabeçalho é localizado pelo conteúdo (DATA e VALOR), não pela posição.
  - Linhas sem data (totais, linhas em branco) não são movimentação.
  - Como a planilha é de DESPESAS, valor positivo vira saída (negativo no
    motor). Valor negativo na planilha (estorno) vira entrada.
  - A DESCRIÇÃO vira o campo `favorecido`, separado do histórico. Ela entra
    na identificação de duplicidade (sem ela, pagamentos diferentes com o
    mesmo texto, valor e dia seriam indistinguíveis), mas as regras só a
    consultam quando configuradas para isso.
  - Linhas com sinais de extração defeituosa recebem alertas e vão para
    revisão, mesmo que alguma regra as reconheça.
  - O Excel guarda valores como ponto flutuante; a conversão para Decimal
    arredonda em centavos e recusa valores com mais de duas casas
    significativas, para não esconder erro de digitação.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from ..modelo import Transacao
from ..texto import normalizar

COLUNAS = {
    "data": {"DATA"},
    "lancamento": {"LANCAMENTO BANCARIO", "LANCAMENTO", "HISTORICO"},
    "descricao": {"DESCRICAO", "FAVORECIDO"},
    "valor": {"VALOR"},
    "conta": {"CAIXA/BANCO", "BANCO"},
}
# Palavras que indicam o tipo de operação no texto do banco. Uma linha sem
# nenhuma delas (ex.: só "SANTOS") costuma ser pedaço de outra linha que a
# extração do PDF separou.
TIPOS_DE_OPERACAO = re.compile(
    r"\b(PIX|BOLETOS?|PAGAMENTOS?|PAGTO|PGTO|TAR|TARIFAS?|IOF|JUROS|TRANSF\w*|TED|DOC"
    r"|SAQUES?|DEP\w*|CHEQUES?|DEBITOS?|CREDITOS?|ESTORNOS?|CONVENIOS?)\b"
)
ALERTA_SEM_TIPO = "texto do extrato sem tipo de operação (possível pedaço de outra linha)"
ALERTA_SEM_TEXTO = "linha sem texto do extrato"
ALERTA_DOIS_NOMES = "favorecido com 6 ou mais palavras (possível junção de dois nomes)"
ALERTA_ENCARGO_COM_FAVORECIDO = (
    "encargo bancário com favorecido preenchido (possível desalinhamento da coluna DESCRIÇÃO)"
)
ENCARGO_BANCARIO = re.compile(r"^(TAR|TARIFAS?|IOF|JUROS)\b")


def alertas_de_qualidade(lancamento: str, descricao: str) -> tuple[str, ...]:
    """Sinais de que a linha veio mal extraída. Na dúvida, vai para revisão."""
    alertas = []
    if not lancamento:
        alertas.append(ALERTA_SEM_TEXTO)
    elif not TIPOS_DE_OPERACAO.search(normalizar(lancamento)):
        alertas.append(ALERTA_SEM_TIPO)
    if len(descricao.split()) >= 6:
        alertas.append(ALERTA_DOIS_NOMES)
    if descricao and ENCARGO_BANCARIO.search(normalizar(lancamento)):
        alertas.append(ALERTA_ENCARGO_COM_FAVORECIDO)
    return tuple(alertas)


def _valor(bruto, onde: str) -> Decimal:
    if isinstance(bruto, bool) or bruto is None:
        raise ValueError(f"{onde}: valor ausente")
    if isinstance(bruto, (int, float)):
        exato = Decimal(repr(bruto))
    else:
        from ..texto import para_decimal

        exato = para_decimal(str(bruto))
    centavos = exato.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    if abs(exato - centavos) > Decimal("0.000001"):
        raise ValueError(f"{onde}: valor com mais de duas casas decimais ({bruto!r})")
    return centavos


def _data(bruto, onde: str) -> date | None:
    if isinstance(bruto, datetime):
        return bruto.date()
    if isinstance(bruto, date):
        return bruto
    if isinstance(bruto, str) and bruto.strip():
        for formato in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                return datetime.strptime(bruto.strip(), formato).date()
            except ValueError:
                continue
        raise ValueError(f"{onde}: data inválida {bruto!r}")
    return None


def ler_planilha_despesas(caminho: str | Path, conta_bancaria: str) -> list[Transacao]:
    try:
        import openpyxl
    except ImportError as erro:  # dependência só deste leitor
        raise RuntimeError("Para ler .xlsx instale o pacote openpyxl.") from erro

    caminho = Path(caminho)
    livro = openpyxl.load_workbook(caminho, data_only=False)
    transacoes: list[Transacao] = []
    for aba in livro.worksheets:
        colunas: dict[str, int] | None = None
        for linha in aba.iter_rows():
            valores = [c.value for c in linha]
            if colunas is None:
                nomes = [normalizar(str(v)) if v is not None else "" for v in valores]
                achadas = {
                    campo: i for campo, sinonimos in COLUNAS.items()
                    for i, nome in enumerate(nomes) if nome in sinonimos
                }
                if "data" in achadas and "valor" in achadas:
                    colunas = achadas
                continue

            numero = linha[0].row
            onde = f"{caminho.name}, aba {aba.title!r}, linha {numero}"
            celula = lambda campo: valores[colunas[campo]] if campo in colunas and colunas[campo] < len(valores) else None  # noqa: E731
            data_mov = _data(celula("data"), onde)
            if data_mov is None:
                continue  # total, subtotal ou linha vazia
            valor = _valor(celula("valor"), onde)
            lancamento = " ".join(str(celula("lancamento") or "").split())
            descricao = " ".join(str(celula("descricao") or "").split())
            transacoes.append(
                Transacao(
                    conta_bancaria=str(celula("conta") or "").strip() or conta_bancaria,
                    data=data_mov,
                    valor=-valor,
                    historico=lancamento,
                    favorecido=descricao or None,
                    origem=caminho.name,
                    linha=numero,
                    alertas=alertas_de_qualidade(lancamento, descricao),
                )
            )
        if colunas is None:
            raise ValueError(
                f"{caminho.name}, aba {aba.title!r}: cabeçalho com DATA e VALOR não encontrado"
            )
    livro.close()
    return transacoes
