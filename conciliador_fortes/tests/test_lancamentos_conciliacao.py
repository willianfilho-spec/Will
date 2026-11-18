import sqlite3

import pytest

from domain import conciliacao_razao as cr
from domain import documentos as doc
from domain import lancamentos as lanc
from domain import operacoes as o
from exporters.fortes_exporter import LoteBloqueado, marca_lancamento
from parsers.comum import ErroEstrutural
from storage import audit
from storage.usuarios import AcessoNegado
from tests.conftest import EXEMPLOS
from tests.test_fluxo import SALDO_ABERTURA, classificar_tudo, movs, preparar_setembro
from tests.test_homologacao import pronto_para_lote

AJUSTE = (b"17/09/2026;259;57;191,79;RECLASSIFICA MULTA DE MORA DARF PAGO [MUL-00311];;;;\r\n"
          b"18/09/2026;57;258;870,95;RECLASSIFICA JUROS [JUR-01403];;;;\r\n")


@pytest.fixture
def plano_ampliado(empresa_pronta):
    op, rev = empresa_pronta
    b = (EXEMPLOS / "plano_contas_fortes.csv").read_bytes() + b'"3.01.01.07.01.0043-6";"Despesa Extra";258;X;X;"Devedora"\r\n'
    o.carregar_plano(op, "plano2.csv", b)
    return op, rev


# ---------------------------------------------------------------- lançamentos manuais

def test_lanc_01_criar_exige_conta_valida_e_valor(plano_ampliado):
    op, _ = plano_ampliado
    base = dict(tipo="provisao", data="2026-09-30", conta_debito="259", conta_credito="57", valor_centavos=10000,
                historico="PROVISAO INSS 09/2026")
    assert lanc.criar(op, **base) > 0
    for mudanca, trecho in [({"conta_debito": "999"}, "não existe"), ({"conta_debito": "57"}, "mesma conta"),
                            ({"valor_centavos": 0}, "maior que zero"), ({"valor_centavos": -5}, "maior que zero"),
                            ({"tipo": "xyz"}, "tipo inválido"), ({"data": "31/02/2026"}, "inválida"),
                            ({"historico": "  "}, "histórico"), ({"conta_credito": "1"}, "não existe")]:
        with pytest.raises(o.OperacaoInvalida, match=trecho):
            lanc.criar(op, **{**base, **mudanca})


def test_lanc_02_duplicidade_exige_justificativa(plano_ampliado):
    op, _ = plano_ampliado
    base = dict(tipo="ajuste", data="2026-09-30", conta_debito="259", conta_credito="57", valor_centavos=500,
                historico="AJUSTE X")
    lanc.criar(op, **base)
    with pytest.raises(o.OperacaoInvalida, match="já existe"):
        lanc.criar(op, **base)
    lanc.criar(op, **base, justificar_duplicidade="duas competências diferentes")


def test_lanc_03_quem_criou_nao_confirma_e_triggers(plano_ampliado):
    op, rev = plano_ampliado
    i = lanc.criar(op, "provisao", "2026-09-30", "259", "57", 10000, "PROVISAO")
    with pytest.raises(AcessoNegado):
        lanc.confirmar(op, i)  # operador não tem o papel
    lanc.confirmar(rev, i)
    assert op.con.execute("SELECT confirmado_por FROM lancamentos").fetchone()[0] == "Revisor B #2"
    j = lanc.criar(rev, "ajuste", "2026-09-30", "259", "57", 700, "OUTRO AJUSTE")
    with pytest.raises(o.OperacaoInvalida, match="quem criou"):
        lanc.confirmar(rev, j)
    for sql, trecho in [("UPDATE lancamentos SET valor_centavos = 1", "editado"), ("DELETE FROM lancamentos", "apagado")]:
        with pytest.raises(sqlite3.IntegrityError, match=trecho):
            op.con.execute(sql)


