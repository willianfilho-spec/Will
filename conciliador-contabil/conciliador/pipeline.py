"""Orquestra as etapas: confere saldo, classifica e aplica a revisão manual."""

from collections import Counter
from decimal import Decimal

from .leitor import converter_data, converter_valor
from .modelos import (
    ORIGEM_IA, ORIGEM_MANUAL, ORIGEM_PENDENTE, ORIGEM_REGRA,
    STATUS_APROVADO, STATUS_CLASSIFICADO, STATUS_PENDENTE, STATUS_REVISAR,
    Extrato, Lancamento, Transacao,
)
from .regras import Configuracao, regras_que_casam


class ErroIntegridade(Exception):
    """Os números não fecham: saldo do extrato ou lançamentos gerados."""


class ErroRevisao(Exception):
    """A planilha de revisão tem aprovações que não podem ser aceitas."""


def conferir_saldo(extrato: Extrato, saldo_inicial=None, saldo_final=None) -> str:
    """Saldo inicial + movimentos tem de dar o saldo final.

    Os saldos vêm das linhas "SALDO ANTERIOR"/"SALDO FINAL" do arquivo ou dos
    parâmetros. Divergência interrompe tudo: indica linha faltando ou a mais.
    Devolve uma frase descrevendo o resultado.
    """
    inicial = saldo_inicial if saldo_inicial is not None else extrato.saldo_inicial
    final = saldo_final if saldo_final is not None else extrato.saldo_final
    movimento = sum((t.valor for t in extrato.transacoes), Decimal(0))
    if inicial is None or final is None:
        faltam = " e ".join(n for n, v in (("inicial", inicial), ("final", final)) if v is None)
        return f"NÃO CONFERIDO (saldo {faltam} não informado; use --saldo-inicial e --saldo-final)"
    if inicial + movimento != final:
        raise ErroIntegridade(
            f"Saldo não fecha: inicial {inicial:.2f} + movimentos {movimento:.2f} = "
            f"{inicial + movimento:.2f}, mas o saldo final informado é {final:.2f} "
            f"(diferença {final - inicial - movimento:.2f}). Verifique linhas faltando ou repetidas."
        )
    return f"CONFERE ({inicial:.2f} + {movimento:.2f} = {final:.2f})"


def _montar(t: Transacao, config: Configuracao, contrapartida: str, **campos) -> Lancamento:
    """Partidas dobradas: entrada debita o banco; saída credita o banco."""
    if t.valor > 0:
        debito, credito = config.conta_banco, contrapartida
    else:
        debito, credito = contrapartida, config.conta_banco
    return Lancamento(
        data=t.data, conta_debito=debito, conta_credito=credito, valor=abs(t.valor),
        documento=t.documento, linha_extrato=t.linha, descricao_extrato=t.descricao, **campos,
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
        duplicidade = repeticoes[(t.data, t.descricao, t.valor)] > 1
        if duplicidade:
            observacoes.append("Possível duplicidade: mesma data, descrição e valor em outra linha.")

        casadas = regras_que_casam(t, config.regras)
        if casadas:
            regra = casadas[0]
            status = STATUS_REVISAR if regra.revisar or duplicidade else STATUS_CLASSIFICADO
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
            lancamento = _montar(t, config, regra.conta, historico=historico, origem=ORIGEM_REGRA,
                                 status=status, regra=regra.nome, fornecedor=regra.fornecedor)
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


def aplicar_revisao(lancamentos: list[Lancamento], linhas_revisao: list[dict], config: Configuracao) -> list[dict]:
    """Aplica as linhas marcadas como APROVADO na planilha de revisão.

    A pessoa pode ter trocado conta de débito, conta de crédito e histórico.
    Data e valor nunca são alterados: vêm do extrato. Devolve a lista de
    alterações feitas, para o registro de auditoria.
    """
    por_linha = {l.linha_extrato: l for l in lancamentos}
    alteracoes, erros = [], []

    for registro in linhas_revisao:
        if (registro.get("status") or "").strip().upper() != STATUS_APROVADO:
            continue
        rotulo = f"linha {registro.get('linha_extrato')}"
        try:
            lancamento = por_linha[int(str(registro.get("linha_extrato")).strip())]
            mesma_origem = (
                converter_data(registro.get("data")) == lancamento.data
                and abs(converter_valor(registro.get("valor"))) == lancamento.valor
            )
        except (KeyError, ValueError):
            erros.append(f"{rotulo}: não existe neste extrato")
            continue
        if not mesma_origem:
            erros.append(f"{rotulo}: data ou valor diferem do extrato (a revisão é de outro arquivo?)")
            continue

        debito = (registro.get("conta_debito") or "").strip()
        credito = (registro.get("conta_credito") or "").strip()
        historico = (registro.get("historico") or "").strip()
        entrada = lancamento.conta_debito == config.conta_banco
        lado_banco, contrapartida = (debito, credito) if entrada else (credito, debito)
        if lado_banco != config.conta_banco:
            lado = "débito" if entrada else "crédito"
            erros.append(f"{rotulo}: a conta do banco ({config.conta_banco}) deve permanecer no {lado}")
        elif contrapartida not in config.plano:
            erros.append(f"{rotulo}: conta '{contrapartida}' não existe no plano de contas")
        elif contrapartida in (config.conta_transitoria, config.conta_banco):
            erros.append(f"{rotulo}: aprovado sem contrapartida definitiva ({contrapartida})")
        elif not historico:
            erros.append(f"{rotulo}: histórico vazio")
        else:
            antes = (lancamento.conta_debito, lancamento.conta_credito, lancamento.historico)
            mudou = antes != (debito, credito, historico)
            alteracoes.append({
                "linha_extrato": lancamento.linha_extrato,
                "status_anterior": lancamento.status,
                "origem_anterior": lancamento.origem,
                "alterado_manualmente": mudou,
                "antes": dict(zip(("conta_debito", "conta_credito", "historico"), antes)),
                "depois": {"conta_debito": debito, "conta_credito": credito, "historico": historico},
            })
            lancamento.conta_debito, lancamento.conta_credito, lancamento.historico = debito, credito, historico
            lancamento.status = STATUS_APROVADO
            if mudou:
                lancamento.origem = ORIGEM_MANUAL

    if erros:
        raise ErroRevisao("Aprovações recusadas na planilha de revisão:\n  " + "\n  ".join(erros))
    return alteracoes


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
