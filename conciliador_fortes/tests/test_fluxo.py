"""Fluxo completo da Etapa A com os exemplos sintéticos."""

import pytest

from domain import operacoes as o
from exporters.fortes_exporter import LoteBloqueado
from parsers.comum import ErroEstrutural
from parsers.tabular_parser import Mapeamento
from storage.usuarios import AcessoNegado
from tests.conftest import EXEMPLOS

OFX = (EXEMPLOS / "extrato_exemplo.ofx").read_bytes()
SALDO_ABERTURA = b"31/08/2026;362;90;10000,00;SALDO DE ABERTURA;;;;\r\n"


def movs(ctx, **filtro):
    sql = "SELECT * FROM movimentos" + (" WHERE " + " AND ".join(f"{k} = ?" for k in filtro) if filtro else "")
    return ctx.con.execute(sql + " ORDER BY id", tuple(filtro.values())).fetchall()


def preparar_setembro(op, rev):
    r = o.carregar_extrato(op, "set.ofx", OFX, "362")
    o.carregar_razao(op, "razao.csv", SALDO_ABERTURA)
    o.informar_saldos(op, "2026-09", "362", 1000000, 91115)
    return r


def classificar_tudo(op, rev):
    for m in movs(op, status="proposto"):
        o.classificar(op, m["id"], m["conta_debito"] if m["valor_centavos"] < 0 else m["conta_credito"],
                      natureza=m["natureza"], origem="regra")
    sispag = movs(op, historico="SISPAG FORNECEDORES")[0]
    socio = movs(op, historico="PIX ENVIADO SOCIO EXEMPLO")[0]
    o.classificar(op, sispag["id"], "56", "PAGTO FORNECEDOR PAPELARIA GAMA")
    o.classificar(op, socio["id"], "90", natureza="socio")
    return sispag, socio


def test_carga_regras_e_risco(empresa_pronta):
    op, rev = empresa_pronta
    r = preparar_setembro(op, rev)
    assert r["movimentos"] == 6 and r["propostos"] == 4 and r["saldo_final_ofx"] == 91115
    socio = movs(op, historico="PIX ENVIADO SOCIO EXEMPLO")[0]
    assert socio["status"] == "pendente" and socio["exige_segunda_confirmacao"] == 1
    assert "sócio" in socio["motivos_risco"] and "limite" in socio["motivos_risco"]
    energia = movs(op, historico="PAGTO ENERGIA ELETRICA DISTRIB")[0]
    assert (energia["conta_debito"], energia["conta_credito"]) == ("265", "362")  # classificação -> reduzido
    ted = movs(op, historico="TED RECEBIDA CLIENTE ALFA LTDA")[0]
    assert (ted["conta_debito"], ted["conta_credito"]) == ("362", "2")


def test_arquivo_repetido_bloqueado_e_fitid_alerta(empresa_pronta):
    op, _ = empresa_pronta
    o.carregar_extrato(op, "set.ofx", OFX, "362")
    with pytest.raises(ErroEstrutural, match="SHA-256"):
        o.carregar_extrato(op, "copia.ofx", OFX, "362")
    # mesmo conteúdo com outro cabeçalho: hash diferente, mas FITID repetido -> alerta, não exclusão
    o.carregar_extrato(op, "outro.ofx", OFX.replace(b"VERSION:102", b"VERSION:103"), "362")
    alertas = movs(op, decisao_duplicidade="pendente")
    assert len(alertas) == 6 and all("FITID" in a["motivo_duplicidade"] for a in alertas)
    assert len(movs(op)) == 12  # nada excluído automaticamente


def test_semelhanca_entre_arquivos_tabulares(empresa_pronta):
    op, _ = empresa_pronta
    mapa = Mapeamento(data="Data", historico="Histórico", valor="Valor")
    o.carregar_extrato(op, "out.csv", (EXEMPLOS / "extrato_exemplo.csv").read_bytes(), "362", mapa)
    parecido = "Data;Histórico;Valor\n06/10/2026;TED RECEBIDA CLIENTE ALFA LTD;2300,00\n".encode()
    o.carregar_extrato(op, "out2.csv", parecido, "362", mapa)
    a = movs(op, decisao_duplicidade="pendente")
    assert len(a) == 1 and "parecido" in a[0]["motivo_duplicidade"]
    o.decidir_duplicidade(op, a[0]["id"], "descartar", "mesmo TED lançado em dois arquivos")
    assert movs(op, id=a[0]["id"])[0]["status"] == "descartado"


