"""Orquestra as etapas: classifica cada transação e monta os lançamentos."""

from collections import Counter
from decimal import Decimal

from .modelos import (
    ORIGEM_IA, ORIGEM_PENDENTE, ORIGEM_REGRA,
    STATUS_CLASSIFICADO, STATUS_PENDENTE, STATUS_REVISAR,
    Lancamento, Transacao,
)
from .regras import Configuracao, regras_que_casam


class ErroIntegridade(Exception):
    """Os lançamentos gerados não batem com o extrato."""


def _montar(t: Transacao, config: Configuracao, contrapartida: str, **campos) -> Lancamento:
    """Partidas dobradas: entrada debita o banco; saída credita o banco."""
    if t.valor > 0:
        debito, credito = config.conta_banco, contrapartida
    else:
        debito, credito = contrapartida, config.conta_banco
    return Lancamento(
        data=t.data, conta_debito=debito, conta_credito=credito, valor=abs(t.valor),
        documento=t.documento, linha_extrato=t.linha, **campos,
    )


def conciliar(transacoes: list[Transacao], config: Configuracao, sugestoes_ia=None) -> list[Lancamento]:
    """Gera um lançamento para cada transação, sem descartar nenhuma.

    `sugestoes_ia` é o dicionário devolvido por ia.sugerir_contas (ou None).
    """
    sugestoes_ia = sugestoes_ia or {}
    repeticoes = Counter((t.data, t.descricao, t.valor) for t in transacoes)
    lancamentos = []

    for t in transacoes:
        observacoes = []
        if repeticoes[(t.data, t.descricao, t.valor)] > 1:
            observacoes.append("Possível duplicidade: mesma data, descrição e valor em outra linha.")

        casadas = regras_que_casam(t, config.regras)
        if casadas:
            regra = casadas[0]
            status = STATUS_REVISAR if regra.revisar else STATUS_CLASSIFICADO
            if regra.revisar:
                observacoes.append(f"Regra '{regra.nome}' é genérica: confirmar a natureza.")
            concorrentes = sorted({r.nome for r in casadas[1:] if r.conta != regra.conta})
            if concorrentes:
                status = STATUS_REVISAR
                observacoes.append(
                    f"Conflito: também casa com {', '.join(concorrentes)}. Aplicada '{regra.nome}'."
                )
            historico = t.descricao
            if regra.historico and regra.historico.lower() != t.descricao.lower():
                historico = f"{regra.historico} - {t.descricao}"
            lancamento = _montar(t, config, regra.conta, historico=historico,
                                 origem=ORIGEM_REGRA, status=status)
        elif t.linha in sugestoes_ia:
            sugestao = sugestoes_ia[t.linha]
            observacoes.append(
                f"Sugestão da IA (confiança {sugestao['confianca']}): {sugestao['justificativa']}"
            )
            lancamento = _montar(t, config, sugestao["conta"], historico=t.descricao,
                                 origem=ORIGEM_IA, status=STATUS_REVISAR)
        else:
            observacoes.append("Nenhuma regra aplicável: classificar manualmente.")
            lancamento = _montar(t, config, config.conta_transitoria, historico=t.descricao,
                                 origem=ORIGEM_PENDENTE, status=STATUS_PENDENTE)

        lancamento.observacao = " ".join(observacoes)
        lancamentos.append(lancamento)

    verificar_integridade(transacoes, lancamentos, config)
    return lancamentos


def verificar_integridade(transacoes, lancamentos, config: Configuracao) -> Decimal:
    """Prova de que nada se perdeu: o movimento líquido da conta banco nos
    lançamentos tem de ser igual à soma do extrato."""
    if len(transacoes) != len(lancamentos):
        raise ErroIntegridade(f"{len(transacoes)} transações geraram {len(lancamentos)} lançamentos.")
    soma_extrato = sum((t.valor for t in transacoes), Decimal(0))
    debitos = sum((l.valor for l in lancamentos if l.conta_debito == config.conta_banco), Decimal(0))
    creditos = sum((l.valor for l in lancamentos if l.conta_credito == config.conta_banco), Decimal(0))
    if debitos - creditos != soma_extrato:
        raise ErroIntegridade(
            f"Movimento do banco nos lançamentos ({debitos - creditos}) difere do extrato ({soma_extrato})."
        )
    return soma_extrato
