"""Testes automatizados ligados à P-004. Não substituem os testes na instalação real do Fortes."""

import json
import sqlite3

import pytest

from domain import homologacao as h
from domain import operacoes as o
from exporters import fortes_exporter
from exporters.fortes_exporter import LoteBloqueado
from storage.restauracao import executar
from tests.conftest import EXEMPLOS
from tests.test_fluxo import SALDO_ABERTURA, classificar_tudo, movs, preparar_setembro

HIST_LONGO = "PAGAMENTO A FORNECEDOR REFERENTE A NOTA FISCAL 123456 SERIE 1 PARCELA 3 DE 12 CONTRATO DE PRESTACAO DE SERVICOS DE MANUTENCAO PREDIAL"


def pronto_para_lote(op, rev, historico_socio=None):
    preparar_setembro(op, rev)
    _, socio = classificar_tudo(op, rev)
    if historico_socio:
        o.classificar(op, socio["id"], "90", historico_socio, natureza="socio")
    o.segunda_confirmacao(rev, socio["id"])
    o.conferir(op, "2026-09", "362")
    return socio


def admin(ambiente):
    c = ambiente["central"]
    if not c.execute("SELECT 1 FROM usuarios WHERE email = 'adm@exemplo.test'").fetchone():
        from storage import usuarios
        usuarios.criar_usuario(c, "Admin Z", "adm@exemplo.test", "senha-forte-9", "admin")
    return c.execute("SELECT * FROM usuarios WHERE email = 'adm@exemplo.test'").fetchone()


# ------------------------------------------------------------------ histórico (H2)

def test_aut_hist_01_limite_configuravel_e_faixa(empresa_pronta):
    op, _ = empresa_pronta
    assert o.limite_historico(op.con) == 118
    o.definir_limite_historico(op, 90)
    assert o.limite_historico(op.con) == 90
    for ruim in (39, 251, "100", 99.5):
        with pytest.raises(ValueError):
            o.definir_limite_historico(op, ruim)
    assert [r["acao"] for r in op.con.execute("SELECT acao FROM audit_log WHERE acao = 'limite_historico_definido'")]


def test_aut_hist_02_historico_completo_preservado(empresa_pronta):
    op, rev = empresa_pronta
    o.definir_limite_historico(op, 60)
    socio = pronto_para_lote(op, rev, HIST_LONGO)
    lote = o.gerar_lote(rev, "2026-09", "362")
    assert lote["limite_historico"] == 60 and lote["truncados"] >= 1
    item = next(i for i in o.itens_lote(op.con, lote["lote_id"]) if i["movimento_id"] == socio["id"])
    assert item["historico_completo"] == HIST_LONGO  # texto inteiro guardado
    assert item["truncado"] == 1 and len(item["historico_exportado"]) <= 60
    assert item["historico_exportado"].endswith(item["marca"])  # a marca nunca é cortada
    assert movs(op, id=socio["id"])[0]["historico_contabil"] == HIST_LONGO
    for linha in lote["arquivo"].read_bytes().decode("ascii").split("\r\n")[:-1]:
        assert len(linha.split(";")[4]) <= 60


def test_aut_hist_03_mudar_limite_nao_altera_lote_gerado(empresa_pronta):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev, HIST_LONGO)
    lote = o.gerar_lote(rev, "2026-09", "362")
    antes = lote["arquivo"].read_bytes()
    o.definir_limite_historico(op, 50)
    assert o.arquivo_lote(op, lote["lote_id"]) == antes
    assert op.con.execute("SELECT limite_historico FROM lotes WHERE id = ?", (lote["lote_id"],)).fetchone()[0] == 118


# ------------------------------------------------------------------ duplicidade

