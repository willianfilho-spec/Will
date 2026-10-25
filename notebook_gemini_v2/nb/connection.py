"""Verifica a chave do Gemini e descobre quais modelos a conta realmente tem,
para o usuário não precisar saber nomes de modelos."""
from dataclasses import dataclass, field

from .embeddings import explain_api_error

_NOT_TEXT_GENERATION = ("embedding", "tts", "image", "live", "audio", "vision", "aqa", "imagen", "veo",
                        "robotics", "computer-use", "learnlm", "gemma")


@dataclass
class KeyCheck:
    ok: bool
    message: str
    generation_models: list[str] = field(default_factory=list)
    embedding_models: list[str] = field(default_factory=list)


def _short(name: str) -> str:
    return name.removeprefix("models/")


def check_key(api_key: str, client_factory=None) -> KeyCheck:
    """Lista os modelos da conta. A listagem é a prova de que a chave funciona."""
    if not api_key or len(api_key) < 20 or any(c.isspace() for c in api_key):
        return KeyCheck(False, "A chave parece incompleta ou tem espaços. Copie de novo no Google AI Studio, inteira e sem espaços.")
    try:
        if client_factory is None:
            from google import genai

            client_factory = lambda key: genai.Client(api_key=key)  # noqa: E731
        client = client_factory(api_key)
        generation, embedding = [], []
        for i, model in enumerate(client.models.list()):
            if i >= 500:
                break
            actions = list(getattr(model, "supported_actions", None) or [])
            name = _short(getattr(model, "name", "") or "")
            if "embedContent" in actions or "embedText" in actions:
                embedding.append(name)
            if "generateContent" in actions and not any(w in name for w in _NOT_TEXT_GENERATION):
                generation.append(name)
    except Exception as exc:  # o SDK levanta tipos próprios (rede, chave, permissão)
        friendly = explain_api_error(exc)
        if friendly:
            return KeyCheck(False, friendly)
        return KeyCheck(False, f"Não consegui falar com o Google. Verifique a internet e tente de novo. Detalhe: {str(exc)[:200]}")
    if not embedding:
        return KeyCheck(False, "A chave funciona, mas a conta não lista nenhum modelo de embeddings. Sem eles a busca não funciona.",
                        generation, embedding)
    return KeyCheck(True, f"Chave válida: {len(generation)} modelo(s) de resposta e {len(embedding)} de busca disponíveis.",
                    generation, embedding)


def pick_embedding(available: list[str], preferred: str = "") -> str | None:
    if preferred and preferred in available:
        return preferred
    ranked = sorted(available, key=lambda n: (0 if "gemini-embedding" in n else 1, 1 if ("preview" in n or "exp" in n) else 0, n))
    return ranked[0] if ranked else None


def pick_generation(available: list[str], preferred: str = "") -> str | None:
    if preferred and preferred in available:
        return preferred
    ranked = sorted(available, key=lambda n: (0 if "flash" in n else 1, 1 if ("preview" in n or "exp" in n or "latest" in n) else 0, n))
    return ranked[0] if ranked else None
