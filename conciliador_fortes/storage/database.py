"""Inicialização e conexões de central.db e contabil.db.

data/
├── central.db                 usuários, empresas, permissões, auditoria de acesso
└── empresas/<slug>/
    ├── contabil.db            dados contábeis isolados da empresa
    └── arquivos/{originais,exportacoes,relatorios}/

Cada empresa tem banco e pasta próprios: uma consulta nunca alcança dados de
outra empresa porque a conexão só abre o arquivo da empresa ativa.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import config

SCHEMA_CENTRAL = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    papel_global TEXT NOT NULL CHECK (papel_global IN ('cliente', 'equipe', 'revisor', 'aprovador', 'admin')),
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS empresas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    razao_social TEXT NOT NULL,
    cnpj TEXT UNIQUE NOT NULL,
    limite_revisao_centavos INTEGER NOT NULL DEFAULT 1000000,
    ativa INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS permissoes_empresa (
    usuario_id INTEGER NOT NULL,
    empresa_id INTEGER NOT NULL,
    papel_empresa TEXT NOT NULL CHECK (papel_empresa IN ('cliente', 'operador', 'revisor', 'aprovador')),
    PRIMARY KEY (usuario_id, empresa_id),
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
    FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);
CREATE TABLE IF NOT EXISTS audit_acesso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    usuario_id INTEGER,
    empresa_id INTEGER,
    acao TEXT NOT NULL,
    resultado TEXT NOT NULL,
    detalhes TEXT
);
"""

SCHEMA_CONTABIL = """
CREATE TABLE IF NOT EXISTS parametros (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS arquivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    nome_original TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('extrato_ofx', 'extrato_tabular', 'planilha_despesas',
                                       'plano_contas', 'razao', 'retorno_fortes')),
    sha256 TEXT NOT NULL,
    tamanho INTEGER NOT NULL,
    caminho TEXT NOT NULL,
    enviado_por TEXT NOT NULL,
    enviado_em TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'carregado' CHECK (status IN ('carregado', 'recusado', 'substituido'))
);
CREATE INDEX IF NOT EXISTS ix_arquivos_sha ON arquivos(sha256);

CREATE TABLE IF NOT EXISTS plano_contas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    versao INTEGER NOT NULL,
    classificacao TEXT NOT NULL,
    descricao TEXT NOT NULL,
    reduzido TEXT,
    aceita_lancamento INTEGER NOT NULL CHECK (aceita_lancamento IN (0, 1)),
    natureza TEXT,
    vigente INTEGER NOT NULL DEFAULT 1,
    arquivo_id INTEGER REFERENCES arquivos(id)
);
CREATE INDEX IF NOT EXISTS ix_plano_reduzido ON plano_contas(vigente, reduzido);

CREATE TABLE IF NOT EXISTS regras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prioridade INTEGER NOT NULL DEFAULT 100,
    nome TEXT NOT NULL,
    tipo_padrao TEXT NOT NULL CHECK (tipo_padrao IN ('contem', 'regex', 'igual')),
    padrao TEXT NOT NULL,
    sentido TEXT NOT NULL CHECK (sentido IN ('entrada', 'saida', 'ambos')),
    valor_min_centavos INTEGER,
    valor_max_centavos INTEGER,
    conta_contrapartida TEXT NOT NULL,
    historico TEXT,
    natureza TEXT NOT NULL DEFAULT 'normal'
        CHECK (natureza IN ('normal', 'transferencia', 'tributo', 'socio', 'incerta')),
    ativa INTEGER NOT NULL DEFAULT 1,
    criada_por TEXT NOT NULL,
    criada_em TEXT NOT NULL,
    evidencia TEXT
);

CREATE TABLE IF NOT EXISTS socios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    termo TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS movimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo_id INTEGER NOT NULL REFERENCES arquivos(id),
    linha_origem INTEGER,
    data TEXT NOT NULL,
    valor_centavos INTEGER NOT NULL CHECK (valor_centavos <> 0),
    historico TEXT NOT NULL,
    documento TEXT,
    fitid TEXT,
    conta_banco TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente'
        CHECK (status IN ('pendente', 'proposto', 'classificado', 'em_espera', 'exportado', 'descartado')),
    conta_debito TEXT,
    conta_credito TEXT,
    historico_contabil TEXT,
    regra_id INTEGER REFERENCES regras(id),
    origem_classificacao TEXT CHECK (origem_classificacao IN ('regra', 'manual', 'ia')),
    natureza TEXT NOT NULL DEFAULT 'normal'
        CHECK (natureza IN ('normal', 'transferencia', 'tributo', 'socio', 'incerta')),
    decisao_duplicidade TEXT NOT NULL DEFAULT 'nao_aplica'
        CHECK (decisao_duplicidade IN ('nao_aplica', 'pendente', 'manter', 'descartar')),
    duplicidade_de INTEGER REFERENCES movimentos(id),
    motivo_duplicidade TEXT,
    exige_segunda_confirmacao INTEGER NOT NULL DEFAULT 0,
    motivos_risco TEXT,
    revisado_por TEXT,
    revisado_em TEXT,
    segunda_confirmacao_por TEXT,
    segunda_confirmacao_em TEXT,
    observacao TEXT,
    lote_id INTEGER REFERENCES lotes(id),
    marca TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_mov_data ON movimentos(data);
CREATE INDEX IF NOT EXISTS ix_mov_fitid ON movimentos(conta_banco, fitid);
CREATE INDEX IF NOT EXISTS ix_mov_status ON movimentos(status);

CREATE TABLE IF NOT EXISTS despesas_planilha (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo_id INTEGER NOT NULL REFERENCES arquivos(id),
    linha_origem INTEGER,
    data TEXT NOT NULL,
    valor_centavos INTEGER NOT NULL,
    descricao TEXT NOT NULL,
    lancamento_bancario TEXT
);

CREATE TABLE IF NOT EXISTS razao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo_id INTEGER NOT NULL REFERENCES arquivos(id),
    data TEXT NOT NULL,
    conta TEXT NOT NULL,
    debito_centavos INTEGER NOT NULL DEFAULT 0,
    credito_centavos INTEGER NOT NULL DEFAULT 0,
    historico TEXT
);
CREATE INDEX IF NOT EXISTS ix_razao_conta ON razao(conta, data);

CREATE TABLE IF NOT EXISTS saldos_extrato (
    periodo TEXT NOT NULL,
    conta_banco TEXT NOT NULL,
    saldo_inicial_centavos INTEGER NOT NULL,
    saldo_final_centavos INTEGER NOT NULL,
    informado_por TEXT NOT NULL,
    informado_em TEXT NOT NULL,
    PRIMARY KEY (periodo, conta_banco)
);

CREATE TABLE IF NOT EXISTS conciliacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    periodo TEXT NOT NULL,
    conta_banco TEXT NOT NULL,
    saldo_inicial_extrato INTEGER NOT NULL,
    movimentacao_extrato INTEGER NOT NULL,
    saldo_final_extrato INTEGER NOT NULL,
    saldo_final_contabil INTEGER NOT NULL,
    diferenca_centavos INTEGER NOT NULL,
    justificativa TEXT,
    justificado_por TEXT,
    segunda_revisao_por TEXT,
    status TEXT NOT NULL CHECK (status IN ('aberta', 'divergente', 'justificada', 'concluida')),
    atualizado_em TEXT NOT NULL,
    UNIQUE (periodo, conta_banco)
);

CREATE TABLE IF NOT EXISTS lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    periodo TEXT NOT NULL,
    conta_banco TEXT NOT NULL,
    caminho TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    quantidade INTEGER NOT NULL,
    total_centavos INTEGER NOT NULL,
    gerado_por TEXT NOT NULL,
    gerado_em TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'gerado' CHECK (status IN ('gerado', 'aceito', 'rejeitado')),
    retorno_por TEXT,
    retorno_em TEXT,
    retorno_obs TEXT
);

CREATE TABLE IF NOT EXISTS travas_periodo (
    periodo TEXT NOT NULL,
    conta_banco TEXT NOT NULL,
    usuario TEXT NOT NULL,
    desde TEXT NOT NULL,
    PRIMARY KEY (periodo, conta_banco)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    usuario TEXT NOT NULL,
    acao TEXT NOT NULL,
    entidade TEXT NOT NULL,
    entidade_id TEXT,
    detalhes TEXT
);
"""