def test_aut_dup_01_marca_ja_no_razao_bloqueia(empresa_pronta):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev)
    tarifa = movs(op, historico="TARIFA PACOTE SERVICOS")[0]
    mk = fortes_exporter.marca("ALF", tarifa["data"], tarifa["id"])
    # alguém importou essa linha no Fortes por fora do app
    o.carregar_razao(op, "razao_com_marca.csv",
                     SALDO_ABERTURA + f"02/09/2026;333;362;45,90;TARIFA {mk};;;;\r\n".encode())
    o.conferir(op, "2026-09", "362")
    with pytest.raises(LoteBloqueado, match="já está no Razão"):
        o.gerar_lote(rev, "2026-09", "362")


def test_aut_dup_02_igual_a_lote_aceito_sem_decisao_bloqueia(empresa_pronta):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev)
    lote = o.gerar_lote(rev, "2026-09", "362")
    o.registrar_retorno(op, lote["lote_id"], True, "ok")
    # cópia exata gravada direto no banco, simulando falha da deduplicação
    tarifa = movs(op, historico="TARIFA PACOTE SERVICOS")[0]
    op.con.execute(
        "INSERT INTO movimentos (arquivo_id, data, valor_centavos, historico, conta_banco, status, conta_debito, "
        "conta_credito, revisado_por, revisado_em) VALUES (?, ?, ?, ?, '362', 'classificado', '333', '362', 'X', 'x')",
        (tarifa["arquivo_id"], tarifa["data"], tarifa["valor_centavos"], tarifa["historico"]))
    with pytest.raises(LoteBloqueado, match="igual ao movimento"):
        o.gerar_lote(rev, "2026-09", "362")


def importar_no_razao(op, rev, lote, extra=b"", trocar=None):
    o.registrar_retorno(op, lote["lote_id"], True, "importado no Fortes de teste")
    conteudo = lote["arquivo"].read_bytes()
    if trocar:
        conteudo = conteudo.replace(*trocar)
    o.carregar_razao(op, "razao_pos_import.csv", SALDO_ABERTURA + conteudo + extra)
    return o.conferir_lote_no_razao(op, lote["lote_id"])


def test_aut_dup_03_conferencia_pos_importacao_aprova(empresa_pronta):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev)
    lote = o.gerar_lote(rev, "2026-09", "362")
    with pytest.raises(o.OperacaoInvalida, match="retorno"):
        o.conferir_lote_no_razao(op, lote["lote_id"])
    r = importar_no_razao(op, rev, lote)
    assert r["aprovado"] and r["encontrados"] == 6


@pytest.mark.parametrize("modo, chave", [("ausente", "ausentes"), ("duplicado", "duplicados"),
                                         ("valor", "divergentes"), ("conta", "divergentes")])
def test_aut_dup_03_conferencia_pos_importacao_detecta(empresa_pronta, modo, chave):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev)
    lote = o.gerar_lote(rev, "2026-09", "362")
    linhas = lote["arquivo"].read_bytes().split(b"\r\n")
    if modo == "ausente":
        r = importar_no_razao(op, rev, lote, trocar=(linhas[0] + b"\r\n", b""))
    elif modo == "duplicado":
        r = importar_no_razao(op, rev, lote, extra=linhas[0] + b"\r\n")
    elif modo == "valor":
        r = importar_no_razao(op, rev, lote, trocar=(b";45,90;", b";45,99;"))
    else:
        r = importar_no_razao(op, rev, lote, trocar=(b";333;362;", b";259;362;"))
    assert not r["aprovado"] and r[chave]


# ------------------------------------------------------------------ alteração indevida e perda

@pytest.mark.parametrize("sql, trecho", [
    ("UPDATE movimentos SET valor_centavos = 1 WHERE id = 1", "origem"),
    ("UPDATE movimentos SET historico = 'X' WHERE id = 1", "origem"),
    ("DELETE FROM movimentos WHERE id = 1", "apagado"),
    ("UPDATE audit_log SET usuario = 'X'", "auditoria"),
    ("DELETE FROM audit_log", "auditoria"),
    ("DELETE FROM arquivos", "apagado"),
    ("UPDATE arquivos SET sha256 = 'x'", "alterado"),
])
def test_aut_int_01_travas_do_banco(empresa_pronta, sql, trecho):
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    with pytest.raises(sqlite3.IntegrityError, match=trecho):
        op.con.execute(sql)


