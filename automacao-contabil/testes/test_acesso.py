"""Identificação por login Google via Cloudflare Access (tokens assinados no próprio teste)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

jwt = pytest.importorskip("jwt")
rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

from motor_contabil.acesso import (  # noqa: E402
    AcessoNegado, ConfigAcesso, Identidade, carregar_config, identificar,
)

EQUIPE = "exemplo-invalido.cloudflareaccess.com"
AUD = "aud-teste-123"
CFG = ConfigAcesso("cloudflare", EQUIPE, AUD, {"revisora@example.test": "Revisora"})
CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OUTRA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLICA = lambda token, cfg: CHAVE.public_key()  # noqa: E731
APP = Path(__file__).resolve().parent.parent / "app.py"


def token(email="revisora@example.test", aud=AUD, iss=f"https://{EQUIPE}",
          validade=600, chave=CHAVE):
    agora = int(time.time())
    return jwt.encode({"email": email, "aud": [aud], "iss": iss, "iat": agora, "exp": agora + validade},
                      chave, algorithm="RS256")


def cab(tk=None, host="conciliador.example.test"):
    h = {"Host": host}
    if tk:
        h["Cf-Access-Jwt-Assertion"] = tk
    return h


def test_sem_arquivo_e_modo_local():
    assert carregar_config(None) == ConfigAcesso()
    assert identificar(cab(), ConfigAcesso()) is None


def test_token_valido_de_email_autorizado():
    ident = identificar(cab(token()), CFG, PUBLICA)
    assert ident == Identidade("Revisora", "revisora@example.test", True)
    assert ident.para_auditoria == "Revisora <revisora@example.test>"


def test_email_com_maiusculas_e_aceito():
    assert identificar(cab(token("Revisora@example.test")), CFG, PUBLICA).autenticado


@pytest.mark.parametrize("tk, trecho", [
    (lambda: token(validade=-10), "sessão expirou"),
    (lambda: token(aud="outra-aplicacao"), "confirmar o login"),
    (lambda: token(iss="https://intruso.cloudflareaccess.com"), "confirmar o login"),
    (lambda: token(chave=OUTRA), "confirmar o login"),
    (lambda: "nao-e-um-token", "confirmar o login"),
    (lambda: token("intruso@example.test"), "não está autorizada"),
])
def test_token_recusado(tk, trecho):
    with pytest.raises(AcessoNegado, match=trecho):
        identificar(cab(tk()), CFG, PUBLICA)


def test_sem_token_vindo_de_fora_e_recusado():
    with pytest.raises(AcessoNegado, match="Acesso sem login"):
        identificar(cab(), CFG, PUBLICA)


@pytest.mark.parametrize("host", ["localhost:8501", "127.0.0.1:8501", "[::1]:8501", "localhost"])
def test_sem_token_no_proprio_computador_pede_nome(host):
    assert identificar(cab(host=host), CFG, PUBLICA) is None
    assert Identidade("Ana", None, False).para_auditoria == "Ana (acesso local, sem login)"


def test_cabecalho_falso_de_email_nao_basta():
    h = cab()
    h["Cf-Access-Authenticated-User-Email"] = "revisora@example.test"
    with pytest.raises(AcessoNegado):
        identificar(h, CFG, PUBLICA)


def test_config_cloudflare_incompleta_e_recusada(tmp_path):
    arq = tmp_path / "acesso.json"
    arq.write_text(json.dumps({"modo": "cloudflare", "dominio_equipe": EQUIPE, "aud": AUD}), encoding="utf-8")
    with pytest.raises(ValueError, match="autorizados"):
        carregar_config(arq)
    arq.write_text(json.dumps({"modo": "cloudflare", "dominio_equipe": "site.com", "aud": AUD,
                               "autorizados": {"a@b.com": "A"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="cloudflareaccess.com"):
        carregar_config(arq)
    arq.write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ValueError, match="5_CONFIGURAR_ACESSO_REMOTO"):
        carregar_config(arq)


def test_config_cloudflare_valida(tmp_path):
    arq = tmp_path / "acesso.json"
    arq.write_text(json.dumps({"modo": "cloudflare", "dominio_equipe": EQUIPE.upper(), "aud": AUD,
                               "autorizados": {" Revisora@example.test ": "Revisora"}}),
                   encoding="utf-8")
    cfg = carregar_config(arq)
    assert cfg.remoto and cfg.dominio_equipe == EQUIPE
    assert cfg.autorizados == {"revisora@example.test": "Revisora"}


def test_interface_remota_sem_login_nao_mostra_dados(monkeypatch, tmp_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    arq = tmp_path / "acesso.json"
    arq.write_text(json.dumps({"modo": "cloudflare", "dominio_equipe": EQUIPE, "aud": AUD,
                               "autorizados": {"revisora@example.test": "Revisora"}}),
                   encoding="utf-8")
    monkeypatch.setenv("MOTOR_CONTABIL_ACESSO", str(arq))
    monkeypatch.setenv("MOTOR_CONTABIL_DADOS", str(tmp_path / "dados"))
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception
    assert any("Acesso sem login" in e.value for e in at.error)
    assert not at.sidebar.selectbox and not at.subheader


def test_assistente_grava_e_mantem_autorizados(tmp_path):
    from motor_contabil.acesso import configurar

    arq = tmp_path / "acesso.json"
    respostas = iter([EQUIPE, AUD, "Revisora@example.test", "Revisora", "nao-e-email",
                      "luciana@example.test", "", ""])
    cfg = configurar(arq, entrada=lambda _: next(respostas), saida=lambda *_: None)
    assert cfg.autorizados == {"revisora@example.test": "Revisora",
                               "luciana@example.test": "luciana@example.test"}
    # Segunda rodada: Enter mantém equipe e AUD; remove a Luciana.
    respostas = iter(["", "", "-luciana@example.test", ""])
    cfg = configurar(arq, entrada=lambda _: next(respostas), saida=lambda *_: None)
    assert cfg.aud == AUD and list(cfg.autorizados) == ["revisora@example.test"]


def test_assistente_nao_grava_configuracao_invalida(tmp_path):
    from motor_contabil.acesso import configurar

    arq = tmp_path / "acesso.json"
    respostas = iter(["site-qualquer.com", AUD, "a@b.com", "A", ""])
    with pytest.raises(ValueError, match=str(arq.name)):
        configurar(arq, entrada=lambda _: next(respostas), saida=lambda *_: None)
    assert not arq.exists() and not arq.with_suffix(".tmp").exists()


def test_interface_com_login_identifica_responsavel_na_auditoria(monkeypatch, tmp_path):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    import motor_contabil.acesso as modulo
    from motor_contabil import empresas

    ex = Path(__file__).resolve().parent.parent / "exemplos" / "fortes"
    dados = tmp_path / "dados"
    emp = empresas.cadastrar(dados, "ex", "EMPRESA EXEMPLO LTDA", "00.000.000/0001-91", "362", "EX",
                             "fortes", ex / "plano_contas_fortes.csv", ex / "regras_fortes.json")
    motor = emp.abrir_motor("x")
    motor.importar(ex / "extrato_exemplo.ofx")
    pendente = next(p for p in motor.listar("pendente") if p["conta_contrapartida"] is None)["chave"]
    motor.banco.fechar()

    arq = tmp_path / "acesso.json"
    arq.write_text(json.dumps({"modo": "cloudflare", "dominio_equipe": EQUIPE, "aud": AUD,
                               "autorizados": {"revisora@example.test": "Revisora"}}),
                   encoding="utf-8")
    # O AppTest não envia cabeçalhos: simula o que a Cloudflare acrescenta a cada acesso.
    original = modulo.identificar
    tk = token()
    monkeypatch.setattr(modulo, "identificar", lambda headers, cfg, obter_chave=None: original(
        cab(tk), cfg, PUBLICA))
    monkeypatch.setenv("MOTOR_CONTABIL_ACESSO", str(arq))
    monkeypatch.setenv("MOTOR_CONTABIL_DADOS", str(dados))
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(APP), default_timeout=60)
    at.run()
    assert not at.exception
    assert not [t for t in at.sidebar.text_input if t.label == "Responsável pela revisão"]
    assert not [t for t in at.text_input if t.label == "Pasta de dados do escritório"]
    assert any("Seu nome e e-mail identificam suas ações no histórico e nos relatórios." == c.value for c in at.sidebar.caption)
    at.selectbox(key=f"conta-{pendente}").set_value("2.01.01.03.01.0010-4").run()
    at.button(key=f"ok-{pendente}").click().run()
    motor = emp.abrir_motor("x")
    quem = motor.banco.conexao.execute(
        "SELECT usuario FROM eventos WHERE acao='aprovado'").fetchone()[0]
    motor.banco.fechar()
    assert quem == "Revisora <revisora@example.test>"


def test_servidor_hospedado_exige_login_ate_de_localhost(tmp_path):
    cfg = ConfigAcesso("cloudflare", EQUIPE, AUD, {"revisora@example.test": "Revisora"}, False)
    with pytest.raises(AcessoNegado, match="Acesso sem login"):
        identificar(cab(host="localhost:8501"), cfg, PUBLICA)
    assert identificar(cab(token(), host="localhost:8501"), cfg, PUBLICA).autenticado
    arq = tmp_path / "acesso.json"
    arq.write_text(json.dumps({"modo": "cloudflare", "dominio_equipe": EQUIPE, "aud": AUD,
                               "autorizados": {"a@b.com": "A"}, "acesso_local_sem_login": False}),
                   encoding="utf-8")
    assert carregar_config(arq).acesso_local_sem_login is False
    arq.write_text(json.dumps({"modo": "cloudflare", "dominio_equipe": EQUIPE, "aud": AUD,
                               "autorizados": {"a@b.com": "A"}, "acesso_local_sem_login": "nao"}),
                   encoding="utf-8")
    with pytest.raises(ValueError, match="true ou false"):
        carregar_config(arq)
