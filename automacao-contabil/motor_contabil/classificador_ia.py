"""Sugestão de conta por IA para históricos que nenhuma regra reconhece.

Princípios (da proposta):
  - A IA só SUGERE. Todo lançamento classificado por IA fica pendente até um
    profissional aprovar. Ela nunca libera lançamento sozinha.
  - A resposta é restrita às contas analíticas do plano (enum no esquema JSON)
    e é validada de novo no motor, mesmo com a restrição.
  - Minimização de dados: vai para a API apenas o histórico (com CPF/CNPJ
    mascarados) e o sentido da operação. Data, conta bancária e valor não são
    enviados, a menos que `enviar_valor=True`.
  - Desligada por padrão. Para ligar é preciso o pacote `anthropic`, uma
    credencial configurada e a decisão explícita de quem opera o sistema.

Observação LGPD: históricos de PIX costumam conter nomes de pessoas físicas.
O mascaramento remove CPF/CNPJ, não nomes. Antes de usar com dados reais,
o escritório precisa decidir se o envio é aceitável e registrar a base legal.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol

from .modelo import Transacao
from .plano_contas import PlanoDeContas
from .texto import formatar_valor, mascarar_documentos

MODELO_PADRAO = os.environ.get("MOTOR_CONTABIL_MODELO", "claude-opus-5-5")
SEM_SUGESTAO = "NENHUMA"


@dataclass
class Sugestao:
    conta: str
    confianca: str  # "alta", "media" ou "baixa"
    justificativa: str


class Classificador(Protocol):
    def sugerir(self, t: Transacao, plano: PlanoDeContas) -> Sugestao | None: ...


class SemIA:
    """Classificador nulo: o comportamento padrão."""

    def sugerir(self, t: Transacao, plano: PlanoDeContas) -> Sugestao | None:
        return None


INSTRUCOES = """Você auxilia um escritório de contabilidade brasileiro a classificar \
movimentações bancárias. Recebe o histórico de uma movimentação e o sentido \
(entrada ou saída de dinheiro da conta bancária) e escolhe, no plano de contas \
fornecido, a conta de contrapartida mais provável.

Regras:
- Escolha somente uma conta da lista. Se o histórico não permitir uma escolha \
razoável (por exemplo, uma transferência PIX sem indicação do motivo), responda \
"NENHUMA".
- Não presuma fatos que o histórico não mostra. Um PIX para uma pessoa pode ser \
pagamento a fornecedor, adiantamento, distribuição de lucros ou empréstimo; sem \
indício, responda "NENHUMA".
- A confiança é "alta" só quando o histórico identifica claramente a natureza \
da operação.
- A justificativa tem uma frase, em português."""


class ClassificadorClaude:
    def __init__(self, modelo: str = MODELO_PADRAO, enviar_valor: bool = False, cliente=None):
        if cliente is None:
            import anthropic  # importação tardia: o pacote é opcional

            cliente = anthropic.Anthropic()
        self.cliente = cliente
        self.modelo = modelo
        self.enviar_valor = enviar_valor

    def _esquema(self, plano: PlanoDeContas) -> dict:
        codigos = sorted(c.codigo for c in plano.analiticas())
        return {
            "type": "object",
            "properties": {
                "conta": {"type": "string", "enum": codigos + [SEM_SUGESTAO]},
                "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                "justificativa": {"type": "string"},
            },
            "required": ["conta", "confianca", "justificativa"],
            "additionalProperties": False,
        }

    def sugerir(self, t: Transacao, plano: PlanoDeContas) -> Sugestao | None:
        lista = "\n".join(f"{c.codigo} - {c.descricao}" for c in plano.analiticas())
        dados = {"historico": mascarar_documentos(t.historico), "sentido": t.sentido}
        if self.enviar_valor:
            dados["valor"] = formatar_valor(t.valor)
        resposta = self.cliente.beta.messages.create(
            model=self.modelo,
            max_tokens=1024,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=INSTRUCOES,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": self._esquema(plano)},
            },
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Plano de contas (contas analíticas):\n{lista}\n\n"
                        f"Movimentação:\n{json.dumps(dados, ensure_ascii=False)}"
                    ),
                }
            ],
        )
        if resposta.stop_reason != "end_turn":
            # recusa, corte por max_tokens etc.: sem sugestão, fica para revisão
            return None
        texto = next((b.text for b in resposta.content if b.type == "text"), None)
        if not texto:
            return None
        try:
            bruto = json.loads(texto)
        except json.JSONDecodeError:
            return None
        conta = bruto.get("conta")
        # Validação redundante de propósito: não confiar só no esquema.
        if conta == SEM_SUGESTAO or plano.problema(conta) is not None:
            return None
        return Sugestao(conta, bruto.get("confianca", "baixa"), bruto.get("justificativa", ""))