def test_lanc_04_importar_leiaute_fortes_tudo_ou_nada(plano_ampliado):
    op, rev = plano_ampliado
    r = lanc.importar_leiaute_fortes(op, "ajuste.csv", AJUSTE)
    assert r["criados"] == 2
    l = lanc.listar(op.con)
    assert {x["ref_externa"] for x in l} == {"[MUL-00311]", "[JUR-01403]"}
    assert all(x["tipo"] == "reclassificacao" and "[" not in x["historico"] for x in l)
    with pytest.raises(ErroEstrutural, match="idêntico"):
        lanc.importar_leiaute_fortes(op, "ajuste2.csv", AJUSTE)
    ruim = AJUSTE + b"19/09/2026;999;57;10,00;CONTA INEXISTENTE;;;;\r\n"
    with pytest.raises(ErroEstrutural, match="não existe no plano"):
        lanc.importar_leiaute_fortes(op, "ruim.csv", ruim)
    assert len(lanc.listar(op.con)) == 2  # nada entrou do arquivo ruim


def test_lanc_05_entra_no_lote_com_marca_propria_e_ida_e_volta(plano_ampliado):
    op, rev = plano_ampliado
    pronto_para_lote(op, rev)
    i = lanc.criar(op, "provisao", "2026-09-30", "259", "57", 123456, "PROVISAO INSS 09/2026")
    _, problemas = o.pre_validar_lote(op, "2026-09", "362")
    assert not any("lançamento manual" in p for p in problemas)  # aguardando: ainda não entra, não bloqueia
    lanc.confirmar(rev, i)
    lote = o.gerar_lote(rev, "2026-09", "362")
    assert lote["quantidade"] == 7
    linhas = o.arquivo_lote(op, lote["lote_id"]).decode("ascii").split("\r\n")[:-1]
    esperado = f"30/09/2026;259;57;1234,56;PROVISAO INSS 09/2026 {marca_lancamento('provisao', '2026-09-30', i)};;;;"
    assert esperado in linhas
    assert op.con.execute("SELECT COUNT(*) FROM lote_itens_lanc").fetchone()[0] == 1
    assert lanc.listar(op.con, "exportado")
    with pytest.raises(sqlite3.IntegrityError):
        op.con.execute("UPDATE lancamentos SET conta_debito = '258'")
    o.registrar_retorno(op, lote["lote_id"], False, "Fortes recusou: conta bloqueada")
    assert lanc.listar(op.con, "confirmado")  # volta para confirmado, pronto para novo lote


def test_lanc_06_marca_ou_referencia_ja_no_razao_bloqueia(plano_ampliado):
    op, rev = plano_ampliado
    pronto_para_lote(op, rev)
    i = lanc.criar(op, "ajuste", "2026-09-30", "259", "57", 1000, "AJUSTE", ref_externa="[MUL-00311]")
    lanc.confirmar(rev, i)
    o.carregar_razao(op, "r.csv", SALDO_ABERTURA + b"30/09/2026;259;57;10,00;JA LANCADO [MUL-00311];;;;\r\n")
    o.conferir(op, "2026-09", "362")
    with pytest.raises(LoteBloqueado, match="MUL-00311"):
        o.gerar_lote(rev, "2026-09", "362")


def test_lanc_07_confere_no_razao_e_saldo_inclui_lancamento_no_banco(plano_ampliado):
    op, rev = plano_ampliado
    pronto_para_lote(op, rev)
    i = lanc.criar(op, "ajuste", "2026-09-28", "362", "259", 5000, "ESTORNO TARIFA")  # toca a conta do banco
    lanc.confirmar(rev, i)
    c = o.conferir(op, "2026-09", "362")
    assert c.pendentes_fora_do_razao != 0 and c.saldo_final_contabil == 91115 + 5000  # lançamento mexe no banco
    assert c.diferenca_centavos == -5000  # e por isso o extrato deixa de bater: o app mostra, não esconde


