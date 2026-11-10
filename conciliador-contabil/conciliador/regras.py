"""Etapa 2: plano de contas, cadastro de fornecedores, regras e classificação."""

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .leitor import normalizar
from .modelos import Transacao


class ErroConfiguracao(Exception):
    """Plano de contas ou arquivo de regras inconsistente."""


def termos(texto: str) -> str:
    """Só letras e números, separados por um espaço e cercados por espaços.

    'F. OLAVO', 'F OLAVO' e 'f.olavo' viram ' f olavo ', de modo que a
    pontuação do extrato não impede a regra de casar. Os espaços nas pontas
    garantem palavra inteira: 'NX' não casa dentro de 'ANXIETY'.
    """
    return " " + re.sub(r"[^a-z0-9]+", " ", normalizar(texto)).strip() + " "


@dataclass
class Regra:
    nome: str
    palavras_chave: list[str]
    conta: str
    sentido: str = "ambos"  # "entrada", "saida" ou "ambos"
    revisar: bool = False   # True = a regra é uma suposição; marcar para conferência
    historico: str = ""
    fornecedor: str = ""    # preenchido nas regras geradas pelo cadastro de fornecedores

    def casa(self, transacao: Transacao) -> bool:
        if self.sentido == "entrada" and transacao.valor < 0:
            return False
        if self.sentido == "saida" and transacao.valor > 0:
            return False
        descricao = termos(transacao.descricao)
        return any(termos(p).strip() and termos(p) in descricao for p in self.palavras_chave)


@dataclass
class Configuracao:
    plano: dict[str, str]          # código -> descrição
    conta_banco: str
    conta_transitoria: str
    regras: list[Regra] = field(default_factory=list)


def carregar_plano(caminho) -> dict[str, str]:
    plano = {}
    with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
        for registro in csv.DictReader(arquivo, delimiter=";"):
            codigo = (registro.get("codigo") or "").strip()
            if codigo:
                plano[codigo] = (registro.get("descricao") or "").strip()
    if not plano:
        raise ErroConfiguracao(f"Plano de contas vazio ou sem colunas codigo;descricao: {caminho}")
    return plano


def carregar_configuracao(caminho_regras, caminho_plano) -> Configuracao:
    plano = carregar_plano(caminho_plano)
    dados = json.loads(Path(caminho_regras).read_text(encoding="utf-8"))

    try:
        # Fornecedores vêm antes das regras gerais: um nome próprio é mais
        # específico do que "PAGAMENTO BOLETO".
        regras = [
            Regra(
                nome=f"Fornecedor: {f['nome']}",
                palavras_chave=f["apelidos"],
                conta=f["conta"],
                sentido=f.get("sentido", "saida"),
                revisar=bool(f.get("revisar", False)),
                historico=f.get("historico", f"Pgto fornecedor {f['nome']}"),
                fornecedor=f["nome"],
            )
            for f in dados.get("fornecedores", [])
        ]
        regras += [
            Regra(
                nome=r["nome"],
                palavras_chave=r["palavras_chave"],
                conta=r["conta"],
                sentido=r.get("sentido", "ambos"),
                revisar=bool(r.get("revisar", False)),
                historico=r.get("historico", ""),
            )
            for r in dados["regras"]
        ]
        config = Configuracao(plano, dados["conta_banco"], dados["conta_transitoria"], regras)
    except KeyError as erro:
        raise ErroConfiguracao(f"Campo obrigatório ausente no arquivo de regras: {erro}") from erro

    # Uma regra que aponta para conta inexistente geraria lançamento que o
    # sistema contábil rejeita na importação. Melhor falhar já.
    problemas = []
    for rotulo, conta in (("conta_banco", config.conta_banco), ("conta_transitoria", config.conta_transitoria)):
        if conta not in plano:
            problemas.append(f"{rotulo} '{conta}' não existe no plano de contas")
    for regra in regras:
        if regra.conta not in plano:
            problemas.append(f"'{regra.nome}': conta '{regra.conta}' não existe no plano de contas")
        if regra.sentido not in ("entrada", "saida", "ambos"):
            problemas.append(f"'{regra.nome}': sentido inválido '{regra.sentido}'")
        if not any(termos(p).strip() for p in regra.palavras_chave):
            problemas.append(f"'{regra.nome}': sem palavras-chave ou apelidos")
    if problemas:
        raise ErroConfiguracao("Configuração inconsistente:\n  " + "\n  ".join(problemas))
    return config


def regras_que_casam(transacao: Transacao, regras: list[Regra]) -> list[Regra]:
    """Todas as regras aplicáveis, na ordem de prioridade (a primeira vence)."""
    return [regra for regra in regras if regra.casa(transacao)]
