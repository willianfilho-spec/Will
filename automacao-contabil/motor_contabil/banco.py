"""Persistência em SQLite: transações, lançamentos, lotes e trilha de auditoria.

A chave primária de `transacoes` é a chave de idempotência. É o próprio banco
de dados que impede a segunda gravação da mesma transação, e não apenas uma
verificação no código.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS lotes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo          TEXT NOT NULL CHECK (tipo IN ('importacao', 'exportacao')),
    criado_em     TEXT NOT NULL,
    usuario       TEXT NOT NULL,
    descricao     TEXT NOT NULL,
    hash_arquivo  TEXT
);

CREATE TABLE IF NOT EXISTS transacoes (
    chave           TEXT PRIMARY KEY,
    chave_conteudo  TEXT NOT NULL,
    fitid           TEXT,
    conta_bancaria  TEXT NOT NULL,
    data            TEXT NOT NULL,
    valor           TEXT NOT NULL,
    historico       TEXT NOT NULL,
    favorecido      TEXT,
    documento       TEXT,
    origem          TEXT NOT NULL,
    linha           INTEGER NOT NULL,
    lote_id         INTEGER NOT NULL REFERENCES lotes(id)
);
CREATE INDEX IF NOT EXISTS ix_transacoes_conteudo ON transacoes(chave_conteudo);

CREATE TABLE IF NOT EXISTS lancamentos (
    chave                TEXT PRIMARY KEY REFERENCES transacoes(chave),
    conta_contrapartida  TEXT,
    conta_debito         TEXT,
    conta_credito        TEXT,
    historico            TEXT NOT NULL,
    status               TEXT NOT NULL,
    motivos              TEXT NOT NULL DEFAULT '',
    fonte                TEXT NOT NULL,
    lote_exportacao      INTEGER REFERENCES lotes(id),
    atualizado_em        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lancamentos_status ON lancamentos(status);

CREATE TABLE IF NOT EXISTS eventos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    quando    TEXT NOT NULL,
    usuario   TEXT NOT NULL,
    chave     TEXT,
    lote_id   INTEGER,
    acao      TEXT NOT NULL,
    detalhe   TEXT NOT NULL DEFAULT ''
);
"""


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class BancoDeDados:
    def __init__(self, caminho: str | Path):
        self.caminho = str(caminho)
        self.conexao = sqlite3.connect(self.caminho)
        self.conexao.row_factory = sqlite3.Row
        self.conexao.execute("PRAGMA foreign_keys = ON")
        self.conexao.executescript(ESQUEMA)
        colunas = {r["name"] for r in self.conexao.execute("PRAGMA table_info(transacoes)")}
        if "favorecido" not in colunas:  # banco criado por versão anterior
            self.conexao.execute("ALTER TABLE transacoes ADD COLUMN favorecido TEXT")
            self.conexao.commit()

    @contextmanager
    def transacao(self):
        """Tudo ou nada: se algo falhar no meio, nada é gravado."""
        try:
            yield self.conexao
            self.conexao.commit()
        except Exception:
            self.conexao.rollback()
            raise

    def registrar_evento(self, usuario: str, acao: str, detalhe: str = "",
                         chave: str | None = None, lote_id: int | None = None) -> None:
        self.conexao.execute(
            "INSERT INTO eventos (quando, usuario, chave, lote_id, acao, detalhe)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (agora(), usuario, chave, lote_id, acao, detalhe),
        )

    def fechar(self) -> None:
        self.conexao.close()
