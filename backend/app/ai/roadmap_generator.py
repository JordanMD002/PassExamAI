import hashlib
import json
import logging
from datetime import date
from typing import Optional

from app.ai.llm_client import llm_complete
from app.db.supabase_client import supabase
from app.rag.retrieval import retrieve_chunks
from app.schemas.roadmap import RoadmapSchema, ChapterSchema
from app.web.firecrawl_client import enrich_with_web

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Prompt principal — sortie JSON stricte
# ─────────────────────────────────────────────
ROADMAP_SYSTEM_PROMPT = """You are an expert educational curriculum designer.
Analyze the provided exam/course material and create a personalized revision roadmap.

The roadmap MUST be adapted to the student's available study time.
If time is short, reduce chapter count and focus on highest-importance topics.
If time allows, provide comprehensive coverage.

Output ONLY valid JSON:
{
  "title": "string",
  "estimated_total_hours": 20.0,
  "chapters": [
    {
      "order_index": 1,
      "title": "string",
      "objective": "string",
      "importance": 2.0,
      "estimated_hours": 3.0
    }
  ]
}

Rules:
- importance: 0.5 (minor) → 3.0 (exam-critical)
- estimated_hours: realistic study time per chapter
- Sum of estimated_hours should match available study time
- Order: prerequisites before advanced topics
- Base content on the uploaded exam material — web is supplementary only
- All text in English

IMPORTANT (Order of Priority):
  Priority 1: The uploaded EXAM (determine the syllabus from it). 
  Priority 2: The provided NOTES (use them to fill the gaps).
  Priority 3: The sources from web search
"""


def _build_roadmap_user_prompt(
    doc_content: str,
    web_sources: list[dict],
    subject: str = "",
    exam_type: str = "",
) -> str:
    """
    Construit le prompt utilisateur avec le contenu du document
    et les sources web enrichies.
    """
    # Résumé des sources web (on garde les 3 premières, cap à 2000 chars chacune)
    web_context = ""
    if web_sources:
        web_parts = []
        for i, source in enumerate(web_sources[:3]):
            content = source.get("content", "")[:2000]
            title = source.get("title", f"Source {i+1}")
            url = source.get("url", "")
            web_parts.append(f"### Web Source {i+1}: {title}\nURL: {url}\n{content}")
        web_context = "\n\n".join(web_parts)

    context_parts = []

    if subject:
        context_parts.append(f"Subject: {subject}")
    if exam_type:
        context_parts.append(f"Exam type: {exam_type}")

    context_header = "\n".join(context_parts)

    return f"""
{context_header}

## Uploaded Document Content (primary source — prioritize this):
{doc_content[:6000]}

## Web Research (supplementary enrichment):
{web_context if web_context else "No web enrichment available."}

Generate the revision roadmap based on this material.
""".strip()


# ─────────────────────────────────────────────
# Cache : même document = même roadmap
# ─────────────────────────────────────────────


def _compute_content_hash(text: str) -> str:
    """Hash SHA256 des 10 000 premiers caractères du texte extrait."""
    return hashlib.sha256(text[:10000].encode()).hexdigest()[:16]


def _get_cached_roadmap(project_id: str, content_hash: str) -> Optional[dict]:
    """
    Vérifie si une roadmap existe déjà pour ce hash de contenu.
    Évite de régénérer à chaque appel pour le même document.
    """
    result = (
        supabase.table("roadmaps")
        .select("*, chapters(*)")
        .eq("project_id", project_id)
        .eq("doc_content_hash", content_hash)
        .eq("status", "ready")
        .single()
        .execute()
    )
    return result.data if result.data else None


# ─────────────────────────────────────────────
# Pipeline principal
# ─────────────────────────────────────────────


