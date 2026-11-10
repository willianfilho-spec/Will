"""Etapa 2b (opcional): sugestão de conta por IA para o que as regras não cobriram.

Só é usada com a opção --ia. Exige `pip install anthropic` e a variável de
ambiente ANTHROPIC_API_KEY. A IA recebe apenas a descrição e o sentido de cada
movimento (não recebe valores nem datas) e só pode responder com uma conta que
exista no plano de contas. Toda sugestão sai marcada como REVISAR.
"""

import json

from .modelos import Transacao

MODELO = "claude-opus-5-5"
TAMANHO_LOTE = 50
INDEFINIDO = "INDEFINIDO"

INSTRUCOES = """Você apoia um escritório de contabilidade brasileiro na classificação de \
movimentos de extrato bancário. Para cada movimento, indique a conta de contrapartida \
(a outra ponta do lançamento, já que uma das pontas é sempre a conta do banco).

Use somente contas do plano de contas fornecido. Se a descrição não permitir identificar \
a natureza do movimento com segurança razoável, responda INDEFINIDO: um lançamento \
pendente custa menos ao contador do que um lançamento errado que parece certo. \
Na justificativa, diga em uma frase o que na descrição levou à escolha."""


class ErroIA(Exception):
    pass


def _esquema(plano: dict[str, str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "classificacoes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "conta": {"type": "string", "enum": [*plano.keys(), INDEFINIDO]},
                        "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                        "justificativa": {"type": "string"},
                    },
                    "required": ["id", "conta", "confianca", "justificativa"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["classificacoes"],
        "additionalProperties": False,
    }


def sugerir_contas(transacoes: list[Transacao], plano: dict[str, str]) -> dict[int, dict]:
    """Devolve {linha do extrato: {"conta", "confianca", "justificativa"}}."""
    if not transacoes:
        return {}
    try:
        import anthropic
    except ImportError as erro:
        raise ErroIA("Instale o SDK para usar --ia:  pip install anthropic") from erro

    cliente = anthropic.Anthropic()
    plano_texto = "\n".join(f"{codigo} - {descricao}" for codigo, descricao in plano.items())
    sugestoes: dict[int, dict] = {}

    for inicio in range(0, len(transacoes), TAMANHO_LOTE):
        lote = transacoes[inicio:inicio + TAMANHO_LOTE]
        movimentos = [
            {"id": t.linha, "sentido": "entrada" if t.valor > 0 else "saida", "descricao": t.descricao}
            for t in lote
        ]
        try:
            resposta = cliente.beta.messages.create(
                model=MODELO,
                max_tokens=16000,
                # Se o modelo principal recusar o pedido, a API tenta um modelo alternativo.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=INSTRUCOES,
                output_config={"format": {"type": "json_schema", "schema": _esquema(plano)}},
                messages=[{
                    "role": "user",
                    "content": (
                        f"<plano_de_contas>\n{plano_texto}\n</plano_de_contas>\n\n"
                        f"<movimentos>\n{json.dumps(movimentos, ensure_ascii=False, indent=1)}\n</movimentos>"
                    ),
                }],
            )
        except anthropic.AuthenticationError as erro:
            raise ErroIA("Chave de API ausente ou inválida (ANTHROPIC_API_KEY).") from erro
        except anthropic.RateLimitError as erro:
            raise ErroIA("Limite de requisições atingido; tente novamente em instantes.") from erro
        except anthropic.APIStatusError as erro:
            raise ErroIA(f"A API recusou a requisição ({erro.status_code}): {erro.message}") from erro
        except anthropic.APIConnectionError as erro:
            raise ErroIA("Sem conexão com a API da Anthropic.") from erro

        if resposta.stop_reason != "end_turn":
            raise ErroIA(f"Resposta incompleta da IA (stop_reason={resposta.stop_reason}).")
        texto = next(bloco.text for bloco in resposta.content if bloco.type == "text")

        linhas_do_lote = {t.linha for t in lote}
        for item in json.loads(texto)["classificacoes"]:
            # Confere de novo: nunca aceitar linha ou conta que não pedimos.
            if item["id"] in linhas_do_lote and item["conta"] in plano:
                sugestoes[item["id"]] = item
    return sugestoes
