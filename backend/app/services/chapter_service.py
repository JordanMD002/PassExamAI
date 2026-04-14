import logging
from typing import Optional, AsyncGenerator
from app.db.supabase_client import supabase
from app.ai.lesson_generator import generate_lesson
from app.ai.exercise_generator import generate_exercises
from app.ai.grader import grade_answer
from app.ai.llm_client import llm_complete
from app.rag.retrieval import retrieve_chunks
from app.rag.query_rewriter import rewrite_query
from app.web.tavily_client import tavily_search
from app.schemas.lesson import LessonSchema
from app.schemas.exercise import ExerciseSchema, GradingResult

logger = logging.getLogger(__name__)

TUTOR_SYSTEM_PROMPT = """You are a focused, expert AI tutor helping a student prepare for an exam.
You answer questions strictly within the scope of the current chapter.
Ground your answers in the provided document chunks and web sources.
Always cite which source supports each key claim.
Keep answers clear, structured, and educational.
If you use a web source, mention the URL.
"""


class ChapterService:

    @staticmethod
    def get_chapter_with_project(chapter_id: str, user_id: str) -> tuple[dict, str]:
        """
        Vérifie que l'utilisateur a accès au chapitre.
        Retourne (chapter_data, project_id).
        Lève ValueError si introuvable, PermissionError si accès refusé.
        """
        ch = (
            supabase.table("chapters")
            .select("id, title, objective, roadmap_id, status")
            .eq("id", chapter_id)
            .single()
            .execute()
        )
        if not ch.data:
            raise ValueError("Chapitre introuvable")

        roadmap = (
            supabase.table("roadmaps")
            .select("id, project_id")
            .eq("id", ch.data["roadmap_id"])
            .single()
            .execute()
        )
        if not roadmap.data:
            raise ValueError("Roadmap introuvable")

        project = (
            supabase.table("projects")
            .select("id")
            .eq("id", roadmap.data["project_id"])
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not project.data:
            raise PermissionError("Accès refusé")

        return ch.data, roadmap.data["project_id"]

    # ── Lesson ───────────────────────────────────────────

    @staticmethod
    async def get_or_create_lesson(
        chapter_id: str,
        user_id: str,
        use_web_enrichment: bool = True,
    ) -> LessonSchema:
        chapter, project_id = ChapterService.get_chapter_with_project(chapter_id, user_id)

        # Met à jour le statut en in_progress
        ChapterService._mark_in_progress(chapter_id, user_id)

        return await generate_lesson(
            chapter_id=chapter_id,
            project_id=project_id,
            use_web_enrichment=use_web_enrichment,
        )

    # ── Chat (tuteur IA streaming) ────────────────────────

    @staticmethod
    async def build_chat_messages(
        chapter_id: str,
        user_id: str,
        message: str,
        history: list,
    ) -> list[dict]:
        """
        Prépare la liste de messages enrichis (RAG + web) pour le LLM.
        Séparé du streaming pour faciliter les tests unitaires.
        """
        chapter, project_id = ChapterService.get_chapter_with_project(chapter_id, user_id)
        chapter_title = chapter["title"]

        # Query rewriting
        rewritten_query = await rewrite_query(
            user_question=message,
            chapter_context=chapter_title,
        )

        # RAG retrieval
        rag_chunks = await retrieve_chunks(
            query=rewritten_query,
            project_id=project_id,
            chapter_hint=chapter_title,
            top_k=3,
        )
        rag_context = "\n\n".join(
            f"[Doc chunk {i+1}]: {c.get('content', '')[:800]}"
            for i, c in enumerate(rag_chunks)
        )

        # Tavily web search
        web_context = ""
        try:
            web_results = await tavily_search(
                query=f"{chapter_title} {rewritten_query}",
                max_results=2,
                search_depth="basic",
            )
            if web_results:
                web_context = "\n\n".join(
                    f"[Web: {r['title']}] {r['content'][:500]} (source: {r['url']})"
                    for r in web_results
                )
        except Exception as e:
            logger.warning(f"Tavily chat search failed: {e}")

        context_block = (
            f"Current chapter: {chapter_title}\n"
            f"Objective: {chapter.get('objective', '')}\n\n"
            f"Document context:\n{rag_context or 'No relevant chunks found.'}\n\n"
            f"Web context:\n{web_context or 'No web results.'}"
        )

        # Garde les 3 derniers échanges (6 messages) pour le budget contexte
        recent_history = history[-6:]

        return [
            {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
            {"role": "user", "content": f"[Context]\n{context_block}"},
            *[{"role": m.role, "content": m.content} for m in recent_history],
            {"role": "user", "content": message},
        ]

    @staticmethod
    async def stream_chat(
        chapter_id: str,
        user_id: str,
        message: str,
        history: list,
    ) -> AsyncGenerator[str, None]:
        """
        Générateur async — yield les tokens du LLM au fur et à mesure.
        Géré proprement pour que le router soit un simple pass-through.
        """
        messages = await ChapterService.build_chat_messages(
            chapter_id, user_id, message, history
        )
        try:
            stream = await llm_complete(
                messages=messages,
                task="chat",
                stream=True,
                max_tokens=1500,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield f"\n[Error: {str(e)}]"

    # ── Exercises ─────────────────────────────────────────

    @staticmethod
    async def get_or_create_exercises(
        chapter_id: str,
        user_id: str,
        count: int = 5,
        types: Optional[list[str]] = None,
    ) -> list:
        chapter, project_id = ChapterService.get_chapter_with_project(chapter_id, user_id)

        # Cache : exercices déjà générés ?
        existing = (
            supabase.table("exercises")
            .select("*")
            .eq("chapter_id", chapter_id)
            .execute()
        )
        if existing.data:
            logger.info(f"Cache hit exercices pour chapitre {chapter_id}")
            return existing.data

        return await generate_exercises(
            chapter_id=chapter_id,
            project_id=project_id,
            count=count,
            types=types,
        )

    # ── Grading ───────────────────────────────────────────

    @staticmethod
    async def grade(exercise_id: str, user_id: str, student_answer: str) -> GradingResult:
        return await grade_answer(
            exercise_id=exercise_id,
            user_id=user_id,
            student_answer=student_answer,
        )

    # ── Completion ────────────────────────────────────────

    @staticmethod
    def complete_chapter(chapter_id: str, user_id: str) -> dict:
        chapter, _ = ChapterService.get_chapter_with_project(chapter_id, user_id)

        current = (
            supabase.table("chapters")
            .select("order_index, roadmap_id")
            .eq("id", chapter_id)
            .single()
            .execute()
        )
        current_order = current.data["order_index"]
        roadmap_id = current.data["roadmap_id"]

        supabase.table("chapters").update({"status": "completed"}).eq("id", chapter_id).execute()
        supabase.table("progress").upsert({
            "user_id": user_id,
            "chapter_id": chapter_id,
            "completion_status": "completed",
        }, on_conflict="user_id,chapter_id").execute()

        # Déverrouille le chapitre suivant
        next_ch = (
            supabase.table("chapters")
            .select("id")
            .eq("roadmap_id", roadmap_id)
            .eq("order_index", current_order + 1)
            .single()
            .execute()
        )
        if next_ch.data:
            supabase.table("chapters").update({"status": "available"}).eq(
                "id", next_ch.data["id"]
            ).execute()
            logger.info(f"Chapitre suivant déverrouillé: {next_ch.data['id']}")

        logger.info(f"Chapitre {chapter_id} marqué comme terminé par user {user_id}")
        return {"status": "completed", "chapter_id": chapter_id}

    # ── Private helpers ───────────────────────────────────

    @staticmethod
    def _mark_in_progress(chapter_id: str, user_id: str) -> None:
        supabase.table("chapters").update({"status": "in_progress"}).eq(
            "id", chapter_id
        ).execute()
        supabase.table("progress").upsert({
            "user_id": user_id,
            "chapter_id": chapter_id,
            "completion_status": "in_progress",
        }, on_conflict="user_id,chapter_id").execute()
