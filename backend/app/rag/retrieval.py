from app.db.supabase_client import supabase
from app.rag.embeddings import get_query_embedding  # ← task_type query
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


async def retrieve_chunks(
    query: str,
    project_id: str,
    chapter_hint: str | None = None,
    top_k: int | None = None,
    min_similarity: float | None = None,
) -> list[dict]:
    """
    Recherche sémantique dans pgvector.
    Retourne : [{content, metadata, similarity}, ...]
    similarity : 0.0 (pas du tout pertinent) → 1.0 (identique)
    """
    k = top_k or settings.top_k_retrieval
    threshold = min_similarity  # None = pas de filtre

    # Embedding de la requête avec task_type='retrieval_query'
    query_vector = await get_query_embedding(query)

    metadata_filter: dict = {"project_id": project_id}
    if chapter_hint:
        metadata_filter["chapter_hint"] = chapter_hint

    try:
        response = supabase.rpc(
            "match_document_chunks",
            {
                "query_embedding": query_vector,
                "match_count": k,
                "filter": metadata_filter,
            },
        ).execute()

        chunks = response.data or []

        # Filtre par seuil de similarité si demandé
        if threshold is not None:
            chunks = [c for c in chunks if c.get("similarity", 0) >= threshold]

        logger.info(
            f"Retrieval '{query[:40]}...' → "
            f"{len(chunks)} chunks (seuil={threshold})"
        )
        return chunks

    except Exception as e:
        logger.error(f"Retrieval error: {e}")
        return []


def assess_rag_quality(chunks: list[dict]) -> tuple[bool, float]:
    """
    Évalue si les chunks RAG sont suffisants pour répondre.
    Retourne : (is_sufficient, avg_similarity)

    Utilisé par le tuteur chat pour décider si web search est nécessaire.
    """
    if not chunks:
        return False, 0.0

    similarities = [c.get("similarity", 0.0) for c in chunks]
    avg_sim = sum(similarities) / len(similarities)
    top_sim = max(similarities)

    # Critères de suffisance :
    # 1. Au moins N chunks trouvés
    # 2. Le meilleur chunk dépasse le seuil
    is_sufficient = (
        len(chunks) >= settings.rag_min_chunks_threshold
        and top_sim >= settings.rag_similarity_threshold
    )

    logger.info(
        f"RAG quality: {len(chunks)} chunks, "
        f"avg_sim={avg_sim:.3f}, top_sim={top_sim:.3f} → "
        f"{'✅ sufficient' if is_sufficient else '⚠️ insufficient → web fallback'}"
    )
    return is_sufficient, avg_sim


async def retrieve_for_chapter(
    chapter_title: str,
    project_id: str,
    top_k: int = 5,
) -> list[dict]:
    query = f"Content related to: {chapter_title}"
    return await retrieve_chunks(
        query=query,
        project_id=project_id,
        chapter_hint=chapter_title,
        top_k=top_k,
    )
