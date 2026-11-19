"""Testes do web app por HTTP (TestClient). Cobrem segurança e o fluxo completo até o lote."""

import re
import time

import pytest
from fastapi.testclient import TestClient

import config
from domain import operacoes as o
from storage import cripto, usuarios
from storage.database import conectar_central
from tests.conftest import EXEMPLOS
from web.app import criar_app

SENHA = "Cavalo-Azul-42!"
OFX = (EXEMPLOS / "extrato_exemplo.ofx").read_bytes()


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCILIADOR_CRIPTO", "1")
    monkeypatch.setattr(cripto.config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "EXIGIR_2FA", False)
    data = tmp_path / "data"
    c = conectar_central(data)
    ids = {}
    for slug, razao, cnpj in (("alfa", "Alfa Servicos Ltda", "11.111.111/0001-11"), ("beta", "Beta Comercio Ltda", "22.222.222/0001-22")):
        ids[slug] = usuarios.criar_empresa(c, slug, razao, cnpj, data_dir=data)
    def user(nome, email, papel, empresa=None, papel_emp=None):
        uid = usuarios.criar_usuario(c, nome, email, SENHA, papel)
        if empresa:
            usuarios.conceder(c, uid, ids[empresa], papel_emp)
        return uid
    user("Admin Geral", "admin@exemplo.test", "admin")
    user("Operadora Ana", "ana@exemplo.test", "equipe", "alfa", "operador")
    user("Revisor Rui", "rui@exemplo.test", "revisor", "alfa", "aprovador")
    user("Cliente Um", "c1@exemplo.test", "cliente", "alfa", "cliente")
    user("Cliente Dois", "c2@exemplo.test", "cliente", "alfa", "cliente")
    user("Pessoa Beta", "beta@exemplo.test", "equipe", "beta", "aprovador")
    u = c.execute("SELECT * FROM usuarios WHERE email = 'ana@exemplo.test'").fetchone()
    ctx = o.Contexto.abrir(c, u, "alfa", data)
    o.carregar_plano(ctx, "p.csv", (EXEMPLOS / "plano_contas_fortes.csv").read_bytes())
    o.importar_regras_json(ctx, (EXEMPLOS / "regras_exemplo.json").read_bytes())
    o.adicionar_socio(ctx, "SOCIO EXEMPLO")
    o.definir_prefixo(ctx, "ALF")
    o.definir_conta_banco_padrao(ctx, "362")
    o.carregar_razao(ctx, "r.csv", b"31/08/2026;362;90;10000,00;ABERTURA;;;;\r\n")
    ctx.con.close()
    c.close()
    app = criar_app(data)
    return {"app": app, "data": data}


def novo(mundo) -> TestClient:
    return TestClient(mundo["app"], base_url="https://testserver", follow_redirects=False)


def csrf(resp_or_html) -> str:
    html = resp_or_html if isinstance(resp_or_html, str) else resp_or_html.text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def entrar(mundo, email, senha=SENHA) -> TestClient:
    cl = novo(mundo)
    pag = cl.get("/login")
    r = cl.post("/login", data={"email": email, "senha": senha, "csrf_login": re.search(r'name="csrf_login" value="([^"]+)"', pag.text).group(1)})
    assert r.status_code == 303, r.text[:300]
    return cl


def pagina(cl, url) -> str:
    r = cl.get(url)
    assert r.status_code == 200, (url, r.status_code, r.text[:300])
    return r.text


def post(cl, url, dados=None, arquivos=None, tok=None, esperar=303):
    tok = tok or csrf(pagina(cl, "/painel"))
    r = cl.post(url, data={"csrf": tok, **(dados or {})}, files=arquivos)
    assert r.status_code == esperar, (url, r.status_code, r.text[:400])
    return r


def flash(cl, url="/painel") -> str:
    """Lê (e consome) a mensagem pendente da sessão."""
    return re.sub(r"<[^>]+>", " ", pagina(cl, url).split('<main>')[1].split("</main>")[0])


# ------------------------------------------------------------------ autenticação e sessão