def test_duplicidade_mantida_exige_segunda_revisao(empresa_pronta):
    op, _ = empresa_pronta
    o.carregar_extrato(op, "set.ofx", OFX, "362")
    o.carregar_extrato(op, "outro.ofx", OFX.replace(b"VERSION:102", b"VERSION:103"), "362")
    a = movs(op, decisao_duplicidade="pendente", fitid="A0001")[0]
    o.decidir_duplicidade(op, a["id"], "manter", "são duas tarifas distintas, conferido no extrato")
    assert "duplicidade mantida" in movs(op, id=a["id"])[0]["motivos_risco"]


def test_segregacao_de_funcao(empresa_pronta):
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    _, socio = classificar_tudo(op, rev)
    with pytest.raises(AcessoNegado):
        o.segunda_confirmacao(op, socio["id"])  # operador não tem o papel
    o.classificar(rev, socio["id"], "90", natureza="socio")  # agora o revisor é quem revisou
    with pytest.raises(o.OperacaoInvalida, match="não pode dar a segunda"):
        o.segunda_confirmacao(rev, socio["id"])
    o.classificar(op, socio["id"], "90", natureza="socio")
    o.segunda_confirmacao(rev, socio["id"])
    assert movs(op, id=socio["id"])[0]["segunda_confirmacao_por"] == "Revisor B"


def test_lote_fortes_completo_byte_a_byte(empresa_pronta):
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    sispag, socio = classificar_tudo(op, rev)
    assert o.pistas_planilha(op.con, sispag) == []
    o.carregar_planilha_despesas(op, "desp.csv", (EXEMPLOS / "despesas_exemplo.csv").read_bytes(),
                                 Mapeamento(data="Data", historico="Descrição", valor="Valor",
                                            documento="Lançamento bancário", inverter_sinal=True))
    assert o.pistas_planilha(op.con, sispag)[0]["descricao"].startswith("Material")

    # sem segunda confirmação do sócio: bloqueado
    c = o.conferir(op, "2026-09", "362")
    assert c.fecha and c.diferenca_centavos == 0
    with pytest.raises(LoteBloqueado, match="segunda confirmação"):
        o.gerar_lote(rev, "2026-09", "362")
    with pytest.raises(AcessoNegado):
        o.gerar_lote(op, "2026-09", "362")  # operador não exporta
    o.segunda_confirmacao(rev, socio["id"])
    lote = o.gerar_lote(rev, "2026-09", "362")
    conteudo = lote["arquivo"].read_bytes()
    linhas = conteudo.decode("ascii").split("\r\n")
    assert linhas[-1] == "" and len(linhas) == 7
    ids = {m["historico"]: m["id"] for m in movs(op)}
    assert linhas[0] == f"02/09/2026;333;362;45,90;TARIFA BANCARIA [ALF-202609-{ids['TARIFA PACOTE SERVICOS']:06d}];;;;"
    assert linhas[4] == (f"15/09/2026;90;362;15000,00;PIX ENVIADO SOCIO EXEMPLO "
                         f"[ALF-202609-{ids['PIX ENVIADO SOCIO EXEMPLO']:06d}];;;;")
    assert all(len(l.split(";")) == 9 for l in linhas[:-1]) and all(b < 128 for b in conteudo)
    assert len(movs(op, status="exportado")) == 6

    # outro lote do mesmo período fica travado até o retorno
    with pytest.raises(LoteBloqueado, match="aguardando retorno"):
        o.gerar_lote(rev, "2026-09", "362")
    o.registrar_retorno(op, lote["lote_id"], False, "Conta do complementar do lançamento em branco")
    assert len(movs(op, status="classificado")) == 6
    lote2 = o.gerar_lote(rev, "2026-09", "362")
    o.registrar_retorno(op, lote2["lote_id"], True, "importado sem erro")

    # Razão reimportado com o lote: a conferência reconhece as marcas e continua fechando
    o.carregar_razao(op, "razao2.csv", SALDO_ABERTURA + lote2["arquivo"].read_bytes())
    c2 = o.conferir(op, "2026-09", "362")
    assert c2.pendentes_fora_do_razao == 0 and c2.saldo_razao == 91115 and c2.fecha
    acoes = [r["acao"] for r in op.con.execute("SELECT acao FROM audit_log")]
    for a in ("extrato_carregado", "movimento_classificado", "segunda_confirmacao", "lote_bloqueado",
              "lote_gerado", "retorno_fortes", "conferencia_saldo"):
        assert a in acoes