def test_lanc_08_lote_aceito_com_lancamento_conferido_no_razao(plano_ampliado):
    op, rev = plano_ampliado
    pronto_para_lote(op, rev)
    i = lanc.criar(op, "provisao", "2026-09-30", "259", "57", 123456, "PROVISAO INSS 09/2026")
    lanc.confirmar(rev, i)
    lote = o.gerar_lote(rev, "2026-09", "362")
    o.registrar_retorno(op, lote["lote_id"], True, "ok")
    o.carregar_razao(op, "r.csv", SALDO_ABERTURA + o.arquivo_lote(op, lote["lote_id"]))
    r = o.conferir_lote_no_razao(op, lote["lote_id"])
    assert r["aprovado"] and r["encontrados"] == 7
    o.carregar_razao(op, "r2.csv", SALDO_ABERTURA + o.arquivo_lote(op, lote["lote_id"]).replace(b";1234,56;", b";1234,50;"))
    assert not o.conferir_lote_no_razao(op, lote["lote_id"])["aprovado"]


# ---------------------------------------------------------------- conciliação extrato x Razão

def test_conc_01_extrato_x_razao_classifica_as_diferencas(empresa_pronta):
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    classificar_tudo(op, rev)
    por_marca = {m["historico"]: o.fortes_exporter.marca("ALF", m["data"], m["id"]) for m in movs(op)}
    razao = (SALDO_ABERTURA
             + f"02/09/2026;333;362;45,90;TARIFA {por_marca['TARIFA PACOTE SERVICOS']};;;;\r\n".encode()          # casa por marca
             + b"05/09/2026;265;362;312,40;LANCADO SEM MARCA;;;;\r\n"                                              # casa por data+valor
             + f"10/09/2026;362;2;8499,00;TED {por_marca['TED RECEBIDA CLIENTE ALFA LTDA']};;;;\r\n".encode()      # divergente
             + b"20/09/2026;78;362;980,55;SIMPLES;;;;\r\n"                                                          # casa por data+valor
             + b"20/09/2026;78;362;980,55;SIMPLES DE NOVO;;;;\r\n"                                                  # duplicidade
             + b"22/09/2026;259;362;77,00;SO NO RAZAO;;;;\r\n")                                                     # sem extrato
    o.carregar_razao(op, "r.csv", razao)
    r = cr.comparar(op, "2026-09", "362")
    assert r["extrato"] == 6 and not r["limpo"]
    assert len(r["divergentes"]) == 1 and r["divergentes"][0]["razao_valor"][1] == 849900
    assert len(r["duplicidade_no_razao"]) == 1 and len(r["lancamento_sem_extrato"]) == 1
    assert {m["historico"] for m in r["extrato_sem_lancamento"]} == {"SISPAG FORNECEDORES", "PIX ENVIADO SOCIO EXEMPLO"}
    assert r["casados"] == 3 and r["casados_por_marca"] == 1


def test_conc_02_lote_do_proprio_app_concilia_limpo(empresa_pronta):
    op, rev = empresa_pronta
    pronto_para_lote(op, rev)
    lote = o.gerar_lote(rev, "2026-09", "362")
    o.carregar_razao(op, "r.csv", SALDO_ABERTURA + o.arquivo_lote(op, lote["lote_id"]))
    r = cr.comparar(op, "2026-09", "362")
    assert r["limpo"] and r["casados"] == 6 == r["casados_por_marca"]


def test_conc_03_sem_razao_carregado_pede_o_razao(empresa_pronta):
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    op.con.execute("DELETE FROM razao")
    with pytest.raises(o.OperacaoInvalida, match="Razão"):
        cr.comparar(op, "2026-09", "362")


# ---------------------------------------------------------------- documentos e solicitações

def test_doc_01_validacao_de_upload():
    with pytest.raises(ErroEstrutural, match="não permitida"):
        doc.validar_upload("a.exe", b"MZ\x90\x00")
    with pytest.raises(ErroEstrutural, match="não corresponde"):
        doc.validar_upload("a.pdf", b"MZ\x90\x00 qualquer")
    with pytest.raises(ErroEstrutural, match="não corresponde"):
        doc.validar_upload("a.ofx", b"isto nao e um ofx")
    with pytest.raises(ErroEstrutural, match="não corresponde"):
        doc.validar_upload("a.csv", b"a;b\x00\x01")
    with pytest.raises(ErroEstrutural, match="vazio"):
        doc.validar_upload("a.csv", b"")
    assert doc.validar_upload("ok.pdf", b"%PDF-1.7 ...") == ".pdf"
    assert doc.validar_upload("ok.ofx", (EXEMPLOS / "extrato_exemplo.ofx").read_bytes()) == ".ofx"