def test_aut_int_01b_exportado_e_aceito_congelados(empresa_pronta):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev)
    lote = o.gerar_lote(rev, "2026-09", "362")
    with pytest.raises(sqlite3.IntegrityError, match="exportado"):
        op.con.execute("UPDATE movimentos SET conta_debito = '259' WHERE status = 'exportado'")
    with pytest.raises(sqlite3.IntegrityError, match="lote"):
        op.con.execute("UPDATE lotes SET total_centavos = 1")
    with pytest.raises(sqlite3.IntegrityError, match="item de lote"):
        op.con.execute("UPDATE lote_itens SET linha_exportada = 'x'")
    o.registrar_retorno(op, lote["lote_id"], True, "ok")
    with pytest.raises(sqlite3.IntegrityError, match="aceito"):
        op.con.execute("UPDATE movimentos SET status = 'classificado', lote_id = NULL WHERE lote_id IS NOT NULL")
    with pytest.raises(sqlite3.IntegrityError, match="lote gerado"):
        op.con.execute("UPDATE lotes SET status = 'rejeitado'")


def test_aut_int_02_arquivo_adulterado(empresa_pronta):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev)
    lote = o.gerar_lote(rev, "2026-09", "362")
    assert o.verificar_integridade(op) == []
    lote["arquivo"].chmod(0o644)
    lote["arquivo"].write_bytes(lote["arquivo"].read_bytes().replace(b"45,90", b"45,99"))
    with pytest.raises(o.OperacaoInvalida, match="alterado"):
        o.arquivo_lote(op, lote["lote_id"])
    original = op.pasta / op.con.execute("SELECT caminho FROM arquivos WHERE tipo = 'extrato_ofx'").fetchone()[0]
    original.chmod(0o644)
    original.write_bytes(b"<OFX></OFX>")
    problemas = o.verificar_integridade(op)
    assert any("lote" in p for p in problemas) and any("original" in p for p in problemas)


def test_aut_int_03_ida_e_volta_detecta_diferenca(empresa_pronta):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev)
    ms = o.movimentos_para_lote(op.con, "2026-09", "362")
    geradas = fortes_exporter.gerar_linhas(ms, o.plano_vigente(op.con), "ALF")
    bom = fortes_exporter.conteudo_arquivo(geradas)
    assert fortes_exporter.conferir_ida_e_volta(bom, ms, geradas) == []
    assert fortes_exporter.conferir_ida_e_volta(bom.replace(b";45,90;", b";45,91;"), ms, geradas)
    assert fortes_exporter.conferir_ida_e_volta(bom.split(b"\r\n", 1)[1], ms, geradas)
    assert fortes_exporter.conferir_ida_e_volta(bom.replace(b"\r\n", b"\n"), ms, geradas)


# ------------------------------------------------------------------ Razão (H3)

def test_aut_raz_01_conferencia_provisoria_sem_homologacao(ambiente, empresa_pronta):
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    o.conferir(op, "2026-09", "362")
    c = o.conciliacao(op.con, "2026-09", "362")
    assert c["razao_homologado"] == 0 and c["formato_razao"] == "fortes_importacao"
    h.registrar(ambiente["central"], admin(ambiente), "H3", "aprovado", "Razão real exportado e carregado",
                "saldo do banco igual ao do Fortes em 30/09", evidencia_nome="razao.png", evidencia=b"png",
                referencia="fortes_importacao", data_dir=ambiente["data"])
    o.conferir(op, "2026-09", "362")
    assert o.conciliacao(op.con, "2026-09", "362")["razao_homologado"] == 1


# ------------------------------------------------------------------ registro de homologação

