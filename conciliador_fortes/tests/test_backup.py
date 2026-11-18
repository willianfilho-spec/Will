import sqlite3

import pytest

from domain import operacoes as o
from storage.backup import criar_backup, restaurar_backup, verificar_backup
from tests.conftest import EXEMPLOS


def test_backup_e_restauracao(ambiente, empresa_pronta, tmp_path):
    op, _ = empresa_pronta
    o.carregar_extrato(op, "set.ofx", (EXEMPLOS / "extrato_exemplo.ofx").read_bytes(), "362")
    pasta = criar_backup(ambiente["data"], tmp_path / "bk")
    assert verificar_backup(pasta) == []
    destino = tmp_path / "restaurado"
    restaurar_backup(pasta, destino)
    con = sqlite3.connect(destino / "empresas" / "alfa" / "contabil.db")
    assert con.execute("SELECT COUNT(*) FROM movimentos").fetchone()[0] == 6
    arq = con.execute("SELECT caminho FROM arquivos WHERE tipo = 'extrato_ofx'").fetchone()[0]
    assert (destino / "empresas" / "alfa" / arq).read_bytes() == (EXEMPLOS / "extrato_exemplo.ofx").read_bytes()
    con.close()
    with pytest.raises(ValueError, match="não está vazio"):
        restaurar_backup(pasta, destino)


def test_backup_corrompido_e_detectado(ambiente, empresa_pronta, tmp_path):
    pasta = criar_backup(ambiente["data"], tmp_path / "bk")
    db = pasta / "empresas" / "alfa" / "contabil.db"
    db.chmod(0o644)
    with open(db, "r+b") as f:
        f.seek(200)
        f.write(b"\xff" * 64)
    assert verificar_backup(pasta)
    with pytest.raises(ValueError, match="backup com problema"):
        restaurar_backup(pasta, tmp_path / "novo")