def test_doc_02_cliente_ve_so_o_que_enviou_e_equipe_processa(ambiente, empresa_pronta):
    from storage import usuarios
    c = ambiente["central"]
    c1 = usuarios.criar_usuario(c, "Cliente Um", "c1@exemplo.test", "senha-forte-11", "cliente")
    c2 = usuarios.criar_usuario(c, "Cliente Um", "c2@exemplo.test", "senha-forte-12", "cliente")  # mesmo nome
    emp = c.execute("SELECT id FROM empresas WHERE slug = 'alfa'").fetchone()[0]
    usuarios.conceder(c, c1, emp, "cliente")
    usuarios.conceder(c, c2, emp, "cliente")
    cli1, cli2 = ambiente["ctx"]("c1@exemplo.test"), ambiente["ctx"]("c2@exemplo.test")
    op, rev = empresa_pronta
    ofx = (EXEMPLOS / "extrato_exemplo.ofx").read_bytes()
    d1 = doc.enviar(cli1, "set.ofx", ofx, "extrato")
    with pytest.raises(ErroEstrutural, match="já enviou"):
        doc.enviar(cli1, "set.ofx", ofx, "extrato")
    assert [d["id"] for d in doc.listar(cli1)] == [d1] and doc.listar(cli2) == []
    with pytest.raises(o.OperacaoInvalida, match="não encontrado"):
        doc.obter(cli2, d1)  # outro cliente da mesma empresa
    assert cli1.nome != cli2.nome  # mesmo nome, identidades diferentes
    with pytest.raises(AcessoNegado):
        doc.processar_extrato(cli1, d1, "362")  # cliente não processa
    r = doc.processar_extrato(op, d1, "362")
    assert r["movimentos"] == 6 and doc.obter(op, d1)[0]["status"] == "processado"
    with pytest.raises(o.OperacaoInvalida, match="já processado"):
        doc.processar_extrato(op, d1, "362")
    # cliente não alcança nada além do portal
    for funcao in (lambda: o.carregar_razao(cli1, "r.csv", SALDO_ABERTURA), lambda: o.verificar_integridade(cli1),
                   lambda: lanc.criar(cli1, "ajuste", "2026-09-30", "259", "57", 1, "X"),
                   lambda: o.criar_regra(cli1, "x", "contem", "X", "ambos", "259")):
        with pytest.raises(AcessoNegado):
            funcao()


def test_doc_03_solicitacoes(ambiente, empresa_pronta):
    from storage import usuarios
    c = ambiente["central"]
    cid = usuarios.criar_usuario(c, "Cliente Dois", "c3@exemplo.test", "senha-forte-13", "cliente")
    usuarios.conceder(c, cid, c.execute("SELECT id FROM empresas WHERE slug = 'alfa'").fetchone()[0], "cliente")
    cli = ambiente["ctx"]("c3@exemplo.test")
    op, _ = empresa_pronta
    sid = doc.criar_solicitacao(op, "Qual é a natureza do PIX de 15/09?", movimento_id=None)
    with pytest.raises(AcessoNegado):
        doc.criar_solicitacao(cli, "cliente não cria")
    v = doc.solicitacoes_visiveis(cli)
    assert v[0]["mensagem"].startswith("Qual") and "movimento_id" not in v[0] and "criada_por" not in v[0]
    doc.responder_solicitacao(cli, sid, "É empréstimo do sócio")
    assert doc.solicitacoes_visiveis(op)[0]["status"] == "respondida"
    doc.encerrar_solicitacao(op, sid)
    with pytest.raises(o.OperacaoInvalida, match="encerrada"):
        doc.responder_solicitacao(cli, sid, "tarde demais")


# ---------------------------------------------------------------- auditoria encadeada e criptografia

