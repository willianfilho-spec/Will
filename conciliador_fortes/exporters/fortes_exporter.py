"""Validador pré-exportação e gerador no leiaute de importação do Fortes.

Leiaute tirado de arquivos reais que o Fortes aceitou no escritório:

    data;debito;credito;valor;historico;;;;

- sem cabeçalho; nove campos separados por ponto e vírgula (quatro vazios no fim);
- data dd/mm/aaaa; contas pelo código reduzido;
- valor positivo, vírgula decimal, sem separador de milhar;
- histórico em maiúsculas, só ASCII, até LIMITE_HISTORICO caracteres,
  terminado pela marca [PREFIXO-AAAAMM-NNNNNN] que identifica o movimento;
- arquivo ASCII com fim de linha CRLF.
- No Fortes, importar com "Desconsiderar Identificador" e "Utilizar Código Reduzido" marcados.

Qualquer falha de validação bloqueia o lote inteiro: nenhum arquivo parcial é
gravado e nenhum movimento muda de estado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import config
from domain.money import formatar_fortes
from parsers.comum import normalizar

CAMPOS_VAZIOS_NO_FIM = 4


class LoteBloqueado(ValueError):
    def __init__(self, problemas: list[str]):
        self.problemas = problemas
        super().__init__("O lote não foi gerado. Corrija e tente de novo:\n- " + "\n- ".join(problemas))


@dataclass(frozen=True)
class ContaPlano:
    reduzido: str
    classificacao: str
    descricao: str
    aceita_lancamento: bool


def marca(prefixo: str, data_iso: str, mov_id: int) -> str:
    return f"[{prefixo}-{data_iso[:4]}{data_iso[5:7]}-{mov_id:06d}]"


def validar_prefixo(prefixo: str) -> str:
    if not re.fullmatch(r"[A-Z0-9]{2,6}", prefixo or ""):
        raise ValueError("o prefixo da marca deve ter de 2 a 6 letras maiúsculas ou números")
    return prefixo


def historico_ascii(texto: str) -> str:
    t = normalizar(texto).replace(";", ",")
    t = t.encode("ascii", "replace").decode("ascii").replace("?", " ")
    t = "".join(c for c in t if 32 <= ord(c) < 127)
    return re.sub(r"\s+", " ", t).strip()


def montar_historico(texto: str, m: str, limite: int = config.LIMITE_HISTORICO) -> str:
    espaco = limite - len(m) - 1
    return f"{historico_ascii(texto)[:espaco].rstrip()} {m}".strip()


def validar(movimentos: list[dict], plano: dict[str, ContaPlano], conciliacao: dict | None) -> list[str]:
    """Todas as regras bloqueantes. Devolve a lista de problemas (vazia = pode exportar)."""
    problemas: list[str] = []
    if not movimentos:
        problemas.append("nenhum movimento classificado para exportar no período")
    for m in movimentos:
        ref = f"movimento {m['id']} de {date.fromisoformat(m['data']).strftime('%d/%m/%Y')}"
        # partidas íntegras
        if not m.get("conta_debito") or not m.get("conta_credito"):
            problemas.append(f"{ref}: sem conta de débito ou de crédito")
        elif m["conta_debito"] == m["conta_credito"]:
            problemas.append(f"{ref}: débito igual a crédito ({m['conta_debito']})")
        if abs(m["valor_centavos"]) <= 0:
            problemas.append(f"{ref}: valor menor ou igual a zero")
        # contas válidas
        for papel in ("conta_debito", "conta_credito"):
            red = m.get(papel)
            if not red:
                continue
            conta = plano.get(str(red))
            if conta is None:
                problemas.append(f"{ref}: conta {red} ({papel[6:]}) não existe no plano vigente")
            elif not conta.aceita_lancamento:
                problemas.append(f"{ref}: conta {red} ({papel[6:]}) é sintética e não aceita lançamento")
        # segregação de função
        if m.get("exige_segunda_confirmacao"):
            if not m.get("segunda_confirmacao_por"):
                problemas.append(f"{ref}: exige segunda confirmação e ainda não tem")
            elif m.get("segunda_confirmacao_por") == m.get("revisado_por"):
                problemas.append(f"{ref}: segunda confirmação feita pela mesma pessoa que revisou")
        if not m.get("revisado_por"):
            problemas.append(f"{ref}: sem revisão inicial registrada")
        # duplicidades resolvidas
        if m.get("decisao_duplicidade") == "pendente":
            problemas.append(f"{ref}: alerta de duplicidade sem decisão")
        # leiaute
        if not historico_ascii(m.get("historico_contabil") or m.get("historico") or ""):
            problemas.append(f"{ref}: histórico vazio depois da limpeza para ASCII")
    # conferência de saldo
    if conciliacao is None:
        problemas.append("conferência de saldo do período ainda não foi feita")
    elif conciliacao["diferenca_centavos"] != 0 and not (
        conciliacao.get("justificativa") and conciliacao.get("segunda_revisao_por")
        and conciliacao.get("segunda_revisao_por") != conciliacao.get("justificado_por")
    ):
        problemas.append("conferência de saldo com diferença sem justificativa e segunda revisão por outra pessoa")
    return problemas


def gerar_linhas(movimentos: list[dict], plano: dict[str, ContaPlano], prefixo: str) -> list[str]:
    validar_prefixo(prefixo)
    linhas, problemas = [], []
    for m in movimentos:
        d = date.fromisoformat(m["data"])
        mk = marca(prefixo, m["data"], m["id"])
        campos = [
            d.strftime("%d/%m/%Y"),
            str(m["conta_debito"]),
            str(m["conta_credito"]),
            formatar_fortes(abs(m["valor_centavos"])),
            montar_historico(m.get("historico_contabil") or m["historico"], mk),
        ] + [""] * CAMPOS_VAZIOS_NO_FIM
        linha = ";".join(campos)
        if len(linha.split(";")) != 9:
            problemas.append(f"movimento {m['id']}: linha não tem 9 campos")
        if any(ord(c) > 127 for c in linha):
            problemas.append(f"movimento {m['id']}: caractere fora do ASCII")
        linhas.append(linha)
    if len(set(linhas)) != len(linhas):
        problemas.append("há linhas idênticas no lote")
    if problemas:
        raise LoteBloqueado(problemas)
    return linhas


def conteudo_arquivo(linhas: list[str]) -> bytes:
    return "".join(l + "\r\n" for l in linhas).encode("ascii")
