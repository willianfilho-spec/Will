"""Geração de embeddings. A interface é pequena de propósito: o RAG não depende do Gemini,
e os testes usam HashEmbedder, que funciona offline."""
import hashlib
import re
import time
import unicodedata
from typing import Protocol

import numpy as np


class EmbeddingError(Exception):
    """Falha ao gerar embeddings; a mensagem pode ser exibida ao usuário."""


def explain_api_error(exc: Exception, model: str = "") -> str | None:
    """Mensagem em português para erros permanentes da API; None se o erro pode ser passageiro."""
    text = str(exc)
    code = getattr(exc, "code", None)
    if "API_KEY_INVALID" in text or "API key not valid" in text:
        return ("O Google recusou a chave da API (chave inválida). Volte ao Google AI Studio, copie a chave inteira "
                "(sem espaços) e cole de novo na caixa de conexão. Se continuar, crie outra em Create API key.")
    if code in (401, 403) or "PERMISSION_DENIED" in text:
        return "O Google negou o acesso com esta chave. Confira se a chave é do Google AI Studio e se a API Gemini está liberada para ela."
    if code == 404 or "NOT_FOUND" in text:
        return (f"O modelo \"{model}\" não foi encontrado na sua conta. Use \"Trocar chave\" na barra lateral para o "
                "programa escolher outro modelo disponível para você.")
    if code == 400:
        return f"O Google recusou o pedido (erro 400): {text[:300]}"
    return None


class Embedder(Protocol):
    model: str
    dim: int

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def normalize(matrix: np.ndarray) -> np.ndarray:
    """Normaliza cada linha para norma 1; assim o produto escalar vira similaridade de cosseno.
    Necessário porque vetores reduzidos (output_dimensionality) não vêm normalizados."""
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix[None, :]
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class GeminiEmbedder:
    """Usa client.models.embed_content do SDK google-genai.
    NÃO verificado contra a API real (sem chave neste ambiente); o formato da chamada segue a
    assinatura do SDK instalado. Confirme modelo, limites de lote e task_type na documentação."""

    BATCH = 50

    def __init__(self, client, model: str, dim: int, retries: int = 3, sleep=time.sleep):
        self.client, self.model, self.dim = client, model, dim
        self._retries, self._sleep = retries, sleep

    def _embed(self, texts: list[str], task_type: str) -> np.ndarray:
        from google.genai import types

        config = types.EmbedContentConfig(task_type=task_type, output_dimensionality=self.dim)
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                response = self.client.models.embed_content(model=self.model, contents=texts, config=config)
                vectors = [e.values for e in response.embeddings]
                if len(vectors) != len(texts):
                    raise EmbeddingError("A API devolveu um número de vetores diferente do enviado.")
                matrix = np.asarray(vectors, dtype=np.float32)
                if matrix.shape[1] != self.dim:
                    raise EmbeddingError(f"Vetor com {matrix.shape[1]} dimensões; o esperado era {self.dim}.")
                return normalize(matrix)
            except EmbeddingError:
                raise
            except Exception as exc:  # o SDK levanta tipos próprios (rede, cota, modelo inexistente)
                last = exc
                friendly = explain_api_error(exc, self.model)
                if friendly:  # erro permanente (chave, modelo, permissão): tentar de novo não adianta
                    raise EmbeddingError(friendly) from exc
                if attempt < self._retries - 1:
                    self._sleep(2**attempt)
        raise EmbeddingError(f"Falha ao gerar embeddings após {self._retries} tentativas: {last}") from last

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        parts = [self._embed(texts[i : i + self.BATCH], "RETRIEVAL_DOCUMENT") for i in range(0, len(texts), self.BATCH)]
        return np.vstack(parts)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    words = _WORD.findall("".join(c for c in text if not unicodedata.combining(c)))
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


class HashEmbedder:
    """Embedder determinístico e offline (palavras e pares de palavras em 'sacos de hash').
    Mede apenas coincidência de vocabulário, NÃO significado: serve para testar o encanamento
    do RAG, nunca para avaliar a qualidade da busca semântica."""

    model = "hash-lexical-v1"

    def __init__(self, dim: int = 512):
        self.dim = dim

    def _vector(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in _tokens(text):
            h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += 1.0
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return normalize(np.vstack([self._vector(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return normalize(self._vector(text))[0]


def gemini_embedder(api_key: str, model: str, dim: int) -> GeminiEmbedder | None:
    """None se não houver chave configurada."""
    if not api_key:
        return None
    from google import genai

    return GeminiEmbedder(genai.Client(api_key=api_key), model, dim)