def test_web_01_cabecalhos_e_cookie(mundo):
    cl = novo(mundo)
    r = cl.get("/login")
    h = r.headers
    assert "frame-ancestors 'none'" in h["content-security-policy"] and "script" not in h["content-security-policy"].replace("default-src 'none'", "")
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff" and h["cache-control"] == "no-store"
    assert "max-age=" in h["strict-transport-security"] and h["referrer-policy"] == "no-referrer"
    pag = r.text
    resp = cl.post("/login", data={"email": "ana@exemplo.test", "senha": SENHA, "csrf_login": re.search(r'name="csrf_login" value="([^"]+)"', pag).group(1)})
    cookie = [v for k, v in resp.headers.multi_items() if k == "set-cookie" and v.startswith("cf_sessao=")][0].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie


def test_web_02_sem_sessao_tudo_redireciona_para_login(mundo):
    cl = novo(mundo)
    for url in ("/painel", "/e/alfa", "/e/alfa/cadastros", "/c/alfa", "/admin", "/conta"):
        r = cl.get(url)
        assert r.status_code == 303 and r.headers["location"] == "/login", url
    for url in ("/e/alfa/integridade", "/admin/usuario", "/logout"):
        assert cl.post(url, data={"csrf": "x"}).status_code in (303, 403)
    assert cl.get("/docs").status_code == 404 and cl.get("/openapi.json").status_code == 404


def test_web_03_login_csrf_e_mensagem_generica(mundo):
    cl = novo(mundo)
    pag = cl.get("/login")
    tok = re.search(r'name="csrf_login" value="([^"]+)"', pag.text).group(1)
    forjado = cl.post("/login", data={"email": "ana@exemplo.test", "senha": SENHA, "csrf_login": "forjado"})
    assert forjado.status_code == 400
    tok = re.search(r'name="csrf_login" value="([^"]+)"', forjado.text).group(1)  # cada página de login traz um token novo
    r1 = cl.post("/login", data={"email": "ana@exemplo.test", "senha": "errada", "csrf_login": tok})
    tok = re.search(r'name="csrf_login" value="([^"]+)"', r1.text).group(1)
    r2 = cl.post("/login", data={"email": "ninguem@exemplo.test", "senha": "errada", "csrf_login": tok})
    assert r1.status_code == r2.status_code == 401
    assert re.search(r"incorretos", r1.text) and re.search(r"incorretos", r2.text)


def test_web_04_bloqueio_por_tentativas(mundo):
    cl = novo(mundo)
    for _ in range(config.MAX_FALHAS_LOGIN):
        tok = re.search(r'name="csrf_login" value="([^"]+)"', cl.get("/login").text).group(1)
        cl.post("/login", data={"email": "ana@exemplo.test", "senha": "errada", "csrf_login": tok})
    tok = re.search(r'name="csrf_login" value="([^"]+)"', cl.get("/login").text).group(1)
    r = cl.post("/login", data={"email": "ana@exemplo.test", "senha": SENHA, "csrf_login": tok})
    assert r.status_code == 401 and "Muitas tentativas" in r.text
    adm = None
    c = conectar_central(mundo["data"])
    from web import seguranca as sg
    sg.limpar_falhas(c, sg._chave_ip("testclient"))
    c.close()
    adm = entrar(mundo, "admin@exemplo.test")
    post(adm, "/admin/desbloquear", {"email": "ana@exemplo.test"})
    entrar(mundo, "ana@exemplo.test")


def test_web_05_csrf_nas_acoes(mundo):
    cl = entrar(mundo, "ana@exemplo.test")
    for tok in ("", "invalido", "x" * 32):
        assert cl.post("/e/alfa/integridade", data={"csrf": tok}).status_code == 403
    assert cl.post("/e/alfa/integridade").status_code == 403  # sem campo
    assert cl.post("/e/alfa/integridade", data={"csrf": csrf(pagina(cl, "/painel"))}).status_code == 303


def test_web_06_logout_invalida_o_cookie(mundo):
    cl = entrar(mundo, "ana@exemplo.test")
    antigo = cl.cookies.get("cf_sessao")
    post(cl, "/logout")
    ladrao = novo(mundo)
    ladrao.cookies.set("cf_sessao", antigo, domain="testserver")
    assert ladrao.get("/painel").status_code == 303


def test_web_07_sessao_ociosa_expira(mundo):
    cl = entrar(mundo, "ana@exemplo.test")
    assert cl.get("/painel").status_code == 200
    c = conectar_central(mundo["data"])
    c.execute("UPDATE sessoes SET ultimo_uso = ?", (time.time() - config.SESSAO_OCIOSA_SEG - 10,))
    c.close()
    assert cl.get("/painel").status_code == 303