def test_aut_hom_01_h1_exige_lote_aceito_e_conferido(ambiente, empresa_pronta):
    op, rev = empresa_pronta
    adm, central = admin(ambiente), ambiente["central"]
    kw = dict(teste="importação do lote no Fortes de teste", resultado="importado sem erro, razão conferido",
              evidencia_nome="tela.png", evidencia=b"img", data_dir=ambiente["data"])
    pronto_para_lote(op, rev)
    lote = o.gerar_lote(rev, "2026-09", "362")
    with pytest.raises(h.HomologacaoInvalida, match="retorno"):
        h.registrar(central, adm, "H1", "aprovado", referencia=f"alfa:{lote['lote_id']}", **kw)
    o.registrar_retorno(op, lote["lote_id"], True, "ok")
    with pytest.raises(h.HomologacaoInvalida, match="conferência"):
        h.registrar(central, adm, "H1", "aprovado", referencia=f"alfa:{lote['lote_id']}", **kw)
    o.carregar_razao(op, "r.csv", SALDO_ABERTURA + lote["arquivo"].read_bytes())
    assert o.conferir_lote_no_razao(op, lote["lote_id"])["aprovado"]
    with pytest.raises(h.HomologacaoInvalida, match="evidência"):
        h.registrar(central, adm, "H1", "aprovado", referencia=f"alfa:{lote['lote_id']}",
                    **{**kw, "evidencia": None})
    h.registrar(central, adm, "H1", "aprovado", referencia=f"alfa:{lote['lote_id']}", **kw)
    assert h.aprovado(central, "H1") and not h.integracao_liberada(central)
    assert h.evidencia_integra(h.estado(central)["H1"]) is True


def test_aut_hom_01b_regras_gerais(ambiente, empresa_pronta):
    op, _ = empresa_pronta
    central = ambiente["central"]
    with pytest.raises(h.HomologacaoInvalida, match="administrador"):
        h.registrar(central, op.usuario, "H2", "em_teste", "teste qualquer aqui", "resultado qualquer")
    adm = admin(ambiente)
    with pytest.raises(h.HomologacaoInvalida, match="ação corretiva"):
        h.registrar(central, adm, "H2", "reprovado", "importação com 123 caracteres", "Fortes cortou a marca")
    h.registrar(central, adm, "H2", "reprovado", "importação com 123 caracteres", "Fortes cortou a marca",
                falha="marca truncada", acao_corretiva="baixar o limite para 100", data_dir=ambiente["data"])
    h.registrar(central, adm, "H2", "aprovado", "importação com 100 caracteres", "histórico inteiro no Razão",
                evidencia_nome="r.pdf", evidencia=b"pdf", referencia="100", data_dir=ambiente["data"])
    assert [r["status"] for r in h.historico(central)] == ["reprovado", "aprovado"]  # nada é sobrescrito
    with pytest.raises(sqlite3.IntegrityError):
        central.execute("UPDATE homologacoes SET status = 'aprovado'")
    with pytest.raises(sqlite3.IntegrityError):
        central.execute("DELETE FROM homologacoes")


def test_aut_hom_02_h4_aceita_so_relatorio_real_aprovado(ambiente, empresa_pronta, tmp_path):
    central, adm = ambiente["central"], admin(ambiente)
    r = executar(ambiente["data"])
    assert r["resultado"] == "aprovado"
    assert r["origem_sintetica"] is True  # e-mails .test do ambiente de teste
    with pytest.raises(h.HomologacaoInvalida, match="demonstração"):
        h.registrar(central, adm, "H4", "aprovado", "restauração isolada", "todas as verificações ok",
                    evidencia_nome="r.json", evidencia=json.dumps(r).encode(), data_dir=ambiente["data"])
    falso = {**r, "origem_sintetica": False, "resultado": "reprovado"}
    with pytest.raises(h.HomologacaoInvalida, match="não está aprovado"):
        h.registrar(central, adm, "H4", "aprovado", "restauração isolada", "todas as verificações ok",
                    evidencia_nome="r.json", evidencia=json.dumps(falso).encode(), data_dir=ambiente["data"])


