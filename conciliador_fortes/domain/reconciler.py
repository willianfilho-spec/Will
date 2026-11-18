"""Conferência de saldos: extrato x contabilidade, por mês e conta bancária.

Duas contas são feitas:
- coerência do extrato: saldo inicial + movimentação = saldo final informado;
- batimento contábil: saldo final do extrato x saldo do banco no Razão,
  somado aos lançamentos classificados aqui que ainda não estão no Razão
  (reconhecidos pela marca [PREFIXO-AAAAMM-ID] no histórico).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Conferencia:
    periodo: str
    conta_banco: str
    saldo_inicial_extrato: int
    movimentacao_extrato: int
    saldo_final_extrato: int
    diferenca_interna_extrato: int      # != 0: faltam movimentos ou saldo informado errado
    saldo_razao: int                    # saldo da conta banco no Razão até o fim do período
    pendentes_fora_do_razao: int        # movimentos classificados ainda não importados
    saldo_final_contabil: int           # razão + pendentes
    diferenca_centavos: int             # extrato - contábil
    movimentos_sem_classificacao: int

    @property
    def fecha(self) -> bool:
        return self.diferenca_interna_extrato == 0 and self.diferenca_centavos == 0


def conferir(periodo: str, conta_banco: str, saldo_inicial: int, saldo_final: int,
             valores_movimentos: list[int], saldo_razao: int, pendentes_fora_do_razao: int,
             sem_classificacao: int) -> Conferencia:
    mov = sum(valores_movimentos)
    contabil = saldo_razao + pendentes_fora_do_razao
    return Conferencia(
        periodo=periodo,
        conta_banco=conta_banco,
        saldo_inicial_extrato=saldo_inicial,
        movimentacao_extrato=mov,
        saldo_final_extrato=saldo_final,
        diferenca_interna_extrato=saldo_final - (saldo_inicial + mov),
        saldo_razao=saldo_razao,
        pendentes_fora_do_razao=pendentes_fora_do_razao,
        saldo_final_contabil=contabil,
        diferenca_centavos=saldo_final - contabil,
        movimentos_sem_classificacao=sem_classificacao,
    )
