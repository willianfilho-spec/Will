from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from motor_contabil import backup
from motor_contabil import BancoDeDados, ConjuntoDeRegras, Motor, PlanoDeContas

EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos"


@pytest.fixture
def dados(tmp_path):
    pasta = tmp_path / "dados"
    (pasta / "empresa_a" / "arquivos").mkdir(parents=True)
    motor = Motor(BancoDeDados(pasta / "empresa_a" / "motor.db"),
                  PlanoDeContas.carregar(EXEMPLOS / "plano_contas.csv"),
                  ConjuntoDeRegras.carregar(EXEMPLOS / "regras.json"))
    motor.importar(EXEMPLOS / "extrato_exemplo.ofx")
    motor.banco.fechar()
    (pasta / "empresa_a" / "arquivos" / "extrato.ofx").write_bytes((EXEMPLOS / "extrato_exemplo.ofx").read_bytes())
    return pasta


def contar(db: Path) -> int:
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0]
    finally:
        con.close()


def test_backup_e_restauracao_preservam_tudo(dados, tmp_path):
    copia = backup.fazer(dados, tmp_path / "bkp")
    assert backup.verificar(copia.pasta) == []
    n = backup.restaurar(copia.pasta, tmp_path / "restaurado")
    assert n == 2
    assert contar(tmp_path / "restaurado" / "empresa_a" / "motor.db") == contar(dados / "empresa_a" / "motor.db")
    assert (tmp_path / "restaurado" / "empresa_a" / "arquivos" / "extrato.ofx").read_bytes() == \
        (dados / "empresa_a" / "arquivos" / "extrato.ofx").read_bytes()
    assert backup.testar_restauracao(tmp_path / "bkp")[1] == 2


def test_backup_com_banco_aberto_e_transacao_em_andamento(dados, tmp_path):
    con = sqlite3.connect(dados / "empresa_a" / "motor.db")
    antes = con.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
    con.execute("BEGIN")
    con.execute("INSERT INTO eventos (quando, usuario, acao) VALUES ('x', 'y', 'nao confirmado')")
    copia = backup.fazer(dados, tmp_path / "bkp")
    con.rollback()
    con.close()
    copiado = sqlite3.connect(copia.pasta / "empresa_a" / "motor.db")
    assert copiado.execute("SELECT COUNT(*) FROM eventos").fetchone()[0] == antes
    copiado.close()


def test_copia_adulterada_e_detectada_e_nao_restaura(dados, tmp_path):
    copia = backup.fazer(dados, tmp_path / "bkp")
    (copia.pasta / "empresa_a" / "arquivos" / "extrato.ofx").write_bytes(b"alterado")
    assert backup.verificar(copia.pasta)
    with pytest.raises(ValueError, match="problemas"):
        backup.restaurar(copia.pasta, tmp_path / "restaurado")


def test_banco_danificado_e_detectado(dados, tmp_path):
    copia = backup.fazer(dados, tmp_path / "bkp")
    db = copia.pasta / "empresa_a" / "motor.db"
    conteudo = bytearray(db.read_bytes())
    tamanho_pagina = int.from_bytes(conteudo[16:18], "big")
    conteudo[tamanho_pagina:tamanho_pagina * 3] = b"\xff" * (tamanho_pagina * 2)  # estraga páginas de dados
    db.write_bytes(bytes(conteudo))
    manifesto = json.loads((copia.pasta / "manifesto.json").read_text())
    for item in manifesto["arquivos"]:  # mesmo com o manifesto "acertado" para o arquivo estragado
        if item["sqlite"]:
            item["sha256"], item["tamanho"] = backup._hash(db), db.stat().st_size
    (copia.pasta / "manifesto.json").write_text(json.dumps(manifesto))
    assert any("banco danificado" in p for p in backup.verificar(copia.pasta))


def test_restaurar_nunca_sobrescreve(dados, tmp_path):
    copia = backup.fazer(dados, tmp_path / "bkp")
    with pytest.raises(ValueError, match="não está vazia"):
        backup.restaurar(copia.pasta, dados)


def test_destino_dentro_dos_dados_e_recusado(dados):
    with pytest.raises(ValueError, match="dentro da pasta de dados"):
        backup.fazer(dados, dados / "bkp")


def test_copia_interrompida_nao_conta(dados, tmp_path, monkeypatch):
    destino = tmp_path / "bkp"
    monkeypatch.setattr(backup, "verificar", lambda pasta: ["falha simulada"])
    with pytest.raises(ValueError, match="falha simulada"):
        backup.fazer(dados, destino)
    assert backup.listar(destino) == [] and list(destino.iterdir()) == []


def test_retencao_30_diarias_e_12_mensais(dados, tmp_path):
    destino = tmp_path / "bkp"
    inicio = datetime(2025, 1, 1, 22, 0, 0)
    for dia in range(500):  # quase um ano e meio de cópias, duas por dia
        for hora in (0, 1):
            momento = inicio + timedelta(days=dia, hours=hora)
            pasta = destino / momento.strftime("backup_%Y%m%d_%H%M%S")
            pasta.mkdir(parents=True)
            (pasta / "manifesto.json").write_text('{"arquivos": []}')
    backup.aplicar_retencao(destino)
    restantes = backup.listar(destino)
    dias = {c.quando.date() for c in restantes}
    meses = {c.quando.strftime("%Y-%m") for c in restantes}
    ultimo = inicio + timedelta(days=499, hours=1)
    assert restantes[-1].quando == ultimo
    assert len({d for d in dias if d > (ultimo - timedelta(days=30)).date()}) == 30
    assert len(meses) >= 12
    assert len(restantes) <= 30 + 12
    assert all(c.quando.hour == 23 for c in restantes)  # fica a última de cada dia


def test_situacao_avisa_copia_atrasada(dados, tmp_path):
    destino = tmp_path / "bkp"
    assert backup.main(["situacao", "--destino", str(destino)]) == 1
    backup.fazer(dados, destino, agora=datetime.now() - timedelta(hours=30))
    assert backup.main(["situacao", "--destino", str(destino)]) == 1
    backup.fazer(dados, destino)
    assert backup.main(["situacao", "--destino", str(destino)]) == 0


def test_segundos_ate_o_proximo_horario():
    from datetime import datetime

    from motor_contabil.backup import segundos_ate

    assert segundos_ate("21:00", datetime(2026, 11, 22, 20, 0)) == 3600
    assert segundos_ate("21:00", datetime(2026, 11, 22, 21, 0)) == 24 * 3600
    assert segundos_ate("03:30", datetime(2026, 11, 22, 21, 0)) == 6.5 * 3600
