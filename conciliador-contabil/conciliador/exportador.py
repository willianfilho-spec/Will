"""Etapa 3: arquivos de conferência, arquivo de importação e registro de auditoria."""

import csv
import getpass
import hashlib
import json
from datetime import datetime
from pathlib import Path

from .leitor import detectar_delimitador, ler_texto
from .modelos import STATUS_APROVADO, STATUS_CLASSIFICADO, Lancamento

CABECALHO = [
    "data", "conta_debito", "conta_credito", "valor", "historico", "documento",
    "fornecedor", "origem", "regra", "status", "observacao", "linha_extrato", "descricao_extrato",
]


class ErroLayout(Exception):
    """O arquivo de layout de importação está incompleto ou inválido."""


def _linha(l: Lancamento) -> list:
    return [
        l.data.strftime("%d/%m/%Y"), l.conta_debito, l.conta_credito,
        f"{l.valor:.2f}".replace(".", ","), l.historico, l.documento, l.fornecedor,
        l.origem, l.regra, l.status, l.observacao, l.linha_extrato, l.descricao_extrato,
    ]


def _gravar(caminho: Path, lancamentos: list[Lancamento]) -> None:
    # utf-8-sig e ponto e vírgula: o arquivo abre direto no Excel em português.
    with open(caminho, "w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(CABECALHO)
        escritor.writerows(_linha(l) for l in lancamentos)


def ler_revisao(caminho) -> list[dict]:
    """Lê a planilha de revisão, inclusive depois de editada e salva pelo Excel."""
    texto = ler_texto(Path(caminho))
    linhas = [l for l in texto.splitlines() if l.strip()]
    if not linhas:
        return []
    leitor = csv.DictReader(linhas, delimiter=detectar_delimitador(linhas[0]))
    return [{(k or "").strip().lower(): v for k, v in registro.items()} for registro in leitor]


def exportar_conferencia(lancamentos: list[Lancamento], pasta_saida) -> tuple[Path, Path]:
    """Grava todos os lançamentos e a planilha de revisão.

    A planilha de revisão traz tudo o que não foi classificado por regra
    objetiva, inclusive o que já foi aprovado: é o registro das decisões.
    """
    pasta = Path(pasta_saida)
    pasta.mkdir(parents=True, exist_ok=True)
    _gravar(pasta / "lancamentos.csv", lancamentos)
    _gravar(pasta / "revisao.csv", [l for l in lancamentos if l.status != STATUS_CLASSIFICADO])
    return pasta / "lancamentos.csv", pasta / "revisao.csv"


def carregar_layout(caminho) -> dict:
    try:
        layout = json.loads(Path(caminho).read_text(encoding="utf-8"))
        colunas = layout["colunas"]
    except (OSError, ValueError, KeyError) as erro:
        raise ErroLayout(f"Layout de importação inválido ({caminho}): {erro}") from erro
    campos = set(CABECALHO)
    for coluna in colunas:
        if ("campo" in coluna) == ("fixo" in coluna):
            raise ErroLayout(f"Coluna {coluna}: informe 'campo' ou 'fixo' (apenas um).")
        if "campo" in coluna and coluna["campo"] not in campos:
            raise ErroLayout(f"Campo desconhecido no layout: {coluna['campo']}. Disponíveis: {sorted(campos)}")
    return layout


def exportar_importacao(lancamentos: list[Lancamento], layout: dict, pasta_saida) -> Path:
    """Grava o arquivo destinado ao sistema contábil, conforme o layout configurado."""
    caminho = Path(pasta_saida) / layout.get("arquivo", "importacao.csv")
    formato_data = layout.get("formato_data", "%d/%m/%Y")
    decimal = layout.get("separador_decimal", ",")

    def valor_da_coluna(l: Lancamento, coluna: dict) -> str:
        if "fixo" in coluna:
            return str(coluna["fixo"])
        bruto = getattr(l, coluna["campo"])
        if coluna["campo"] == "data":
            texto = bruto.strftime(formato_data)
        elif coluna["campo"] == "valor":
            texto = f"{bruto:.2f}".replace(".", decimal)
        else:
            texto = str(bruto)
        if coluna.get("sem_pontuacao"):
            texto = "".join(c for c in texto if c.isalnum())
        return texto[: coluna["tamanho_maximo"]] if coluna.get("tamanho_maximo") else texto

    with open(caminho, "w", encoding=layout.get("codificacao", "utf-8"), newline="", errors="replace") as arquivo:
        escritor = csv.writer(arquivo, delimiter=layout.get("delimitador", ";"))
        if layout.get("cabecalho", True):
            escritor.writerow([c.get("titulo", c.get("campo", "")) for c in layout["colunas"]])
        escritor.writerows([valor_da_coluna(l, c) for c in layout["colunas"]] for l in lancamentos)
    return caminho


def sha256(caminho) -> str:
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


def gravar_auditoria(pasta_saida, *, arquivos_entrada: dict, saldo: str, lancamentos: list[Lancamento],
                     alteracoes: list[dict], arquivo_importacao) -> Path:
    """Acrescenta uma linha ao histórico de execuções (um JSON por linha).

    Registra quem rodou, quando, com quais arquivos (pelo hash), qual regra
    classificou cada linha e o que foi alterado ou aprovado manualmente.
    """
    registro = {
        "executado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "usuario_do_sistema": getpass.getuser(),
        "arquivos_de_entrada": {
            nome: {"caminho": str(caminho), "sha256": sha256(caminho)}
            for nome, caminho in arquivos_entrada.items() if caminho
        },
        "conferencia_de_saldo": saldo,
        "totais_por_status": {
            status: sum(1 for l in lancamentos if l.status == status)
            for status in sorted({l.status for l in lancamentos})
        },
        "aprovacoes_e_alteracoes_manuais": alteracoes,
        "arquivo_de_importacao": (
            {"caminho": str(arquivo_importacao), "sha256": sha256(arquivo_importacao)}
            if arquivo_importacao else None
        ),
        "lancamentos": [
            {"linha_extrato": l.linha_extrato, "origem": l.origem, "regra": l.regra,
             "status": l.status, "conta_debito": l.conta_debito, "conta_credito": l.conta_credito}
            for l in lancamentos
        ],
    }
    caminho = Path(pasta_saida) / "auditoria.jsonl"
    with open(caminho, "a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return caminho


def ha_aprovacoes(caminho) -> bool:
    caminho = Path(caminho)
    return caminho.exists() and any(
        (r.get("status") or "").strip().upper() == STATUS_APROVADO for r in ler_revisao(caminho)
    )