# ------------------------------------------------------------------ backup isolado (H4)

def test_aut_bk_01_restauracao_isolada(ambiente, empresa_pronta):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev)
    o.gerar_lote(rev, "2026-09", "362")
    r = executar(ambiente["data"])
    assert r["resultado"] == "aprovado", r["verificacoes"]
    assert any("SHA-256" in v["teste"] for v in r["verificacoes"])


def test_aut_bk_02_restauracao_detecta_original_corrompido(ambiente, empresa_pronta):
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    f = op.pasta / op.con.execute("SELECT caminho FROM arquivos LIMIT 1").fetchone()[0]
    f.chmod(0o644)
    f.write_bytes(b"corrompido")
    r = executar(ambiente["data"])
    assert r["resultado"] == "reprovado"


def test_aut_int_03b_falha_de_ida_e_volta_bloqueia_lote(empresa_pronta, monkeypatch):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev)
    monkeypatch.setattr(fortes_exporter, "conferir_ida_e_volta", lambda *a: ["valor trocado na linha 1"])
    with pytest.raises(LoteBloqueado, match="ida e volta"):
        o.gerar_lote(rev, "2026-09", "362")
    assert not list((op.pasta / "arquivos" / "exportacoes").iterdir())
    assert not movs(op, status="exportado")


def test_aut_mig_01_banco_antigo_e_migrado_sem_perder_dados(tmp_path):
    """Banco criado antes da P-004 (sem lote_itens, sem colunas novas) abre, migra e mantém os dados."""
    from storage.database import conectar_empresa, pasta_empresa
    pasta = pasta_empresa("antiga", tmp_path)
    pasta.mkdir(parents=True)
    con = sqlite3.connect(pasta / "contabil.db")
    con.executescript("""
        CREATE TABLE lotes (id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT UNIQUE NOT NULL, periodo TEXT NOT NULL,
          conta_banco TEXT NOT NULL, caminho TEXT NOT NULL, sha256 TEXT NOT NULL, quantidade INTEGER NOT NULL,
          total_centavos INTEGER NOT NULL, gerado_por TEXT NOT NULL, gerado_em TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'gerado', retorno_por TEXT, retorno_em TEXT, retorno_obs TEXT);
        CREATE TABLE conciliacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, periodo TEXT NOT NULL, conta_banco TEXT NOT NULL,
          saldo_inicial_extrato INTEGER NOT NULL, movimentacao_extrato INTEGER NOT NULL, saldo_final_extrato INTEGER NOT NULL,
          saldo_final_contabil INTEGER NOT NULL, diferenca_centavos INTEGER NOT NULL, justificativa TEXT,
          justificado_por TEXT, segunda_revisao_por TEXT, status TEXT NOT NULL, atualizado_em TEXT NOT NULL,
          UNIQUE (periodo, conta_banco));
        INSERT INTO lotes (uuid, periodo, conta_banco, caminho, sha256, quantidade, total_centavos, gerado_por, gerado_em)
          VALUES ('u1', '2026-01', '362', 'x', 'abc', 3, 300, 'Ana', 'ontem');
    """)
    con.commit()
    con.close()
    novo = conectar_empresa("antiga", tmp_path)
    colunas = {r["name"] for r in novo.execute("PRAGMA table_info(lotes)")}
    assert {"limite_historico", "truncados", "conferencia_razao"} <= colunas
    assert novo.execute("SELECT quantidade, gerado_por FROM lotes").fetchone()[:] == (3, "Ana")
    assert novo.execute("SELECT COUNT(*) FROM lote_itens").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError, match="lote gerado"):
        novo.execute("UPDATE lotes SET total_centavos = 1")
    novo.close()
