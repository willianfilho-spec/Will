"""Validador pré-exportação e gerador no leiaute de importação do Fortes.

Leiaute tirado de arquivos reais que o Fortes aceitou no escritório:

    data;debito;credito;valor;historico;;;;

- sem cabeçalho; nove campos separados por ponto e vírgula (quatro vazios no fim);
- data dd/mm/aaaa; contas pelo código reduzido;
- valor positivo, vírgula decimal, sem separador de milhar;
- histórico em maiúsculas, só ASCII, até o limite configurado da empresa
  (padrão config.LIMITE_HISTORICO), terminado pela marca [PREFIXO-AAAAMM-NNNNNN]
  que identifica o movimento. O corte só acontece no arquivo: o histórico
  completo continua no banco e fica registrado em lote_itens;
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
LIMITE_MINIMO, LIMITE_MAXIMO = 40, 250   # a marca ocupa até 22 caracteres


def validar_limite(limite: int) -> int:
    if not isinstance(limite, int) or isinstance(limite, bool) or not LIMITE_MINIMO <= limite <= LIMITE_MAXIMO:
        raise ValueError(f"limite do histórico deve ser um inteiro entre {LIMITE_MINIMO} e {LIMITE_MAXIMO}")
    return limite


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


def montar_historico(texto: str, m: str, limite: int = config.LIMITE_HISTORICO) -> tuple[str, bool]:
    """(histórico do arquivo, se houve corte). A marca nunca é cortada."""
    validar_limite(limite)
    espaco = limite - len(m) - 1
    limpo = historico_ascii(texto)
    return f"{limpo[:espaco].rstrip()} {m}".strip(), len(limpo) > espaco


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


@dataclass(frozen=True)
class LinhaGerada:
    movimento_id: int
    marca: str
    linha: str
    historico_completo: str
    historico_exportado: str
    truncado: bool


def gerar_linhas(movimentos: list[dict], plano: dict[str, ContaPlano], prefixo: str,
                 limite: int = config.LIMITE_HISTORICO) -> list[LinhaGerada]:
    validar_prefixo(prefixo)
    validar_limite(limite)
    geradas, problemas = [], []
    for m in movimentos:
        d = date.fromisoformat(m["data"])
        mk = marca(prefixo, m["data"], m["id"])
        completo = m.get("historico_contabil") or m["historico"]
        hist, cortado = montar_historico(completo, mk, limite)
        campos = [
            d.strftime("%d/%m/%Y"),
            str(m["conta_debito"]),
            str(m["conta_credito"]),
            formatar_fortes(abs(m["valor_centavos"])),
            hist,
        ] + [""] * CAMPOS_VAZIOS_NO_FIM
        linha = ";".join(campos)
        if len(linha.split(";")) != 9:
            problemas.append(f"movimento {m['id']}: linha não tem 9 campos")
        if any(ord(c) > 127 for c in linha):
            problemas.append(f"movimento {m['id']}: caractere fora do ASCII")
        if len(hist) > limite:
            problemas.append(f"movimento {m['id']}: histórico com {len(hist)} caracteres, acima do limite {limite}")
        geradas.append(LinhaGerada(m["id"], mk, linha, completo, hist, cortado))
    linhas = [g.linha for g in geradas]
    if len(set(linhas)) != len(linhas):
        problemas.append("há linhas idênticas no lote")
    marcas = [g.marca for g in geradas]
    if len(set(marcas)) != len(marcas):
        problemas.append("há marcas repetidas no lote")
    if problemas:
        raise LoteBloqueado(problemas)
    return geradas


def conferir_ida_e_volta(conteudo: bytes, movimentos: list[dict], geradas: list[LinhaGerada]) -> list[str]:
    """Relê o arquivo pronto como o Fortes leria e compara com a origem, linha a linha.
    Pega perda de linha, troca de conta, valor alterado e marca perdida antes de liberar o lote."""
    from parsers.fortes_razao_parser import ler_lancamentos_fortes
    problemas: list[str] = []
    try:
        texto = conteudo.decode("ascii")
    except UnicodeDecodeError:
        return ["arquivo gerado tem byte fora do ASCII"]
    if not texto.endswith("\r\n") or "\n" in texto.replace("\r\n", ""):
        problemas.append("fim de linha diferente de CRLF")
    partidas = ler_lancamentos_fortes(conteudo)
    if len(partidas) != 2 * len(movimentos):
        return problemas + [f"arquivo tem {len(partidas) // 2} lançamentos; esperados {len(movimentos)}"]
    for i, (m, g) in enumerate(zip(movimentos, geradas)):
        d, c = partidas[2 * i], partidas[2 * i + 1]
        esperado = (m["data"], str(m["conta_debito"]), str(m["conta_credito"]), abs(m["valor_centavos"]))
        lido = (d["data"], d["conta"], c["conta"], d["debito_centavos"])
        if lido != esperado or c["credito_centavos"] != abs(m["valor_centavos"]):
            problemas.append(f"movimento {m['id']}: arquivo diz {lido}, origem diz {esperado}")
        if not d["historico"].endswith(g.marca):
            problemas.append(f"movimento {m['id']}: marca {g.marca} não está no fim do histórico")
    total = sum(p["debito_centavos"] for p in partidas)
    if total != sum(abs(m["valor_centavos"]) for m in movimentos):
        problemas.append("total do arquivo difere do total dos movimentos")
    return problemas


def conteudo_arquivo(linhas: list[str] | list[LinhaGerada]) -> bytes:
    return "".join((l.linha if isinstance(l, LinhaGerada) else l) + "\r\n" for l in linhas).encode("ascii")
