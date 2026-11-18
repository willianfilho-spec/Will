"""Peças compartilhadas pelas telas."""

from __future__ import annotations

from contextlib import contextmanager

import pandas as pd
import streamlit as st

from domain import operacoes as o
from domain.money import ValorInvalido, formatar_br, para_centavos
from exporters.fortes_exporter import LoteBloqueado
from parsers.comum import ErroEstrutural
from storage.usuarios import AcessoNegado, pode

STATUS_ROTULO = {
    "pendente": "Sem regra", "proposto": "Proposto por regra", "classificado": "Classificado",
    "em_espera": "Em espera", "exportado": "Exportado", "descartado": "Descartado",
}


def ctx() -> o.Contexto | None:
    return st.session_state.get("_ctx")


def pode_fazer(acao: str) -> bool:
    c = ctx()
    return bool(c) and pode(c.central, c.usuario["id"], c.empresa["id"], acao)


@contextmanager
def tratar_erros(sucesso: str | None = None):
    """Mostra erros de negócio de forma legível em vez de stack trace."""
    try:
        yield
    except (ErroEstrutural, LoteBloqueado) as exc:
        st.error("**Bloqueado.** Corrija os itens abaixo:")
        st.markdown("\n".join(f"- {p}" for p in exc.problemas[:100]))
    except AcessoNegado as exc:
        st.error(f"Sem permissão: {exc}")
    except (o.OperacaoInvalida, ValorInvalido, ValueError) as exc:
        st.error(str(exc))
    else:
        if sucesso:
            st.session_state["_aviso"] = sucesso
            st.rerun()


def aviso_pendente() -> None:
    msg = st.session_state.pop("_aviso", None)
    if msg:
        st.success(msg)


def campo_valor(rotulo: str, chave: str, padrao: int | None = None) -> int | None:
    texto = st.text_input(rotulo, value=formatar_br(padrao, simbolo=False) if padrao is not None else "",
                          key=chave, placeholder="0,00")
    if not texto.strip():
        return None
    try:
        return para_centavos(texto)
    except ValorInvalido as exc:
        st.warning(f"{rotulo}: {exc}")
        return None


def opcoes_contas() -> dict[str, str]:
    """reduzido -> rótulo legível."""
    return {r["reduzido"]: f"{r['reduzido']} · {r['classificacao']} · {r['descricao']}"
            for r in o.contas_analiticas(ctx().con)}


def seletor_conta(rotulo: str, chave: str, padrao: str | None = None, excluir: str | None = None) -> str | None:
    opcoes = {k: v for k, v in opcoes_contas().items() if k != excluir}
    if not opcoes:
        st.info("Importe o plano de contas do Fortes em **Cadastros** primeiro.")
        return None
    chaves = list(opcoes)
    idx = chaves.index(padrao) if padrao in chaves else None
    return st.selectbox(rotulo, chaves, index=idx, format_func=lambda k: opcoes[k], key=chave,
                        placeholder="Digite para buscar a conta")


def conta_banco_padrao() -> str | None:
    from storage.database import parametro
    return parametro(ctx().con, "conta_banco_padrao")


def tabela_movimentos(linhas, extra: list[str] | None = None) -> pd.DataFrame:
    cols = ["id", "data", "valor", "historico", "status", "conta_debito", "conta_credito", "natureza",
            "motivos_risco", "revisado_por", "segunda_confirmacao_por", "observacao"] + (extra or [])
    dados = []
    for r in linhas:
        d = dict(r)
        d["valor"] = formatar_br(d["valor_centavos"], simbolo=False)
        d["status"] = STATUS_ROTULO.get(d["status"], d["status"])
        dados.append({c: d.get(c) for c in cols})
    return pd.DataFrame(dados, columns=cols)


def exigir_contexto() -> o.Contexto:
    c = ctx()
    if c is None:
        st.warning("Escolha a empresa ativa na barra lateral.")
        st.stop()
    return c


def abas(rotulos: list[str], chave: str, formatar=None) -> str:
    """Abas que sobrevivem ao recarregamento da página (st.tabs volta para a primeira)."""
    escolha = st.segmented_control(" ", rotulos, key=chave, default=rotulos[0], format_func=formatar,
                                   label_visibility="collapsed")
    return escolha or rotulos[0]
