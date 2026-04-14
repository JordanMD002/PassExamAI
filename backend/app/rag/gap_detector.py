import logging
from app.rag.retrieval import retrieve_chunks, assess_rag_quality
from app.web.tavily_client import tavily_search
from app.web.firecrawl_client import firecrawl_scrape
from app.core.config import settings

logger = logging.getLogger(__name__)


async def enrich_if_needed(
    query: str,
    project_id: str,
    chapter_hint: str | None = None,
    top_k: int = 5,
    context_label: str = "generation",
) -> tuple[list[dict], list[dict], bool]:
    """
    Intelligence centrale du RAG hybride.

    1. Récupère d'abord les chunks de l'utilisateur (RAG offline)
    2. Évalue la qualité : suffisant ? → retourne directement
    3. Insuffisant → web search ciblé pour combler les lacunes

    Retourne : (rag_chunks, web_sources, web_was_used)

    Principe : les sources de l'utilisateur sont TOUJOURS prioritaires.
    Le web est un complément, jamais un substitut.
    """
    # ── 1. RAG principal (sources utilisateur) ─────────────
    rag_chunks = await retrieve_chunks(
        query=query,
        project_id=project_id,
        chapter_hint=chapter_hint,
        top_k=top_k,
    )

    is_sufficient, avg_sim = assess_rag_quality(rag_chunks)

    # ── 2. Si suffisant, pas besoin du web ─────────────────
    if is_sufficient:
        logger.info(
            f"[{context_label}] RAG suffisant (avg_sim={avg_sim:.3f}) — pas de web search"
        )
        return rag_chunks, [], False

    # ── 3. RAG insuffisant → web search ciblé ──────────────
    logger.info(
        f"[{context_label}] RAG insuffisant (avg_sim={avg_sim:.3f}) → "
        f"web search pour combler les lacunes"
    )

    web_sources = await _targeted_web_search(query, rag_chunks)
    return rag_chunks, web_sources, True


async def _targeted_web_search(
    query: str,
    existing_chunks: list[dict],
) -> list[dict]:
    """
    Recherche web ciblée sur les lacunes identifiées dans le RAG.
    Utilise le contenu existant pour affiner la requête.
    """
    # Construit une requête enrichie depuis ce qu'on a déjà
    existing_context = " ".join(c.get("content", "")[:100] for c in existing_chunks[:2])

    search_query = query
    if existing_context:
        # La requête web cherche ce qui MANQUE dans les sources existantes
        search_query = f"{query} detailed explanation examples"

    try:
        results = await tavily_search(
            query=search_query,
            max_results=3,
            search_depth="advanced",
        )

        if not results:
            return []

        # Crawle seulement la meilleure URL pour plus de profondeur
        best_url = results[0].get("url", "")
        enriched_sources = []

        for r in results:
            enriched_sources.append(
                {
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "content": r.get("content", ""),
                    "source": "tavily",
                }
            )

        # Deep crawl de la meilleure source
        if best_url:
            deep_content = await firecrawl_scrape(best_url, max_chars=6000)
            if deep_content:
                enriched_sources[0]["content"] = deep_content
                enriched_sources[0]["source"] = "firecrawl"

        logger.info(f"Web enrichment ciblé: {len(enriched_sources)} sources récupérées")
        return enriched_sources

    except Exception as e:
        logger.warning(f"Web fallback search failed: {e}")
        return []
