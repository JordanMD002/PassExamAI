import logging
from app.db.supabase_client import supabase
from app.rag.chunking import chunk_text
from app.rag.embeddings import embed_chunks
from app.rag.ingestion import store_chunks_in_pgvector

logger = logging.getLogger(__name__)


def update_source_status(
    source_id: str,
    status: str,
    chunks_count: int = 0,
    error_message: str | None = None,
) -> None:
    payload = {"status": status}
    if chunks_count > 0:
        payload["chunks_count"] = chunks_count
    if error_message:
        payload["error_message"] = error_message
    supabase.table("user_sources").update(payload).eq("id", source_id).execute()


async def ingest_user_link(
    source_id: str,
    url: str,
    project_id: str,
) -> None:
    """
    Pipeline d'ingestion pour un lien fourni par l'utilisateur.
    URL → Firecrawl → chunks → embeddings → pgvector.

    Ces contenus ont la même priorité que les PDFs dans le RAG :
    ils constituent la base de connaissance principale de l'étudiant.
    """
    logger.info(f"🔗 Ingestion lien utilisateur: {url}")

    try:
        # ── ÉTAPE 1 : Extraction du contenu ────────────────
        update_source_status(source_id, "crawling")

        from app.web.firecrawl_client import firecrawl_scrape

        content = await firecrawl_scrape(
            url, max_chars=50000
        )  # Cap généreux pour liens user

        if not content.strip():
            # Fallback Tavily extract si Firecrawl échoue
            from app.web.tavily_client import tavily_extract_url

            content = await tavily_extract_url(url)

        if not content.strip():
            raise ValueError(f"Impossible d'extraire le contenu de {url}")

        # Sauvegarde le texte extrait
        supabase.table("user_sources").update(
            {
                "extracted_text": content[:50000],
            }
        ).eq("id", source_id).execute()

        # ── ÉTAPE 2 : Chunking ─────────────────────────────
        update_source_status(source_id, "chunking")

        chunks = chunk_text(
            text=content,
            document_id=source_id,  # On réutilise document_id pour les liens
            project_id=project_id,
            source_type="reference",
            filename=url,
        )

        if not chunks:
            raise ValueError("Aucun chunk produit")

        # ── ÉTAPE 3 : Embeddings ───────────────────────────
        update_source_status(source_id, "embedding")
        embedded_chunks = await embed_chunks(chunks)

        # ── ÉTAPE 4 : Stockage pgvector ────────────────────
        # On stocke dans document_chunks avec un marqueur source_type='web_user'
        # pour distinguer des PDFs mais garder le même RAG unifié
        for chunk in embedded_chunks:
            chunk.metadata.source_type = "reference"  # type: ignore

        chunks_count = await store_chunks_in_pgvector(
            chunks=embedded_chunks,
            document_id=source_id,
        )

        update_source_status(source_id, "ready", chunks_count=chunks_count)
        logger.info(f"✅ Lien ingéré: {url} → {chunks_count} chunks")

    except Exception as e:
        logger.error(f"❌ Ingestion lien échouée {url}: {e}")
        update_source_status(source_id, "failed", error_message=str(e))