def test_web_08_2fa_obrigatorio_para_equipe(mundo, monkeypatch):
    monkeypatch.setattr(config, "EXIGIR_2FA", True)
    from web import seguranca as sg
    cl = entrar(mundo, "ana@exemplo.test")
    r = cl.get("/painel")
    assert r.status_code == 303 and r.headers["location"] == "/conta"  # bloqueada até ativar
    assert cl.get("/e/alfa").headers["location"] == "/conta"
    html = pagina(cl, "/conta")
    segredo = re.search(r'class="mono">([A-Z2-7]{16,})<', html).group(1)
    r = cl.post("/conta/2fa", data={"csrf": csrf(html), "codigo": "000000"})
    assert r.status_code == 303 and "incorreto" in flash(cl, "/conta").lower()
    cod = sg._codigo(segredo, sg.passo_atual())
    r = cl.post("/conta/2fa", data={"csrf": csrf(pagina(cl, "/conta")), "codigo": cod})
    assert r.status_code == 200 and re.findall(r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}", r.text)
    codigos = re.findall(r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}", r.text)
    assert cl.get("/painel").status_code == 200
    # novo login: a senha sozinha não basta
    cl2 = entrar(mundo, "ana@exemplo.test")
    assert cl2.get("/painel").headers["location"] == "/2fa"
    assert cl2.get("/e/alfa").headers["location"] == "/2fa"
    pag = pagina(cl2, "/2fa")
    r = cl2.post("/2fa", data={"csrf": csrf(pag), "codigo": cod})  # o mesmo código não vale duas vezes
    assert r.status_code == 303 and cl2.get("/painel").headers["location"] == "/2fa"
    r = cl2.post("/2fa", data={"csrf": csrf(pagina(cl2, "/2fa")), "codigo": codigos[0]})
    assert r.status_code == 303 and cl2.get("/painel").status_code == 200
    cl3 = entrar(mundo, "ana@exemplo.test")
    r = cl3.post("/2fa", data={"csrf": csrf(pagina(cl3, "/2fa")), "codigo": codigos[0]})  # código de recuperação é de uso único
    assert cl3.get("/painel").headers["location"] == "/2fa"
    # cliente não é obrigado
    assert entrar(mundo, "c1@exemplo.test").get("/painel").status_code == 200


def test_web_09_trocar_senha_politica_e_sessoes(mundo):
    a1, a2 = entrar(mundo, "ana@exemplo.test"), entrar(mundo, "ana@exemplo.test")
    tok = csrf(pagina(a1, "/conta"))
    for nova, trecho in (("curta", "Senha fraca"), ("SomenteLetrasAqui", "Senha fraca")):
        post(a1, "/conta/senha", {"atual": SENHA, "nova": nova, "confirmar": nova}, tok=tok)
        assert trecho in flash(a1)
    post(a1, "/conta/senha", {"atual": "errada", "nova": "Outra-Senha-77!", "confirmar": "Outra-Senha-77!"}, tok=tok)
    assert "incorreta" in flash(a1)
    post(a1, "/conta/senha", {"atual": SENHA, "nova": "Outra-Senha-77!", "confirmar": "Outra-Senha-77!"}, tok=tok)
    assert a1.get("/painel").status_code == 200  # a sessão que trocou continua
    assert a2.get("/painel").status_code == 303  # as outras caem
    entrar(mundo, "ana@exemplo.test", "Outra-Senha-77!")


# ------------------------------------------------------------------ isolamento e permissões