async def generate_roadmap(
    project_id: str,
    user_id: str,
) -> RoadmapSchema:
    """
    Génère une roadmap structurée pour un projet :
    1. Récupère le texte extrait du dernier document prêt
    2. Vérifie le cache (hash du contenu)
    3. Recherche web enrichi (Tavily + Firecrawl)
    4. Appel LLM avec prompt structuré
    5. Validation Pydantic + sauvegarde DB
    6. Retourne la RoadmapSchema complète
    """
    logger.info(f"Génération roadmap pour projet {project_id}")

    # ── 1. Récupère le contenu du document depuis la DB ──
    doc_result = (
        supabase.table("uploaded_documents")
        .select("id, extracted_text, filename")
        .eq("project_id", project_id)
        .eq("status", "ready")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if not doc_result.data:
        raise ValueError(
            "Aucun document prêt trouvé pour ce projet. "
            "Attendez la fin de l'ingestion."
        )

    doc = doc_result.data[0]
    extracted_text = doc.get("extracted_text", "")

    if not extracted_text:
        raise ValueError("Texte du document vide — ingestion incomplète.")

    # ── 2. Vérification cache ────────────────────────────
    content_hash = _compute_content_hash(extracted_text)
    cached = _get_cached_roadmap(project_id, content_hash)
    if cached:
        logger.info(f"Cache hit roadmap pour hash {content_hash}")
        return _db_to_roadmap_schema(cached)

    # ── 3. Récupère les infos du projet (subject, exam_type) ──
    project_result = (
        supabase.table("projects")
        .select(
            "title, subject, target_exam_type, deadline, hours_per_day, days_per_week"
        )
        .eq("id", project_id)
        .single()
        .execute()
    )
    project = project_result.data or {}
    subject = project.get("subject", "")
    exam_type = project.get("target_exam_type", "")

    # Exploitation du deadline
    deadline = project.get("deadline")
    hours_per_day = project.get("hours_per_day", 2.0)
    days_per_week = project.get("days_per_week", 5)

    study_plan_context = ""
    if deadline:
        from datetime import date

        try:
            deadline_date = date.fromisoformat(str(deadline))
            days_remaining = (deadline_date - date.today()).days
            total_hours = days_remaining * (days_per_week / 7) * hours_per_day
            study_plan_context = (
                f"Days until exam: {days_remaining}\n"
                f"Study hours per day: {hours_per_day}\n"
                f"Study days per week: {days_per_week}\n"
                f"Total estimated study hours available: {total_hours:.0f}h"
            )
        except Exception:
            pass
        
    # ── 4. Enrichissement web ────────────────────────────
    search_queries = _build_search_queries(extracted_text, subject, exam_type) + study_plan_context
    web_sources = []
    try:
        web_sources = await enrich_with_web(
            queries=search_queries,
            max_urls_to_crawl=2,
            search_depth="advanced",
        )
    except Exception as e:
        logger.warning(f"Web enrichment failed (continuing without): {e}")

    # ── 5. Appel LLM ─────────────────────────────────────
    user_prompt = _build_roadmap_user_prompt(
        doc_content=extracted_text,
        web_sources=web_sources,
        subject=subject,
        exam_type=exam_type,
    )

    messages = [
        {"role": "system", "content": ROADMAP_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw_output = await llm_complete(
        messages=messages,
        task="roadmap",
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    # ── 6. Parse + Validation Pydantic ───────────────────
    roadmap_schema = _parse_and_validate_roadmap(raw_output, project_id)

    # ── 7. Sauvegarde en DB ──────────────────────────────
    saved = _save_roadmap_to_db(roadmap_schema, project_id, content_hash)

    logger.info(
        f"✅ Roadmap générée: {len(roadmap_schema.chapters)} chapitres "
        f"pour projet {project_id}"
    )
    return saved


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _build_search_queries(
    extracted_text: str,
    subject: str,
    exam_type: str,
) -> list[str]:
    """
    Construit 2-3 queries de recherche web pertinentes
    à partir du contenu du document.
    """
    queries = []

    # Query principale : sujet + type d'examen
    if subject and exam_type:
        queries.append(f"{subject} {exam_type} syllabus course outline")
    elif subject:
        queries.append(f"{subject} exam preparation topics overview")

    # Query basée sur les premiers mots du document
    first_words = " ".join(extracted_text[:200].split()[:15])
    queries.append(f"{first_words} study guide chapters")

    # Fallback générique si rien d'autre
    if not queries:
        queries.append("exam preparation structured learning roadmap")

    return queries[:3]  # Max 3 queries pour limiter les coûts API


def _parse_and_validate_roadmap(
    raw_output: str,
    project_id: str,
) -> RoadmapSchema:
    """
    Parse la sortie JSON du LLM et valide via Pydantic.
    Retry une fois si la validation échoue.
    """
    try:
        data = json.loads(raw_output)
        chapters = [
            ChapterSchema(
                order_index=ch["order_index"],
                title=ch["title"],
                objective=ch.get("objective", ""),
                importance=float(ch.get("importance", 1.0)),
                status="locked",
            )
            for ch in data.get("chapters", [])
        ]

        # Le premier chapitre est toujours disponible
        if chapters:
            chapters[0].status = "available"

        return RoadmapSchema(
            project_id=project_id,
            title=data.get("title", "Revision Roadmap"),
            status="ready",
            chapters=chapters,
        )

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Roadmap parse error: {e}\nRaw: {raw_output[:500]}")
        raise ValueError(f"LLM output invalide pour roadmap: {e}")


def _save_roadmap_to_db(
    roadmap: RoadmapSchema,
    project_id: str,
    content_hash: str,
) -> RoadmapSchema:
    """
    Insère la roadmap et ses chapitres en DB.
    Retourne la roadmap avec les IDs générés par Supabase.
    """
    import uuid

    roadmap_id = str(uuid.uuid4())

    # Insère la roadmap
    supabase.table("roadmaps").insert(
        {
            "id": roadmap_id,
            "project_id": project_id,
            "title": roadmap.title,
            "status": "ready",
            "doc_content_hash": content_hash,
        }
    ).execute()

    # Insère les chapitres
    chapter_rows = [
        {
            "roadmap_id": roadmap_id,
            "order_index": ch.order_index,
            "title": ch.title,
            "objective": ch.objective,
            "importance": ch.importance,
            "status": ch.status,
        }
        for ch in roadmap.chapters
    ]
    chapters_result = supabase.table("chapters").insert(chapter_rows).execute()

    # Reconstruit la RoadmapSchema avec les vrais IDs
    saved_chapters = [
        ChapterSchema(
            id=row["id"],
            roadmap_id=roadmap_id,
            order_index=row["order_index"],
            title=row["title"],
            objective=row["objective"],
            importance=row["importance"],
            status=row["status"],
        )
        for row in (chapters_result.data or [])
    ]

    roadmap.id = uuid.UUID(roadmap_id)
    roadmap.chapters = saved_chapters
    return roadmap


def _db_to_roadmap_schema(data: dict) -> RoadmapSchema:
    """Convertit un dict DB (avec chapters imbriqués) en RoadmapSchema."""
    import uuid

    chapters = [
        ChapterSchema(
            id=uuid.UUID(ch["id"]),
            roadmap_id=uuid.UUID(ch["roadmap_id"]),
            order_index=ch["order_index"],
            title=ch["title"],
            objective=ch.get("objective", ""),
            importance=ch.get("importance", 1.0),
            status=ch.get("status", "locked"),
        )
        for ch in sorted(data.get("chapters", []), key=lambda x: x["order_index"])
    ]
    return RoadmapSchema(
        id=uuid.UUID(data["id"]),
        project_id=data["project_id"],
        title=data["title"],
        status=data["status"],
        chapters=chapters,
        doc_content_hash=data.get("doc_content_hash"),
    )