@pytest.mark.parametrize("estrago, trecho", [
    ("UPDATE movimentos SET conta_debito = '999' WHERE historico LIKE 'TARIFA%'", "não existe no plano"),
    ("UPDATE movimentos SET conta_debito = '362' WHERE historico LIKE 'TARIFA%'", "débito igual a crédito"),
    ("UPDATE movimentos SET conta_credito = NULL WHERE historico LIKE 'TARIFA%'", "sem conta"),
    ("UPDATE plano_contas SET aceita_lancamento = 0 WHERE reduzido = '333'", "sintética"),
    ("UPDATE movimentos SET decisao_duplicidade = 'pendente' WHERE historico LIKE 'TARIFA%'", "duplicidade"),
])
def test_validadores_bloqueantes(empresa_pronta, estrago, trecho):
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    _, socio = classificar_tudo(op, rev)
    o.segunda_confirmacao(rev, socio["id"])
    o.conferir(op, "2026-09", "362")
    op.con.execute(estrago)
    with pytest.raises(LoteBloqueado, match=trecho):
        o.gerar_lote(rev, "2026-09", "362")
    assert not movs(op, status="exportado")
    assert not list((op.pasta / "arquivos" / "exportacoes").iterdir())


def test_diferenca_exige_justificativa_e_segunda_revisao(empresa_pronta):
    op, rev = empresa_pronta
    preparar_setembro(op, rev)
    _, socio = classificar_tudo(op, rev)
    o.segunda_confirmacao(rev, socio["id"])
    tarifa = movs(op, historico="TARIFA PACOTE SERVICOS")[0]
    o.colocar_em_espera(op, tarifa["id"], "aguardando contrato do pacote")
    c = o.conferir(op, "2026-09", "362")
    assert c.diferenca_centavos == -4590  # a tarifa em espera ainda não está na contabilidade
    with pytest.raises(LoteBloqueado, match="justificativa"):
        o.gerar_lote(rev, "2026-09", "362")
    o.justificar_diferenca(rev, "2026-09", "362", "tarifa de 45,90 em espera, vai em lote separado")
    with pytest.raises(o.OperacaoInvalida, match="quem justificou"):
        o.revisar_diferenca(rev, "2026-09", "362")
    o.justificar_diferenca(op, "2026-09", "362", "tarifa de 45,90 em espera, vai em lote separado")
    with pytest.raises(AcessoNegado):
        o.revisar_diferenca(op, "2026-09", "362")
    o.revisar_diferenca(rev, "2026-09", "362")
    assert o.conciliacao(op.con, "2026-09", "362")["status"] == "justificada"  # nunca 'concluida' com diferença
    lote = o.gerar_lote(rev, "2026-09", "362")
    assert lote["quantidade"] == 5  # em espera fica fora


def test_isolamento_entre_empresas(ambiente, empresa_pronta):
    op, _ = empresa_pronta
    preparar_setembro(op, None)
    with pytest.raises(AcessoNegado):
        ambiente["ctx"]("op@exemplo.test", "beta")
    beta = ambiente["ctx"]("c@exemplo.test", "beta")
    assert beta.con.execute("SELECT COUNT(*) FROM movimentos").fetchone()[0] == 0
    with pytest.raises(AcessoNegado):
        ambiente["ctx"]("c@exemplo.test", "alfa")
    negados = ambiente["central"].execute("SELECT COUNT(*) FROM audit_acesso WHERE resultado = 'negado'").fetchone()[0]
    assert negados == 2
    # cada empresa tem seu próprio arquivo de banco
    assert op.con.execute("PRAGMA database_list").fetchone()["file"] != beta.con.execute(
        "PRAGMA database_list").fetchone()["file"]