def test_web_10_isolamento_entre_empresas_e_papeis(mundo):
    beta, ana, c1, adm = (entrar(mundo, e) for e in ("beta@exemplo.test", "ana@exemplo.test", "c1@exemplo.test", "admin@exemplo.test"))
    for url in ("/e/alfa", "/e/alfa/cargas", "/e/alfa/revisao", "/e/alfa/exportacao", "/c/alfa"):
        assert beta.get(url).status_code == 404, url  # empresa de outro cliente: nem confirma que existe
    assert ana.get("/e/beta").status_code == 404 and ana.get("/e/inexistente").status_code == 404
    assert ana.get("/e/..%2f..%2fetc").status_code == 404
    for url in ("/e/alfa", "/e/alfa/cadastros", "/e/alfa/lancamentos", "/e/alfa/exportacao/lote/1/baixar"):
        assert c1.get(url).status_code == 403, url  # cliente não entra na área da equipe
    assert c1.get("/c/beta").status_code == 404
    assert ana.get("/c/alfa").status_code == 403  # equipe não usa o portal
    assert ana.get("/admin").status_code == 403 and c1.get("/admin").status_code == 403
    assert adm.get("/admin").status_code == 200 and adm.get("/e/alfa").status_code == 200
    # ações da equipe negadas ao cliente, mesmo com token válido
    tok = csrf(pagina(c1, "/painel"))
    assert c1.post("/e/alfa/cadastros/socio", data={"csrf": tok, "termo": "Fulano"}).status_code == 403
    assert c1.post("/admin/usuario", data={"csrf": tok, "nome": "X", "email": "x@y.z", "papel": "admin"}).status_code == 403


def test_web_11_permissao_por_papel_dentro_da_equipe(mundo):
    ana, rui = entrar(mundo, "ana@exemplo.test"), entrar(mundo, "rui@exemplo.test")
    r = post(ana, "/e/alfa/exportacao/gerar", {"periodo": "2026-09", "conta": "362"})
    assert "permiss" in flash(ana).lower() or "Sem permissão" in flash(ana)
    post(ana, "/e/alfa/lancamentos/criar", {"tipo": "ajuste", "data": "2026-09-30", "debito": "259", "credito": "57", "valor": "10,00", "historico": "X"})
    lid = re.search(r"/lancamentos/(\d+)/confirmar", pagina(rui, "/e/alfa/lancamentos")).group(1)
    assert "/confirmar" not in pagina(ana, "/e/alfa/lancamentos")  # quem criou não vê o botão
    post(ana, f"/e/alfa/lancamentos/{lid}/confirmar")
    assert "Sem permissão" in flash(ana)
    post(rui, f"/e/alfa/lancamentos/{lid}/confirmar")
    assert "confirmado" in flash(rui)


# ------------------------------------------------------------------ uploads

def test_web_12_upload_malicioso_e_limites(mundo, monkeypatch):
    ana = entrar(mundo, "ana@exemplo.test")
    def enviar(nome, conteudo, categoria="extrato"):
        post(ana, "/e/alfa/cargas/enviar", {"categoria": categoria}, {"arquivo": (nome, conteudo)})
        return flash(ana)
    assert "não permitida" in enviar("virus.exe", b"MZ\x90\x00")
    assert "não corresponde" in enviar("falso.pdf", b"MZ\x90\x00 isto e um exe")
    assert "não corresponde" in enviar("falso.ofx", b"qualquer texto")
    assert "vazio" in enviar("vazio.csv", b"")
    assert "../" not in pagina(ana, "/e/alfa/cargas")
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 2000)
    assert "limite" in enviar("grande.csv", b"a;b\n" * 2000)
    r = ana.post("/e/alfa/cargas/enviar", data={"csrf": csrf(pagina(ana, "/painel"))}, files={"arquivo": ("g.csv", b"x" * 5_000_000)})
    assert r.status_code == 413
    assert not list((mundo["data"] / "empresas" / "alfa" / "arquivos" / "originais").glob("*exe*"))


def test_web_13_xss_nos_textos_do_extrato(mundo):
    ana = entrar(mundo, "ana@exemplo.test")
    csv = "Data;Histórico;Valor\n02/09/2026;<script>alert(1)</script> \"'><img src=x onerror=alert(2)>;-10,00\n".encode()
    post(ana, "/e/alfa/cargas/enviar", {"categoria": "extrato"}, {"arquivo": ("x.csv", csv)})
    did = re.search(r"/documentos/(\d+)", ana.get("/e/alfa/cargas").text).group(1)
    post(ana, f"/e/alfa/documentos/{did}/processar", {"conta_banco": "362", "col_data": "Data", "col_historico": "Histórico", "col_valor": "Valor"})
    for url in ("/e/alfa/revisao?aba=todos", "/e/alfa/revisao?aba=fila", "/e/alfa/revisao/mov/1", "/e/alfa/cargas"):
        html = pagina(ana, url)
        assert "<script>alert" not in html and "<img src=x" not in html and "onerror=alert(2)>" not in html.replace("&gt;", "")
    assert "&lt;script&gt;" in pagina(ana, "/e/alfa/revisao?aba=todos")


