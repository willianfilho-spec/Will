"""Leitor CSV/XLSX de extratos e planilhas de despesas, com mapeamento de colunas.

O mapeamento diz qual coluna é data, histórico e valor. O valor pode vir numa
coluna só (com sinal) ou em duas (entrada e saída / crédito e débito).
Qualquer linha com data ou valor inválido recusa o arquivo inteiro.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from domain.money import ValorInvalido, para_centavos
from parsers.comum import ErroEstrutural, decodificar, normalizar, para_data, sanitizar_texto


@dataclass
class Mapeamento:
    data: str
    historico: str
    valor: str | None = None          # coluna única com sinal
    entrada: str | None = None        # ou duas colunas
    saida: str | None = None
    documento: str | None = None
    inverter_sinal: bool = False      # planilha de despesas costuma trazer saída positiva

    def validar(self) -> None:
        if not self.data or not self.historico:
            raise ErroEstrutural(["mapeamento: informe as colunas de data e de histórico"])
        if not self.valor and not (self.entrada or self.saida):
            raise ErroEstrutural(["mapeamento: informe a coluna de valor ou as de entrada/saída"])


def ler_tabela(bruto: bytes, nome_arquivo: str) -> tuple[list[str], list[dict]]:
    """Devolve (colunas, linhas) como texto. Aceita .csv, .txt e .xlsx."""
    nome = nome_arquivo.lower()
    if nome.endswith(".xlsx") or nome.endswith(".xlsm"):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(bruto), read_only=True, data_only=True)
        except Exception as exc:  # arquivo corrompido ou não-xlsx
            raise ErroEstrutural([f"XLSX ilegível: {exc}"]) from exc
        ws = wb.worksheets[0]
        linhas = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    elif nome.endswith(".csv") or nome.endswith(".txt"):
        texto = decodificar(bruto)
        amostra = texto[:4096]
        try:
            dialeto = csv.Sniffer().sniff(amostra, delimiters=";,\t|")
            delim = dialeto.delimiter
        except csv.Error:
            delim = ";"
        linhas = list(csv.reader(io.StringIO(texto, newline=""), delimiter=delim))
    else:
        raise ErroEstrutural([f"formato não suportado: {nome_arquivo} (use CSV ou XLSX)"])
    linhas = [l for l in linhas if any(c not in (None, "") for c in l)]
    if not linhas:
        raise ErroEstrutural(["arquivo vazio"])
    cab = [sanitizar_texto(c) or f"coluna_{i + 1}" for i, c in enumerate(linhas[0])]
    if len(set(cab)) != len(cab):
        raise ErroEstrutural([f"cabeçalho com nomes repetidos: {cab}"])
    dados = []
    for l in linhas[1:]:
        l = list(l) + [None] * (len(cab) - len(l))
        dados.append(dict(zip(cab, l)))
    return cab, dados


def sugerir_mapeamento(colunas: list[str]) -> dict:
    """Palpite inicial pelo nome da coluna; o operador confirma na tela."""
    n = {c: normalizar(c) for c in colunas}

    def achar(*termos):
        for c, nc in n.items():
            if any(t in nc for t in termos):
                return c
        return None

    return {
        "data": achar("DATA", "DT "),
        "historico": achar("HISTORICO", "DESCRICAO", "LANCAMENTO", "FAVORECIDO", "MEMO"),
        "valor": achar("VALOR", "QUANTIA", "MONTANTE"),
        "entrada": achar("ENTRADA", "CREDITO"),
        "saida": achar("SAIDA", "DEBITO"),
        "documento": achar("DOCUMENTO", "DOC", "NUMERO"),
    }


def _cent(v) -> int:
    if v is None or (isinstance(v, str) and not v.strip()):
        return 0
    if isinstance(v, float):
        return para_centavos(f"{v:.2f}") if round(v, 2) == v else para_centavos(v)
    return para_centavos(v)


def extrair_movimentos(linhas: list[dict], mapa: Mapeamento) -> list[dict]:
    mapa.validar()
    colunas = set(linhas[0].keys()) if linhas else set()
    faltando = [c for c in (mapa.data, mapa.historico, mapa.valor, mapa.entrada, mapa.saida, mapa.documento)
                if c and c not in colunas]
    if faltando:
        raise ErroEstrutural([f"coluna inexistente no arquivo: {c}" for c in faltando])
    problemas, saida = [], []
    for i, l in enumerate(linhas, start=2):
        try:
            d = para_data(l[mapa.data]).isoformat()
        except ValueError as exc:
            problemas.append(f"linha {i}: {exc}")
            continue
        try:
            if mapa.valor:
                v = _cent(l[mapa.valor])
            else:
                ent = abs(_cent(l.get(mapa.entrada))) if mapa.entrada else 0
                sai = abs(_cent(l.get(mapa.saida))) if mapa.saida else 0
                if ent and sai:
                    raise ValorInvalido("linha com entrada e saída ao mesmo tempo")
                v = ent - sai
            if mapa.inverter_sinal:
                v = -v
        except ValorInvalido as exc:
            problemas.append(f"linha {i}: {exc}")
            continue
        if v == 0:
            problemas.append(f"linha {i}: valor zero ou vazio")
            continue
        hist = sanitizar_texto(l[mapa.historico])
        if not hist:
            problemas.append(f"linha {i}: histórico vazio")
            continue
        saida.append({
            "linha": i, "data": d, "valor_centavos": v, "historico": hist,
            "documento": sanitizar_texto(l.get(mapa.documento)) if mapa.documento else None,
            "fitid": None,
        })
    if problemas:
        raise ErroEstrutural(problemas)
    if not saida:
        raise ErroEstrutural(["nenhum movimento encontrado"])
    return saida
