"""Embedding service with pluggable providers.

Default: hash_mock — deterministic 384-dim vectors for pipeline validation.
Optional: sentence_transformers — real semantic embeddings (requires network + model).
"""

import hashlib
import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Pluggable embedding provider for text → vector conversion."""

    def __init__(
        self,
        provider: str = "hash_mock",
        dim: int = 384,
        model_name: Optional[str] = None,
    ):
        self.provider = provider
        self.dim = dim
        self.model_name = model_name
        self._model = None

        if provider == "sentence_transformers":
            self._init_sentence_transformers()
        else:
            logger.info("EmbeddingService: using hash_mock (pipeline validation only, not semantic)")

    def _init_sentence_transformers(self):
        try:
            from sentence_transformers import SentenceTransformer

            name = self.model_name or "all-MiniLM-L6-v2"
            self._model = SentenceTransformer(name)
            logger.info("EmbeddingService: loaded sentence-transformers model '%s'", name)
        except Exception as e:
            logger.warning("EmbeddingService: sentence-transformers unavailable (%s), fallback to hash_mock", e)
            self.provider = "hash_mock"
            self._model = None

    def _hash_embed(self, text: str) -> list[float]:
        """Generate a deterministic 384-dim normalized vector from text hash."""
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand to dim dimensions
        vec = np.zeros(self.dim, dtype=np.float32)
        for i in range(self.dim):
            seed = int.from_bytes(h[i % len(h) : i % len(h) + 1] or b"\x00", "big")
            vec[i] = (seed / 255.0) * 2 - 1  # scale to [-1, 1]

        # Normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        if not texts:
            return []
        if self._model is not None:
            return self._model.encode(texts, normalize_embeddings=True).tolist()
        return [self._hash_embed(t) for t in texts]

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query string."""
        if not query:
            return [0.0] * self.dim
        if self._model is not None:
            return self._model.encode([query], normalize_embeddings=True)[0].tolist()
        return self._hash_embed(query)

    def status(self) -> dict[str, object]:
        """Public embedding status for RAG transparency."""
        return {
            "embedding_provider": self.provider,
            "embedding_model": self.model_name or ("hash_mock" if self.provider == "hash_mock" else ""),
            "embedding_dim": self.dim,
            "semantic_embedding": self.provider != "hash_mock",
        }