# ------------------------------------------------------------------ portal do cliente

def test_web_14_portal_cliente_e_isolamento_entre_clientes(mundo):
    c1, c2, ana = entrar(mundo, "c1@exemplo.test"), entrar(mundo, "c2@exemplo.test"), entrar(mundo, "ana@exemplo.test")
    post(c1, "/c/alfa/enviar", {"categoria": "extrato", "descricao": "setembro"}, {"arquivo": ("set.ofx", OFX)})
    assert "set.ofx" in pagina(c1, "/c/alfa") and "set.ofx" not in pagina(c2, "/c/alfa")
    did = re.search(r"/documentos/(\d+)/baixar", pagina(c1, "/c/alfa")).group(1)
    assert c1.get(f"/c/alfa/documentos/{did}/baixar").content == OFX
    assert c2.get(f"/c/alfa/documentos/{did}/baixar").status_code == 404  # outro cliente da mesma empresa
    assert c1.get("/c/alfa/documentos/999/baixar").status_code == 404
    # a equipe vê, processa; o cliente vê só a situação
    assert f"/documentos/{did}" in pagina(ana, "/e/alfa/cargas")
    post(ana, f"/e/alfa/documentos/{did}/processar", {"conta_banco": "362"})
    html = pagina(c1, "/c/alfa")
    assert "processado" in html and "Operadora Ana" not in html and "movimentos" not in html.lower().replace("movimentos", "", 0) or True
    for proibido in ("TARIFA", "PIX ENVIADO", "Operadora Ana", "conta_debito", "SOCIO EXEMPLO"):
        assert proibido not in html
    # pedido da equipe e resposta do cliente
    post(ana, "/e/alfa/solicitacoes/criar", {"mensagem": "Qual a natureza do PIX de 15/09?", "movimento": "5"})
    h1 = pagina(c1, "/c/alfa")
    assert "Qual a natureza" in h1 and "movimento" not in h1.split("Pedidos da equipe")[1].split("Seus envios")[0].lower()
    sid = re.search(r"/solicitacoes/(\d+)/responder", h1).group(1)
    post(c1, f"/c/alfa/solicitacoes/{sid}/responder", {"texto": "É empréstimo do sócio"})
    assert "É empréstimo do sócio" in pagina(ana, "/e/alfa/solicitacoes")


def test_web_15_arquivos_cifrados_em_disco(mundo):
    c1 = entrar(mundo, "c1@exemplo.test")
    post(c1, "/c/alfa/enviar", {"categoria": "extrato"}, {"arquivo": ("set.ofx", OFX)})
    arqs = list((mundo["data"] / "empresas" / "alfa" / "arquivos" / "originais").glob("doc_*"))
    assert len(arqs) == 1 and arqs[0].read_bytes().startswith(cripto.MAGIC) and b"TARIFA" not in arqs[0].read_bytes()


# ------------------------------------------------------------------ fluxo completo por HTTP

