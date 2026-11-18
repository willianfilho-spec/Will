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
CREATE TABLE IF NOT EXISTS homologacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('aprovado', 'reprovado', 'em_teste')),
    tipo_teste TEXT NOT NULL CHECK (tipo_teste IN ('automatizado', 'instalacao_real')),
    teste TEXT NOT NULL,
    resultado TEXT NOT NULL,
    falha TEXT,
    acao_corretiva TEXT,
    evidencia_nome TEXT,
    evidencia_sha256 TEXT,
    evidencia_caminho TEXT,
    referencia TEXT,
    registrado_por TEXT NOT NULL,
    registrado_em TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS trg_homologacoes_sem_update BEFORE UPDATE ON homologacoes
BEGIN SELECT RAISE(ABORT, 'registro de homologação não pode ser alterado; registre um novo'); END;
CREATE TRIGGER IF NOT EXISTS trg_homologacoes_sem_delete BEFORE DELETE ON homologacoes
BEGIN SELECT RAISE(ABORT, 'registro de homologação não pode ser apagado'); END;

CREATE TABLE IF NOT EXISTS sessoes (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    csrf TEXT NOT NULL,
    criada_em REAL NOT NULL,
    ultimo_uso REAL NOT NULL,
    expira_em REAL NOT NULL,
    mfa_ok INTEGER NOT NULL DEFAULT 0,
    ip TEXT,
    flash TEXT,
    totp_pendente TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessoes_usuario ON sessoes(usuario_id);
CREATE TABLE IF NOT EXISTS tentativas_login (
    chave TEXT PRIMARY KEY,
    falhas INTEGER NOT NULL DEFAULT 0,
    janela_inicio REAL NOT NULL,
    bloqueado_ate REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS codigos_recuperacao (
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    codigo_hash TEXT NOT NULL,
    usado_em TEXT,
    PRIMARY KEY (usuario_id, codigo_hash)
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
CREATE TRIGGER IF NOT EXISTS trg_audit_acesso_sem_update BEFORE UPDATE ON audit_acesso
BEGIN SELECT RAISE(ABORT, 'auditoria não pode ser alterada'); END;
CREATE TRIGGER IF NOT EXISTS trg_audit_acesso_sem_delete BEFORE DELETE ON audit_acesso
BEGIN SELECT RAISE(ABORT, 'auditoria não pode ser apagada'); END;
"""

MIGRACOES_CENTRAL = {
    "usuarios": {
        "totp_segredo": "TEXT",
        "totp_ativo": "INTEGER NOT NULL DEFAULT 0",
        "totp_ultimo_passo": "INTEGER NOT NULL DEFAULT 0",
        "deve_trocar_senha": "INTEGER NOT NULL DEFAULT 0",
        "senha_alterada_em": "TEXT",
    },
    "audit_acesso": {"hash_anterior": "TEXT", "hash": "TEXT"},
}

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

CREATE TABLE IF NOT EXISTS lote_itens (
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    movimento_id INTEGER NOT NULL REFERENCES movimentos(id),
    marca TEXT NOT NULL,
    linha_exportada TEXT NOT NULL,
    historico_completo TEXT NOT NULL,
    historico_exportado TEXT NOT NULL,
    truncado INTEGER NOT NULL CHECK (truncado IN (0, 1)),
    PRIMARY KEY (lote_id, movimento_id)
);

CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    nome_original TEXT NOT NULL,
    categoria TEXT NOT NULL CHECK (categoria IN ('extrato', 'planilha', 'folha', 'guia', 'recibo', 'contrato',
                                                  'lancamentos', 'razao', 'outro')),
    descricao TEXT,
    sha256 TEXT NOT NULL,
    tamanho INTEGER NOT NULL,
    caminho TEXT NOT NULL,
    origem TEXT NOT NULL CHECK (origem IN ('cliente', 'equipe')),
    enviado_por TEXT NOT NULL,
    usuario_id INTEGER NOT NULL,
    enviado_em TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'recebido' CHECK (status IN ('recebido', 'processado', 'recusado')),
    observacao TEXT
);
CREATE INDEX IF NOT EXISTS ix_documentos_sha ON documentos(sha256);

CREATE TABLE IF NOT EXISTS lancamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL CHECK (tipo IN ('ajuste', 'provisao', 'reclassificacao', 'transposicao', 'outro')),
    data TEXT NOT NULL,
    conta_debito TEXT NOT NULL,
    conta_credito TEXT NOT NULL,
    valor_centavos INTEGER NOT NULL CHECK (valor_centavos > 0),
    historico TEXT NOT NULL,
    ref_externa TEXT,
    documento_id INTEGER REFERENCES documentos(id),
    status TEXT NOT NULL DEFAULT 'aguardando_confirmacao'
        CHECK (status IN ('aguardando_confirmacao', 'confirmado', 'exportado', 'descartado')),
    criado_por TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    confirmado_por TEXT,
    confirmado_em TEXT,
    observacao TEXT,
    lote_id INTEGER REFERENCES lotes(id),
    marca TEXT UNIQUE,
    CHECK (conta_debito <> conta_credito)
);
CREATE INDEX IF NOT EXISTS ix_lanc_data ON lancamentos(data);

CREATE TABLE IF NOT EXISTS lote_itens_lanc (
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    lancamento_id INTEGER NOT NULL REFERENCES lancamentos(id),
    marca TEXT NOT NULL,
    linha_exportada TEXT NOT NULL,
    historico_completo TEXT NOT NULL,
    historico_exportado TEXT NOT NULL,
    truncado INTEGER NOT NULL CHECK (truncado IN (0, 1)),
    PRIMARY KEY (lote_id, lancamento_id)
);

CREATE TABLE IF NOT EXISTS solicitacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movimento_id INTEGER REFERENCES movimentos(id),
    mensagem TEXT NOT NULL,
    criada_por TEXT NOT NULL,
    criada_em TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta', 'respondida', 'encerrada')),
    resposta TEXT,
    respondida_por TEXT,
    respondida_em TEXT,
    documento_id INTEGER REFERENCES documentos(id),
    encerrada_por TEXT,
    encerrada_em TEXT
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

-- Proteções contra alteração indevida e perda de informação ------------------
CREATE TRIGGER IF NOT EXISTS trg_audit_sem_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'auditoria não pode ser alterada'); END;
CREATE TRIGGER IF NOT EXISTS trg_audit_sem_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'auditoria não pode ser apagada'); END;

-- o que veio do extrato nunca muda
CREATE TRIGGER IF NOT EXISTS trg_mov_origem_imutavel BEFORE UPDATE ON movimentos
WHEN NEW.data IS NOT OLD.data OR NEW.valor_centavos IS NOT OLD.valor_centavos
  OR NEW.historico IS NOT OLD.historico OR NEW.fitid IS NOT OLD.fitid
  OR NEW.documento IS NOT OLD.documento OR NEW.arquivo_id IS NOT OLD.arquivo_id
  OR NEW.conta_banco IS NOT OLD.conta_banco
BEGIN SELECT RAISE(ABORT, 'dados de origem do extrato não podem ser alterados'); END;

-- movimento exportado fica congelado até o retorno do Fortes
CREATE TRIGGER IF NOT EXISTS trg_mov_exportado_imutavel BEFORE UPDATE ON movimentos
WHEN OLD.status = 'exportado' AND (
     NEW.conta_debito IS NOT OLD.conta_debito OR NEW.conta_credito IS NOT OLD.conta_credito
  OR NEW.historico_contabil IS NOT OLD.historico_contabil OR NEW.natureza IS NOT OLD.natureza
  OR NEW.revisado_por IS NOT OLD.revisado_por OR NEW.segunda_confirmacao_por IS NOT OLD.segunda_confirmacao_por
  OR (NEW.status <> 'classificado' AND NEW.status <> OLD.status))
BEGIN SELECT RAISE(ABORT, 'movimento exportado não pode ser alterado'); END;

-- movimento de lote aceito pelo Fortes não volta atrás
CREATE TRIGGER IF NOT EXISTS trg_mov_aceito_imutavel BEFORE UPDATE ON movimentos
WHEN OLD.lote_id IS NOT NULL AND (SELECT status FROM lotes WHERE id = OLD.lote_id) = 'aceito'
BEGIN SELECT RAISE(ABORT, 'movimento de lote aceito no Fortes não pode ser alterado'); END;

CREATE TRIGGER IF NOT EXISTS trg_mov_sem_delete BEFORE DELETE ON movimentos
BEGIN SELECT RAISE(ABORT, 'movimento não pode ser apagado; use descartar'); END;

CREATE TRIGGER IF NOT EXISTS trg_arquivos_imutavel BEFORE UPDATE ON arquivos
WHEN NEW.sha256 IS NOT OLD.sha256 OR NEW.caminho IS NOT OLD.caminho OR NEW.tamanho IS NOT OLD.tamanho
BEGIN SELECT RAISE(ABORT, 'registro do arquivo original não pode ser alterado'); END;
CREATE TRIGGER IF NOT EXISTS trg_arquivos_sem_delete BEFORE DELETE ON arquivos
BEGIN SELECT RAISE(ABORT, 'arquivo original não pode ser apagado'); END;

CREATE TRIGGER IF NOT EXISTS trg_lotes_imutavel BEFORE UPDATE ON lotes
WHEN NEW.sha256 IS NOT OLD.sha256 OR NEW.caminho IS NOT OLD.caminho OR NEW.quantidade IS NOT OLD.quantidade
  OR NEW.total_centavos IS NOT OLD.total_centavos OR NEW.gerado_por IS NOT OLD.gerado_por
  OR (OLD.status <> 'gerado' AND NEW.status IS NOT OLD.status)
BEGIN SELECT RAISE(ABORT, 'lote gerado não pode ser alterado'); END;
CREATE TRIGGER IF NOT EXISTS trg_lotes_sem_delete BEFORE DELETE ON lotes
BEGIN SELECT RAISE(ABORT, 'lote não pode ser apagado'); END;
CREATE TRIGGER IF NOT EXISTS trg_documentos_imutavel BEFORE UPDATE ON documentos
WHEN NEW.sha256 IS NOT OLD.sha256 OR NEW.caminho IS NOT OLD.caminho OR NEW.tamanho IS NOT OLD.tamanho
  OR NEW.usuario_id IS NOT OLD.usuario_id OR NEW.enviado_por IS NOT OLD.enviado_por
BEGIN SELECT RAISE(ABORT, 'documento enviado não pode ser alterado'); END;
CREATE TRIGGER IF NOT EXISTS trg_documentos_sem_delete BEFORE DELETE ON documentos
BEGIN SELECT RAISE(ABORT, 'documento não pode ser apagado'); END;

CREATE TRIGGER IF NOT EXISTS trg_lanc_origem_imutavel BEFORE UPDATE ON lancamentos
WHEN NEW.data IS NOT OLD.data OR NEW.conta_debito IS NOT OLD.conta_debito OR NEW.conta_credito IS NOT OLD.conta_credito
  OR NEW.valor_centavos IS NOT OLD.valor_centavos OR NEW.historico IS NOT OLD.historico
  OR NEW.criado_por IS NOT OLD.criado_por OR NEW.tipo IS NOT OLD.tipo
BEGIN SELECT RAISE(ABORT, 'lançamento manual não pode ser editado; descarte e crie outro'); END;
CREATE TRIGGER IF NOT EXISTS trg_lanc_exportado_imutavel BEFORE UPDATE ON lancamentos
WHEN OLD.status = 'exportado' AND NOT (NEW.status = 'exportado'
     OR (NEW.status = 'confirmado' AND NEW.lote_id IS NULL AND NEW.marca IS NULL))
BEGIN SELECT RAISE(ABORT, 'lançamento exportado não pode ser alterado'); END;
CREATE TRIGGER IF NOT EXISTS trg_lanc_aceito_imutavel BEFORE UPDATE ON lancamentos
WHEN OLD.lote_id IS NOT NULL AND (SELECT status FROM lotes WHERE id = OLD.lote_id) = 'aceito'
BEGIN SELECT RAISE(ABORT, 'lançamento de lote aceito no Fortes não pode ser alterado'); END;
CREATE TRIGGER IF NOT EXISTS trg_lanc_sem_delete BEFORE DELETE ON lancamentos
BEGIN SELECT RAISE(ABORT, 'lançamento não pode ser apagado; use descartar'); END;
CREATE TRIGGER IF NOT EXISTS trg_lote_itens_lanc_sem_update BEFORE UPDATE ON lote_itens_lanc
BEGIN SELECT RAISE(ABORT, 'item de lote não pode ser alterado'); END;
CREATE TRIGGER IF NOT EXISTS trg_lote_itens_lanc_sem_delete BEFORE DELETE ON lote_itens_lanc
BEGIN SELECT RAISE(ABORT, 'item de lote não pode ser apagado'); END;

CREATE TRIGGER IF NOT EXISTS trg_lote_itens_sem_update BEFORE UPDATE ON lote_itens
BEGIN SELECT RAISE(ABORT, 'item de lote não pode ser alterado'); END;
CREATE TRIGGER IF NOT EXISTS trg_lote_itens_sem_delete BEFORE DELETE ON lote_itens
BEGIN SELECT RAISE(ABORT, 'item de lote não pode ser apagado'); END;
"""

# Colunas acrescentadas depois da primeira versão (bancos antigos são migrados ao abrir).
MIGRACOES_CONTABIL = {
    "lotes": {
        "limite_historico": "INTEGER",
        "truncados": "INTEGER NOT NULL DEFAULT 0",
        "conferencia_razao": "TEXT",
        "conferido_por": "TEXT",
        "conferido_em": "TEXT",
    },
    "audit_log": {"hash_anterior": "TEXT", "hash": "TEXT"},
    "conciliacoes": {
        "razao_homologado": "INTEGER NOT NULL DEFAULT 0",
        "formato_razao": "TEXT",
    },
}

SUBPASTAS = ("originais", "exportacoes", "relatorios")


def agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def validar_slug(slug: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", slug or ""):
        raise ValueError("slug deve ter de 2 a 41 caracteres: letras minúsculas, números, '-' ou '_'")
    return slug


def _conectar(caminho: Path) -> sqlite3.Connection:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=config.BUSY_TIMEOUT_MS / 1000, isolation_level=None, check_same_thread=False)
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
    _migrar(con, MIGRACOES_CENTRAL)
    return con


def conectar_empresa(slug: str, data_dir: Path | None = None) -> sqlite3.Connection:
    pasta = pasta_empresa(slug, data_dir)
    for sub in SUBPASTAS:
        (pasta / "arquivos" / sub).mkdir(parents=True, exist_ok=True)
    con = _conectar(pasta / "contabil.db")
    con.executescript(SCHEMA_CONTABIL)
    _migrar(con, MIGRACOES_CONTABIL)
    return con


def _migrar(con: sqlite3.Connection, migracoes: dict) -> None:
    for tabela, colunas in migracoes.items():
        existentes = {r["name"] for r in con.execute(f"PRAGMA table_info({tabela})")}
        for nome, tipo in colunas.items():
            if nome not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")


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
