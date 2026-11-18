"""Registro de homologação da P-004.

Cada item só vira 'aprovado' com evidência anexada (arquivo guardado com
SHA-256) e, quando o sistema consegue conferir, com a condição verificada em
código. O registro é só de inclusão: um resultado novo não apaga o anterior.

Itens dependentes da instalação real do Fortes nunca são aprovados por teste
automatizado.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import config
from domain.deduplicator import sha256
from storage.database import agora, conectar_empresa


@dataclass(frozen=True)
class Item:
    codigo: str
    titulo: str
    criterio: str
    referencia: str   # o que o campo referência deve conter


ITENS: dict[str, Item] = {i.codigo: i for i in (
    Item("H1", "Importação real de lote no Fortes",
         "Um lote gerado pelo app é importado no Fortes sem erro e todas as marcas aparecem no Razão "
         "exportado depois, uma vez só, com data, valor e contas iguais.",
         "slug-da-empresa:id-do-lote (lote aceito e com conferência no Razão aprovada)"),
    Item("H2", "Limite de caracteres do histórico",
         "O Fortes aceita o histórico no tamanho configurado sem cortar a marca [PREFIXO-AAAAMM-NNNNNN].",
         "limite validado (número inteiro)"),
    Item("H3", "Leiaute do Razão exportado pelo Fortes",
         "Um Razão real, exportado do Fortes, é lido pelo app e o saldo do banco bate com o mostrado no Fortes.",
         "formato do leitor validado: fortes_importacao ou tabular"),
    Item("H4", "Backup e restauração",
         "Backup restaurado em pasta isolada na máquina do escritório, com contagens, SHA-256 e "
         "integridade iguais aos da origem.",
         "anexar o JSON gerado por scripts/teste_restauracao.py"),
    Item("H5", "Extratos reais do piloto",
         "Um OFX e um CSV/XLSX reais de cada banco do piloto são carregados sem erro estrutural e "
         "o saldo final calculado bate com o do extrato.",
         "bancos e formatos testados"),
)}

# itens que precisam estar aprovados para considerar a integração com o Fortes liberada
NECESSARIOS_LIBERACAO = ("H1", "H2", "H3", "H4", "H5")


class HomologacaoInvalida(ValueError):
    pass


def _pasta(data_dir: Path | None) -> Path:
    p = (data_dir or config.DATA_DIR) / "homologacao"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _checar_h1(referencia: str, data_dir: Path | None) -> None:
    try:
        slug, lote = referencia.split(":")
        lote_id = int(lote)
    except ValueError as exc:
        raise HomologacaoInvalida("H1: referência deve ser slug:id_do_lote") from exc
    con = conectar_empresa(slug, data_dir)
    try:
        l = con.execute("SELECT * FROM lotes WHERE id = ?", (lote_id,)).fetchone()
    finally:
        con.close()
    if l is None:
        raise HomologacaoInvalida(f"H1: lote {lote_id} não existe em {slug}")
    if l["status"] != "aceito":
        raise HomologacaoInvalida("H1: o lote precisa estar com retorno 'importado sem erro'")
    conf = json.loads(l["conferencia_razao"] or "{}")
    if not conf.get("aprovado"):
        raise HomologacaoInvalida("H1: a conferência do lote no Razão não foi feita ou não foi aprovada")


def _checar_h2(referencia: str) -> None:
    from exporters.fortes_exporter import validar_limite
    try:
        validar_limite(int(referencia))
    except ValueError as exc:
        raise HomologacaoInvalida(f"H2: {exc}") from exc


def _checar_h3(referencia: str) -> None:
    if referencia not in ("fortes_importacao", "tabular"):
        raise HomologacaoInvalida("H3: referência deve ser 'fortes_importacao' ou 'tabular'")


def _checar_h4(evidencia: bytes) -> None:
    try:
        dados = json.loads(evidencia.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HomologacaoInvalida("H4: a evidência deve ser o JSON de scripts/teste_restauracao.py") from exc
    if dados.get("ferramenta") != "teste_restauracao" or dados.get("resultado") != "aprovado":
        raise HomologacaoInvalida("H4: o relatório de restauração anexado não está aprovado")
    if dados.get("origem_sintetica"):
        raise HomologacaoInvalida("H4: o teste foi feito com dados de demonstração; repita com a base do escritório")


def registrar(central: sqlite3.Connection, usuario: sqlite3.Row, item: str, status: str, teste: str,
              resultado: str, falha: str = "", acao_corretiva: str = "", evidencia_nome: str | None = None,
              evidencia: bytes | None = None, referencia: str = "", data_dir: Path | None = None) -> int:
    if usuario["papel_global"] != "admin":
        raise HomologacaoInvalida("só administrador registra homologação")
    if item not in ITENS:
        raise HomologacaoInvalida(f"item desconhecido: {item}")
    if status not in ("aprovado", "reprovado", "em_teste"):
        raise HomologacaoInvalida("status deve ser aprovado, reprovado ou em_teste")
    if len(teste.strip()) < 10 or len(resultado.strip()) < 10:
        raise HomologacaoInvalida("descreva o teste realizado e o resultado observado")
    if status == "reprovado" and not (falha.strip() and acao_corretiva.strip()):
        raise HomologacaoInvalida("reprovação exige a falha identificada e a ação corretiva")
    if status == "aprovado":
        if not evidencia:
            raise HomologacaoInvalida("aprovação exige evidência anexada (arquivo)")
        ref = referencia.strip()
        if item == "H1":
            _checar_h1(ref, data_dir)
        elif item == "H2":
            _checar_h2(ref)
        elif item == "H3":
            _checar_h3(ref)
        elif item == "H4":
            _checar_h4(evidencia)
        elif not ref:
            raise HomologacaoInvalida(f"{item}: informe a referência ({ITENS[item].referencia})")
    caminho = sha = None
    if evidencia:
        sha = sha256(evidencia)
        ext = Path(evidencia_nome or "").suffix.lower()[:8]
        destino = _pasta(data_dir) / f"{item}_{sha[:16]}{ext}"
        if not destino.exists():
            destino.write_bytes(evidencia)
            os.chmod(destino, 0o444)
        caminho = str(destino)
    cur = central.execute(
        "INSERT INTO homologacoes (item, status, tipo_teste, teste, resultado, falha, acao_corretiva, evidencia_nome, "
        "evidencia_sha256, evidencia_caminho, referencia, registrado_por, registrado_em) "
        "VALUES (?, ?, 'instalacao_real', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (item, status, teste.strip(), resultado.strip(), falha.strip() or None, acao_corretiva.strip() or None,
         evidencia_nome, sha, caminho, referencia.strip() or None, usuario["nome"], agora()),
    )
    return cur.lastrowid


def estado(central: sqlite3.Connection) -> dict[str, sqlite3.Row | None]:
    """Último registro de cada item (None = nunca testado)."""
    atual = {}
    for codigo in ITENS:
        atual[codigo] = central.execute(
            "SELECT * FROM homologacoes WHERE item = ? ORDER BY id DESC LIMIT 1", (codigo,)).fetchone()
    return atual


def historico(central: sqlite3.Connection) -> list[sqlite3.Row]:
    return central.execute("SELECT * FROM homologacoes ORDER BY id").fetchall()


def aprovado(central: sqlite3.Connection, item: str) -> bool:
    r = estado(central)[item]
    return r is not None and r["status"] == "aprovado"


def integracao_liberada(central: sqlite3.Connection) -> bool:
    return all(aprovado(central, i) for i in NECESSARIOS_LIBERACAO)


def razao_homologado(central: sqlite3.Connection, formato: str | None) -> bool:
    r = estado(central)["H3"]
    return bool(formato) and r is not None and r["status"] == "aprovado" and r["referencia"] == formato


def evidencia_integra(row: sqlite3.Row) -> bool | None:
    if not row["evidencia_caminho"]:
        return None
    f = Path(row["evidencia_caminho"])
    return f.exists() and sha256(f.read_bytes()) == row["evidencia_sha256"]