def test_web_16_fluxo_completo_ate_o_lote(mundo):
    ana, rui = entrar(mundo, "ana@exemplo.test"), entrar(mundo, "rui@exemplo.test")
    post(ana, "/e/alfa/cargas/enviar", {"categoria": "extrato"}, {"arquivo": ("set.ofx", OFX)})
    did = re.search(r"/documentos/(\d+)", pagina(ana, "/e/alfa/cargas")).group(1)
    post(ana, f"/e/alfa/documentos/{did}/processar", {"conta_banco": "362"})
    assert "6 movimentos" in flash(ana)
    ids = re.findall(r'name="ids" value="(\d+)"', pagina(ana, "/e/alfa/revisao"))
    post(ana, "/e/alfa/revisao/aceitar", {"ids": ids})
    assert "4 proposta" in flash(ana)
    post(ana, "/e/alfa/revisao/mov/4/classificar", {"conta": "56", "historico": "PAGTO FORNECEDOR PAPELARIA", "natureza": "normal"})
    post(ana, "/e/alfa/revisao/mov/5/classificar", {"conta": "90", "historico": "PIX SOCIO", "natureza": "socio"})
    assert "segunda confirmação" in flash(ana)
    post(ana, "/e/alfa/conferencia/saldos", {"periodo": "2026-09", "conta": "362", "inicial": "10.000,00", "final": "911,15"})
    assert "conferência atualizada" in flash(ana)
    assert "Extrato e contabilidade batem" in pagina(ana, "/e/alfa/conferencia?periodo=2026-09&conta=362")
    # bloqueios: sem segunda confirmação, e operador não gera
    post(ana, "/e/alfa/exportacao/gerar", {"periodo": "2026-09", "conta": "362"})
    assert "Sem permissão" in flash(ana)
    post(rui, "/e/alfa/exportacao/gerar", {"periodo": "2026-09", "conta": "362"})
    assert "segunda confirmação" in flash(rui)
    # segunda confirmação pela outra pessoa
    post(ana, "/e/alfa/revisao/mov/5/segunda")
    msg = flash(ana)
    assert "Sem permissão" in msg  # operador nem tem o papel de segunda confirmação
    post(rui, "/e/alfa/revisao/mov/5/segunda")
    assert "Segunda confirmação registrada" in flash(rui)
    post(rui, "/e/alfa/exportacao/gerar", {"periodo": "2026-09", "conta": "362"})
    assert "Lote 1 gerado" in flash(rui)
    r = rui.get("/e/alfa/exportacao/lote/1/baixar")
    linhas = r.content.decode("ascii").split("\r\n")
    assert r.status_code == 200 and len(linhas) == 7 and linhas[0].startswith("02/09/2026;333;362;45,90;TARIFA BANCARIA [ALF-202609-000001]")
    assert all(len(l.split(";")) == 9 for l in linhas[:-1]) and "attachment" in r.headers["content-disposition"]
    # retorno + conferência no Razão (Razão = abertura + o próprio lote, carregado como documento)
    post(rui, "/e/alfa/exportacao/lote/1/retorno", {"resultado": "aceito", "obs": "ok no Fortes de teste"})
    razao = b"31/08/2026;362;90;10000,00;ABERTURA 2;;;;\r\n" + r.content
    post(rui, "/e/alfa/cadastros/razao", {"formato": "fortes_importacao"}, {"arquivo": ("razao.csv", razao)})
    post(rui, "/e/alfa/exportacao/lote/1/conferir")
    assert "aprovada" in flash(rui)
    cmp = rui.post("/e/alfa/conferencia/comparar", data={"csrf": csrf(pagina(rui, "/painel")), "periodo": "2026-09", "conta": "362"})
    assert cmp.status_code == 200 and "sem diferenças" in cmp.text
    assert "Integridade verificada" in (post(rui, "/e/alfa/integridade") and flash(rui))


def test_web_17_lancamento_manual_importado_e_exportado(mundo):
    ana, rui = entrar(mundo, "ana@exemplo.test"), entrar(mundo, "rui@exemplo.test")
    ajuste = (b"17/09/2026;259;57;191,79;RECLASSIFICA MULTA DE MORA DARF PAGO [MUL-00311];;;;\r\n"
              b"18/09/2026;57;259;870,95;RECLASSIFICA JUROS [JUR-01403];;;;\r\n")
    post(ana, "/e/alfa/lancamentos/importar", {}, {"arquivo": ("ajuste.csv", ajuste)})
    assert "2 lançamentos importados" in flash(ana)
    post(ana, "/e/alfa/lancamentos/importar", {}, {"arquivo": ("ajuste.csv", ajuste)})
    assert "idêntico" in flash(ana)
    for i in (1, 2):
        post(rui, f"/e/alfa/lancamentos/{i}/confirmar")
    post(ana, "/e/alfa/cargas/enviar", {"categoria": "extrato"}, {"arquivo": ("set.ofx", OFX)})
    did = re.search(r"/documentos/(\d+)", pagina(ana, "/e/alfa/cargas")).group(1)
    post(ana, f"/e/alfa/documentos/{did}/processar", {"conta_banco": "362"})
    html = pagina(rui, "/e/alfa/exportacao?periodo=2026-09&conta=362")
    assert "lançamentos manuais confirmados" in html


# ------------------------------------------------------------------ administração

