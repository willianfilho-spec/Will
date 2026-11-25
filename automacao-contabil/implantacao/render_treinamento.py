"""Executa somente a base fictícia no Render, atrás do Cloudflare Access."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse

from motor_contabil import acesso, empresas


RAIZ = Path(__file__).resolve().parents[1]


class ExigirAcesso:
    """Verifica a sessão antes de entregar HTTP, arquivos ou WebSockets do app."""

    def __init__(self, app, config: acesso.ConfigAcesso):
        self.app = app
        self.config = config

    async def __call__(self, scope, receive, send):
        tipo = scope["type"]
        if tipo not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        if tipo == "http" and scope["path"] == "/saude-render" and scope["method"] in {"GET", "HEAD"}:
            await PlainTextResponse("ok")(scope, receive, send)
            return

        cabecalhos = {chave.decode("latin-1"): valor.decode("latin-1") for chave, valor in scope["headers"]}
        try:
            await run_in_threadpool(acesso.identificar, cabecalhos, self.config)
        except acesso.AcessoNegado:
            if tipo == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await PlainTextResponse("Acesso autorizado necessário.", status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def criar_exemplo(dados: Path) -> None:
    exemplos = RAIZ / "exemplos" / "fortes"
    empresa = empresas.cadastrar(
        dados, "demo", "EMPRESA FICTÍCIA DE TREINAMENTO", "00.000.000/0001-91", "362", "EX",
        "fortes", exemplos / "plano_contas_fortes.csv", exemplos / "regras_fortes.json",
    )
    motor = empresa.abrir_motor("treinamento")
    try:
        motor.importar(exemplos / "extrato_exemplo.ofx", empresa.conta_bancaria)
    finally:
        motor.banco.fechar()


def executar() -> None:
    config = acesso.carregar_config(os.environ["MOTOR_CONTABIL_ACESSO"])
    if not config.remoto or config.acesso_local_sem_login:
        raise ValueError("O Render exige Cloudflare Access e login para todas as sessões.")
    with tempfile.TemporaryDirectory(prefix="conciliador-treinamento-") as pasta:
        os.environ["MOTOR_CONTABIL_TREINAMENTO"] = "1"
        os.environ["MOTOR_CONTABIL_DADOS"] = pasta
        os.environ.pop("MOTOR_CONTABIL_BACKUP", None)
        criar_exemplo(Path(pasta))
        app = st.App(RAIZ / "app.py", middleware=[Middleware(ExigirAcesso, config=config)])
        app.run(config={
            "server.address": "0.0.0.0",
            "server.port": int(os.environ.get("PORT", "10000")),
            "server.headless": True,
            "server.fileWatcherType": "none",
            "browser.serverAddress": os.environ["CONCILIADOR_HOST_PUBLICO"],
            "browser.serverPort": 443,
            "client.showErrorDetails": "none",
        })


if __name__ == "__main__":
    executar()
