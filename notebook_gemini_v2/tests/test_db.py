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