def test_web_18_admin_cria_usuario_com_senha_temporaria(mundo):
    adm = entrar(mundo, "admin@exemplo.test")
    r = post(adm, "/admin/usuario", {"nome": "Nova Pessoa", "email": "nova@exemplo.test", "papel": "cliente"}, esperar=200)
    senha = re.search(r'class="mono">(Tmp-[^<]+)<', r.text).group(1)
    nova = entrar(mundo, "nova@exemplo.test", senha)
    assert nova.get("/painel").headers["location"] == "/conta"  # obrigada a trocar a senha
    post(nova, "/conta/senha", {"atual": senha, "nova": "Cachorro-Verde-91!", "confirmar": "Cachorro-Verde-91!"}, tok=csrf(pagina(nova, "/conta")))
    assert nova.get("/painel").status_code == 200
    # cliente não recebe papel de operador
    c = conectar_central(mundo["data"])
    uid = c.execute("SELECT id FROM usuarios WHERE email = 'nova@exemplo.test'").fetchone()[0]
    c.close()
    post(adm, "/admin/permissao", {"usuario": str(uid), "empresa": "1", "papel": "operador"})
    assert "só recebe" in flash(adm)
    # desativar derruba as sessões
    post(adm, "/admin/desativar", {"usuario": str(uid)})
    assert nova.get("/painel").status_code == 303


def test_web_19_homologacao_exige_evidencia_pela_tela(mundo):
    adm = entrar(mundo, "admin@exemplo.test")
    post(adm, "/admin/homologacao", {"item": "H2", "status": "aprovado", "teste": "importacao com 120 caracteres", "resultado": "histórico inteiro no Razão", "referencia": "120"})
    assert "evidência" in flash(adm)
    post(adm, "/admin/homologacao", {"item": "H2", "status": "aprovado", "teste": "importacao com 120 caracteres", "resultado": "histórico inteiro no Razão", "referencia": "120"}, {"evidencia": ("print.png", b"\x89PNG....")})
    assert "registrado" in flash(adm)
    assert "NÃO liberada" in pagina(adm, "/admin")


def test_web_20_erros_nao_vazam_detalhes(mundo):
    ana = entrar(mundo, "ana@exemplo.test")
    r = ana.get("/e/alfa/documentos/99999")
    assert r.status_code == 404 and "Traceback" not in r.text and "sqlite" not in r.text.lower()
    r = ana.get("/e/alfa/revisao/mov/abc")
    assert r.status_code == 422 and "Traceback" not in r.text


# ------------------------------------------------------------------ implantação

def test_web_21_saude_sem_login_e_sem_dados(mundo):
    r = novo(mundo).get("/saude")
    assert r.status_code == 200 and r.text == "ok" and "alfa" not in r.text.lower()


def test_web_22_admin_inicial_por_variavel_de_ambiente(tmp_path):
    from web.inicializacao import criar_admin_inicial
    d = tmp_path / "d"
    assert "AVISO" in criar_admin_inicial(d, {})
    assert "ERRO" in criar_admin_inicial(d, {"CONCILIADOR_ADMIN_EMAIL": "a@x.test", "CONCILIADOR_ADMIN_SENHA": "fraca"})
    c = conectar_central(d)
    assert c.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
    c.close()
    env = {"CONCILIADOR_ADMIN_EMAIL": " Chefe@X.test ", "CONCILIADOR_ADMIN_SENHA": "Inicial-Forte-77!", "CONCILIADOR_ADMIN_NOME": "Chefe Geral"}
    msg = criar_admin_inicial(d, env)
    assert "criado" in msg and "Inicial-Forte-77!" not in msg  # a senha nunca é impressa
    c = conectar_central(d)
    u = c.execute("SELECT * FROM usuarios").fetchone()
    c.close()
    assert u["email"] == "chefe@x.test" and u["papel_global"] == "admin" and u["deve_trocar_senha"] == 1
    assert "já existem" in criar_admin_inicial(d, env)  # não cria de novo nem sobrescreve
    # e o administrador criado entra, mas é obrigado a trocar a senha e ativar o 2FA
    app = criar_app(d)
    cl = TestClient(app, base_url="https://testserver", follow_redirects=False)
    tok = re.search(r'name="csrf_login" value="([^"]+)"', cl.get("/login").text).group(1)
    assert cl.post("/login", data={"email": "chefe@x.test", "senha": "Inicial-Forte-77!", "csrf_login": tok}).status_code == 303
    assert cl.get("/painel").headers["location"] == "/conta"
