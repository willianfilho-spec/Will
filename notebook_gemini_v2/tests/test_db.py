import sqlite3

import pytest

from nb.db import MIGRATIONS, connect, schema_version


def test_cria_schema_na_versao_mais_recente(tmp_path):
    conn = connect(tmp_path / "a.db")
    assert schema_version(conn) == MIGRATIONS[-1][0]
    tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"notebooks", "documents", "pages", "messages"} <= tabelas


def test_migracao_e_idempotente(tmp_path):
    connect(tmp_path / "a.db").close()
    conn = connect(tmp_path / "a.db")  # segunda abertura não deve falhar nem duplicar
    assert schema_version(conn) == MIGRATIONS[-1][0]


def test_dados_persistem_entre_aberturas(tmp_path):
    from nb import repo

    c1 = connect(tmp_path / "a.db")
    nid = repo.create_notebook(c1, "Persistente")
    c1.close()
    c2 = connect(tmp_path / "a.db")
    assert [n["id"] for n in repo.list_notebooks(c2)] == [nid]


def test_chaves_estrangeiras_ativas(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO messages (notebook_id, role, content, created_at) VALUES ('inexistente','user','x','y')"
        )


def test_mensagem_guarda_metadados_de_verificacao(conn, nid):
    from nb import repo

    repo.add_message(conn, nid, "assistant", "resposta", metadata='{"a": 1}')
    repo.add_message(conn, nid, "user", "pergunta")
    rows = repo.list_messages(conn, nid)
    assert [(r["role"], r["metadata"]) for r in rows] == [("user", None), ("assistant", '{"a": 1}')]


V1_SCHEMA = """CREATE TABLE notebooks (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE documents (id TEXT PRIMARY KEY, notebook_id TEXT NOT NULL, name TEXT NOT NULL,
    path TEXT NOT NULL, content TEXT NOT NULL, added_at TEXT NOT NULL);
CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, notebook_id TEXT NOT NULL,
    role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);"""


def test_banco_da_v1_e_guardado_em_copia_e_um_banco_novo_e_criado(tmp_path):
    import sqlite3

    from nb.db import backup_legacy_database

    path = tmp_path / "notebook.db"
    old = sqlite3.connect(path)
    old.executescript(V1_SCHEMA)
    old.execute("INSERT INTO notebooks VALUES ('1', 'Antigo', 'x')")
    old.commit()
    old.close()
    backup = backup_legacy_database(path)
    assert backup and backup.exists() and ".v1-backup-" in backup.name and not path.exists()
    assert sqlite3.connect(backup).execute("SELECT name FROM notebooks").fetchone()[0] == "Antigo"
    conn = connect(path)
    assert schema_version(conn) == MIGRATIONS[-1][0] and conn.execute("SELECT COUNT(*) FROM notebooks").fetchone()[0] == 0


def test_banco_da_v2_e_banco_inexistente_nao_sao_tratados_como_v1(tmp_path):
    from nb.db import backup_legacy_database

    assert backup_legacy_database(tmp_path / "nao_existe.db") is None
    connect(tmp_path / "v2.db").close()
    assert backup_legacy_database(tmp_path / "v2.db") is None and (tmp_path / "v2.db").exists()


def test_abrir_banco_da_v1_direto_sem_o_backup_falha_alto_em_vez_de_corromper(tmp_path):
    import sqlite3

    path = tmp_path / "notebook.db"
    old = sqlite3.connect(path)
    old.executescript(V1_SCHEMA)
    old.close()
    with pytest.raises(sqlite3.OperationalError):
        connect(path)
