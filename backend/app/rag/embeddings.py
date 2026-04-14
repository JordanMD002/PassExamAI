import logging
import asyncio
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import settings
from app.schemas.documents import DocumentChunk

logger = logging.getLogger(__name__)

# Configure le client Gemini une seule fois
genai.configure(api_key=settings.gemini_api_key)

EMBEDDING_BATCH_SIZE = 50  # Gemini API : limite plus basse qu'OpenAI
EMBEDDING_MODEL = "models/text-embedding-004"  # 768 dimensions, stable


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
async def _embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Appelle l'API Gemini Embeddings pour un batch de textes.
    Exécuté dans un thread pour ne pas bloquer l'event loop
    (SDK Gemini est synchrone).
    """

    def _sync_embed():
        result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=texts,
            task_type="retrieval_document",  # Optimisé pour le stockage RAG
        )
        return (
            result["embedding"] if len(texts) == 1 else [e for e in result["embedding"]]
        )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_embed)


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Génère des embeddings Gemini pour une liste de textes.
    Retourne une liste de vecteurs 768 dimensions.
    Utilisé par le pipeline d'ingestion ET la recherche.
    """
    if not texts:
        return []

    all_embeddings = []

    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + EMBEDDING_BATCH_SIZE]
        logger.info(
            f"Embedding batch {i // EMBEDDING_BATCH_SIZE + 1} "
            f"({len(batch)} textes) via Gemini..."
        )
        try:
            embeddings = await _embed_batch(batch)
            # Gemini retourne un seul vecteur si 1 texte, liste si multiple
            if len(batch) == 1 and isinstance(embeddings[0], float):
                all_embeddings.append(embeddings)
            else:
                all_embeddings.extend(embeddings)
        except Exception as e:
            logger.error(f"Embedding batch error: {e}")
            raise

    logger.info(f"✅ {len(all_embeddings)} embeddings générés (dim=768)")
    return all_embeddings


async def get_query_embedding(query: str) -> list[float]:
    """
    Embedding pour une requête de recherche.
    Utilise task_type='retrieval_query' — différent du stockage.
    Cette distinction améliore la précision de la recherche.
    """

    def _sync_query_embed():
        result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=query,
            task_type="retrieval_query",  # ← Différent de retrieval_document
        )
        return result["embedding"]

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_query_embed)


async def embed_chunks(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """
    Génère les embeddings pour tous les chunks.
    Retourne les chunks avec embedding renseigné.
    """
    if not chunks:
        return []

    texts = [chunk.content for chunk in chunks]
    embeddings = await get_embeddings(texts)

    for chunk, embedding in zip(chunks, embeddings):
        chunk.embedding = embedding

    return chunks
