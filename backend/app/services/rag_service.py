"""RAG service: build indices and search across course chunks."""

import logging
import os
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from sqlmodel import Session, select

from app.core.config import settings
from app.models.course import Course
from app.models.knowledge_chunk import KnowledgeChunk
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

_embedding_service: Optional[EmbeddingService] = None
_vector_store: Optional[VectorStoreService] = None
_chroma_collection = None

MAX_TOP_K = 20


def _get_services() -> tuple[EmbeddingService, VectorStoreService]:
    global _embedding_service, _vector_store
    if _embedding_service is None:
        _embedding_service = EmbeddingService(
            provider=settings.EMBEDDING_PROVIDER,
            dim=settings.EMBEDDING_DIM,
        )
    if _vector_store is None:
        _vector_store = VectorStoreService(
            persist_dir=settings.CHROMA_PERSIST_DIR,
            collection_name=settings.CHROMA_COLLECTION_NAME,
            embedding_service=_embedding_service,
        )
    return _embedding_service, _vector_store


def build_course_index(course_id: int, session: Session) -> dict:
    """Read knowledge_chunks from SQLite and upsert into ChromaDB."""
    course = session.get(Course, course_id)
    if not course:
        return {"error": "course not found", "course_id": course_id}

    chunks = session.exec(
        select(KnowledgeChunk).where(KnowledgeChunk.course_id == course_id)
    ).all()

    if not chunks:
        return {"error": "no chunks found for this course", "course_id": course_id}

    embedding, vs = _get_services()
    chunk_dicts = [
        {
            "chunk_id": c.id,
            "content": c.content,
            "course_id": c.course_id,
            "file_id": c.file_id,
            "chunk_index": c.chunk_index,
            "source": c.source,
            "page_number": c.page_number,
        }
        for c in chunks
    ]
    result = vs.upsert_chunks(chunk_dicts)
    return {
        "course_id": course_id,
        "indexed_chunks": result["indexed"],
        "collection": settings.CHROMA_COLLECTION_NAME,
        "provider": embedding.provider,
        "rag_status": _rag_status_payload(vector_count=result["indexed"], embedding=embedding),
    }


def search_course(course_id: int, query: str, top_k: int, session: Session) -> dict:
    """Search ChromaDB for chunks matching query, filtered by course_id."""
    course = session.get(Course, course_id)
    if not course:
        return {"error": "course not found", "course_id": course_id}

    top_k = min(top_k, MAX_TOP_K)
    embedding, vs = _get_services()
    results = vs.search(query=query, course_id=course_id, top_k=top_k)
    return {
        "course_id": course_id,
        "query": query,
        "results": results,
        "rag_status": _rag_status_payload(
            vector_count=len(results),
            embedding=embedding,
            course_references_enabled=True,
        ),
    }


def search_all_courses(query: str, top_k: int, session: Session) -> dict:
    """Search across all courses (no course_id filter)."""
    top_k = min(top_k, MAX_TOP_K)
    embedding, vs = _get_services()
    results = vs.search(query=query, course_id=None, top_k=top_k)
    return {
        "course_id": None,
        "query": query,
        "results": results,
        "rag_status": _rag_status_payload(
            vector_count=len(results),
            embedding=embedding,
            course_references_enabled=False,
        ),
    }


def _lite_vector_count() -> int:
    """Count vectors without loading the embedding model (fast dashboard path)."""
    global _chroma_collection
    if _chroma_collection is None:
        os.makedirs(settings.CHROMA_PERSIST_DIR, exist_ok=True)
        client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _chroma_collection = client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return int(_chroma_collection.count())


def get_rag_status() -> dict:
    """Return RAG component status."""
    try:
        vector_count = _lite_vector_count()
    except Exception as exc:
        logger.warning("RAG status count failed: %s", exc)
        vector_count = 0
    embedding, _ = _get_services()
    return {
        "collection": settings.CHROMA_COLLECTION_NAME,
        "persist_dir": settings.CHROMA_PERSIST_DIR,
        "retrieval_mode": settings.RAG_RETRIEVAL_MODE,
        "course_references_enabled": True,
        "embedding_provider": embedding.provider,
        "embedding_dim": embedding.dim,
        "embedding_status": embedding.status(),
        "vector_count": vector_count,
    }


def _rag_status_payload(
    *,
    vector_count: int,
    embedding: EmbeddingService,
    course_references_enabled: bool = True,
) -> dict:
    return {
        "course_references_enabled": course_references_enabled,
        "course_reference_label": "课程引用已启用" if course_references_enabled else "跨课程检索",
        "retrieval_mode": settings.RAG_RETRIEVAL_MODE,
        "embedding_provider": embedding.provider,
        "embedding_status": embedding.status(),
        "matched_chunks": vector_count,
    }
