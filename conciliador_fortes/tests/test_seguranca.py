import time

import pytest

import config
from storage import usuarios
from storage.database import conectar_central
from web import seguranca as sg


@pytest.fixture
def central(tmp_path):
    c = conectar_central(tmp_path)
    usuarios.criar_usuario(c, "Ana Souza", "ana@exemplo.test", "Segredo!Forte9", "equipe")
    yield c
    c.close()


def test_sec_01_politica_de_senha():
    sg.validar_politica_senha("Cavalo-Azul-42!", "x@y.z", "Beto")
    for ruim in ("curta1A!", "senha12345", "aaaaaaaaaaaa", "somenteminusculas", "ana.souza123ABC"):
        with pytest.raises(ValueError, match="Senha fraca"):
            sg.validar_politica_senha(ruim, "ana.souza@exemplo.test", "Ana")


def test_sec_02_bloqueio_por_falhas_sem_revelar_conta(central):
    for _ in range(config.MAX_FALHAS_LOGIN):
        u, msg = sg.tentar_login(central, "ana@exemplo.test", "errada", "10.0.0.1")
        assert u is None and msg == "E-mail ou senha incorretos."
    u, msg = sg.tentar_login(central, "ana@exemplo.test", "Segredo!Forte9", "10.0.0.2")
    assert u is None and "Muitas tentativas" in msg  # nem a senha certa entra durante o bloqueio
    sg.desbloquear_usuario(central, "ana@exemplo.test")
    assert sg.tentar_login(central, "ana@exemplo.test", "Segredo!Forte9", "10.0.0.2")[0] is not None
    # e-mail inexistente recebe exatamente a mesma resposta
    assert sg.tentar_login(central, "ninguem@exemplo.test", "x", "10.0.0.3")[1] == "E-mail ou senha incorretos."


def test_sec_03_sessao_expira_por_inatividade_e_tempo_total(central, monkeypatch):
    uid = central.execute("SELECT id FROM usuarios").fetchone()[0]
    token, _ = sg.criar_sessao(central, uid, True, "1.1.1.1")
    assert sg.obter_sessao(central, token) is not None
    assert sg.obter_sessao(central, token + "x") is None and sg.obter_sessao(central, None) is None
    # o banco não guarda o token em claro
    assert central.execute("SELECT COUNT(*) FROM sessoes WHERE token_hash = ?", (token,)).fetchone()[0] == 0
    real = time.time()
    monkeypatch.setattr(time, "time", lambda: real + config.SESSAO_OCIOSA_SEG + 5)
    assert sg.obter_sessao(central, token) is None
    monkeypatch.setattr(time, "time", lambda: real)
    t2, _ = sg.criar_sessao(central, uid, True, "1.1.1.1")
    central.execute("UPDATE sessoes SET expira_em = ?", (real - 1,))
    assert sg.obter_sessao(central, t2) is None


def test_sec_04_totp_rfc6238_e_sem_reuso():
    # vetor de teste da RFC 6238 (SHA-1, segredo ASCII "12345678901234567890", T = 59 s -> 94287082; 6 dígitos = 287082)
    import base64
    seg = base64.b32encode(b"12345678901234567890").decode()
    assert sg._codigo(seg, 59 // 30) == "287082"
    assert sg._codigo(seg, 1111111109 // 30) == "081804"
    t = 1_700_000_000
    cod = sg._codigo(seg, sg.passo_atual(t))
    p = sg.verificar_totp(seg, cod, 0, t)
    assert p == sg.passo_atual(t)
    assert sg.verificar_totp(seg, cod, p, t) is None  # reuso
    assert sg.verificar_totp(seg, "000000", 0, t) is None and sg.verificar_totp(seg, "abc", 0, t) is None
    assert sg.verificar_totp(seg, sg._codigo(seg, sg.passo_atual(t) + 5), 0, t) is None  # fora da janela


def test_sec_05_2fa_codigos_de_recuperacao_uso_unico(central):
    uid = central.execute("SELECT id FROM usuarios").fetchone()[0]
    seg = sg.novo_segredo()
    codigos = sg.ativar_totp(central, uid, seg)
    u = central.execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
    assert u["totp_ativo"] == 1 and seg not in u["totp_segredo"] or u["totp_segredo"].startswith("claro:")
    assert sg.segredo_do_usuario(u) == seg and len(codigos) == 8
    assert sg.usar_codigo_recuperacao(central, uid, codigos[0]) is True
    assert sg.usar_codigo_recuperacao(central, uid, codigos[0]) is False
    assert sg.usar_codigo_recuperacao(central, uid, "0000-0000-0000") is False


def test_sec_06_promover_sessao_troca_o_token(central):
    uid = central.execute("SELECT id FROM usuarios").fetchone()[0]
    token, _ = sg.criar_sessao(central, uid, False, "1.1.1.1")
    s = sg.obter_sessao(central, token)
    novo = sg.promover_sessao(central, s, "1.1.1.1")
    assert sg.obter_sessao(central, token) is None and sg.obter_sessao(central, novo).mfa_ok is True


def test_sec_07_limite_de_requisicoes():
    l = sg.LimiteRequisicoes()
    assert all(l.permitir("a", 3, 60) for _ in range(3)) and not l.permitir("a", 3, 60) and l.permitir("b", 3, 60)


def test_sec_08_cliente_so_recebe_papel_cliente(central):
    cid = usuarios.criar_usuario(central, "Cli", "cli@exemplo.test", "Segredo!Forte9", "cliente")
    central.execute("INSERT INTO empresas (slug, razao_social, cnpj) VALUES ('zeta', 'Zeta', '33333333000133')")
    eid = central.execute("SELECT id FROM empresas").fetchone()[0]
    with pytest.raises(ValueError, match="só recebe"):
        usuarios.conceder(central, cid, eid, "operador")
    uid = central.execute("SELECT id FROM usuarios WHERE papel_global = 'equipe'").fetchone()[0]
    with pytest.raises(ValueError, match="só recebe"):
        usuarios.conceder(central, uid, eid, "cliente")
    usuarios.conceder(central, cid, eid, "cliente")