def test_aud_01_cadeia_detecta_adulteracao(empresa_pronta):
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    assert audit.verificar_cadeia(op.con) == []
    op.con.execute("DROP TRIGGER trg_audit_sem_update")  # quem mexe no arquivo .db diretamente
    op.con.execute("UPDATE audit_log SET usuario = 'Fulano' WHERE id = 3")
    assert any("não confere" in p for p in audit.verificar_cadeia(op.con))
    op.con.execute("DROP TRIGGER trg_audit_sem_delete")
    op.con.execute("DELETE FROM audit_log WHERE id = 5")
    p = audit.verificar_cadeia(op.con)
    assert any("ausentes" in x for x in p)
    ultimo = op.con.execute("SELECT MAX(id) FROM audit_log").fetchone()[0]
    op.con.execute("DELETE FROM audit_log WHERE id = ?", (ultimo,))
    assert any("finais ausentes" in x for x in audit.verificar_cadeia(op.con))
    assert any("cadeia" in x or "audit_log" in x for x in o.verificar_integridade(op))


def test_aud_02_cadeia_de_acesso_central(ambiente):
    c = ambiente["central"]
    audit.registrar_acesso(c, 1, None, "login", "ok")
    audit.registrar_acesso(c, 1, None, "login", "negado")
    assert audit.verificar_cadeia(c, "audit_acesso") == []
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE audit_acesso SET resultado = 'ok'")


def test_cri_01_arquivos_cifrados_em_repouso(ambiente, monkeypatch, empresa_pronta):
    from storage import cripto
    monkeypatch.setenv("CONCILIADOR_CRIPTO", "1")
    monkeypatch.setattr(cripto.config, "DATA_DIR", ambiente["data"])
    op, rev = empresa_pronta
    ofx = (EXEMPLOS / "extrato_exemplo.ofx").read_bytes()
    o.carregar_extrato(op, "set.ofx", ofx, "362")
    f = op.pasta / op.con.execute("SELECT caminho FROM arquivos WHERE tipo = 'extrato_ofx'").fetchone()[0]
    bruto = f.read_bytes()
    assert bruto.startswith(cripto.MAGIC) and b"TARIFA" not in bruto and b"<OFX>" not in bruto
    assert op.ler_arquivo(f) == ofx
    assert o.verificar_integridade(op) == []
    # arquivo de uma empresa não abre com a chave de outra
    with pytest.raises(cripto.ErroCripto):
        cripto.recuperar("beta", bruto)
    # adulteração é detectada
    f.chmod(0o644)
    f.write_bytes(bruto[:-1] + bytes([bruto[-1] ^ 1]))
    assert any("alterado ou ilegível" in p for p in o.verificar_integridade(op))
    t = cripto.proteger_texto("SEMENTE123")
    assert t.startswith("aes:") and "SEMENTE123" not in t and cripto.recuperar_texto(t) == "SEMENTE123"


def test_aud_03_cadeia_detecta_encadeamento_forjado_e_linha_inserida_por_fora(empresa_pronta):
    """Quem refaz o hash de UMA linha continua sendo pego pelo elo com a anterior; linha sem hash também."""
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    assert audit.verificar_cadeia(op.con) == []
    op.con.execute("DROP TRIGGER trg_audit_sem_update")
    linha = op.con.execute("SELECT * FROM audit_log WHERE id = 4").fetchone()
    falso_anterior = "f" * 64
    novo = audit._hash(falso_anterior, {c: linha[c] for c in audit.CAMPOS["audit_log"]})
    op.con.execute("UPDATE audit_log SET hash_anterior = ?, hash = ? WHERE id = 4", (falso_anterior, novo))
    problemas = audit.verificar_cadeia(op.con)
    assert any("linha 4: encadeamento quebrado" in p for p in problemas)
    assert not any("linha 4: conteúdo não confere" in p for p in problemas)  # o hash próprio estava coerente
    op.con.execute("UPDATE audit_log SET hash_anterior = ?, hash = ? WHERE id = 4", (linha["hash_anterior"], linha["hash"]))
    assert audit.verificar_cadeia(op.con) == []
    op.con.execute("INSERT INTO audit_log (ts, usuario, acao, entidade) VALUES ('x', 'intruso', 'acao', 'x')")
    assert any("sem hash depois de a cadeia começar" in p for p in audit.verificar_cadeia(op.con))
