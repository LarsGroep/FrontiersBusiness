"""Local CPU embeddings (no API key needed). 384-dim, matches chunks.embedding."""
from __future__ import annotations

import os
from functools import lru_cache

MODEL = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding
    return TextEmbedding(MODEL, cache_dir=os.getenv("FASTEMBED_CACHE_PATH"))


def embed_passages(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _model().passage_embed(texts, batch_size=64)]


def embed_query(text: str) -> list[float]:
    return next(iter(_model().query_embed([text]))).tolist()