SUBPASTAS = ("originais", "exportacoes", "relatorios")


def agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def validar_slug(slug: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", slug or ""):
        raise ValueError("slug deve ter de 2 a 41 caracteres: letras minúsculas, números, '-' ou '_'")
    return slug


def _conectar(caminho: Path) -> sqlite3.Connection:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=config.BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute(f"PRAGMA busy_timeout = {config.BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA foreign_keys = ON")
    return con


def caminho_central(data_dir: Path | None = None) -> Path:
    return (data_dir or config.DATA_DIR) / "central.db"


def pasta_empresa(slug: str, data_dir: Path | None = None) -> Path:
    return (data_dir or config.DATA_DIR) / "empresas" / validar_slug(slug)


def caminho_contabil(slug: str, data_dir: Path | None = None) -> Path:
    return pasta_empresa(slug, data_dir) / "contabil.db"


def conectar_central(data_dir: Path | None = None) -> sqlite3.Connection:
    con = _conectar(caminho_central(data_dir))
    con.executescript(SCHEMA_CENTRAL)
    return con


def conectar_empresa(slug: str, data_dir: Path | None = None) -> sqlite3.Connection:
    pasta = pasta_empresa(slug, data_dir)
    for sub in SUBPASTAS:
        (pasta / "arquivos" / sub).mkdir(parents=True, exist_ok=True)
    con = _conectar(pasta / "contabil.db")
    con.executescript(SCHEMA_CONTABIL)
    return con


@contextmanager
def transacao(con: sqlite3.Connection):
    """BEGIN IMMEDIATE: pega a trava de escrita antes de ler, evitando decidir sobre estado velho."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    else:
        con.execute("COMMIT")


def parametro(con: sqlite3.Connection, chave: str, padrao: str | None = None) -> str | None:
    linha = con.execute("SELECT valor FROM parametros WHERE chave = ?", (chave,)).fetchone()
    return linha["valor"] if linha else padrao


def definir_parametro(con: sqlite3.Connection, chave: str, valor: str) -> None:
    con.execute(
        "INSERT INTO parametros (chave, valor) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
        (chave, valor),
    )
