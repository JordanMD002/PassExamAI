import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.deps import get_current_user
from app.services.chapter_service import ChapterService, TUTOR_SYSTEM_PROMPT
from app.schemas.lesson import LessonSchema, LessonRequest
from app.schemas.exercise import ExerciseSchema, GradingResult, ExerciseRequest, GradeRequest
from app.schemas.chat import ChatMessage, ChatRequest
from app.rag.gap_detector import enrich_if_needed
from app.ai.llm_client import llm_complete
from app.core.config import settings
from app.rag.query_rewriter import rewrite_query


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/{chapter_id}/lesson", response_model=LessonSchema, summary="Génère ou récupère la leçon")
async def get_or_generate_lesson(
    chapter_id: uuid.UUID,
    request: LessonRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await ChapterService.get_or_create_lesson(
            chapter_id=str(chapter_id),
            user_id=current_user["user_id"],
            use_web_enrichment=request.use_web_enrichment,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{chapter_id}/chat", summary="Tuteur IA contextuel — réponse en streaming")
async def chapter_chat(
    chapter_id: uuid.UUID,
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    chapter, project_id = ChapterService.get_chapter_with_project(
        str(chapter_id), current_user["user_id"]
    )
    chapter_title = chapter["title"]

    # ── 1. Query rewriting ─────────────────────────────────
    rewritten_query = await rewrite_query(
        user_question=request.message,
        chapter_context=chapter_title,
    )

    # ── 2. RAG + web fallback INTELLIGENT ─────────────────
    # Le web n'est utilisé QUE si le RAG est insuffisant
    rag_chunks, web_sources, web_was_used = await enrich_if_needed(
        query=rewritten_query,
        project_id=project_id,
        chapter_hint=chapter_title,
        top_k=settings.top_k_final,
        context_label="chat",
    )

    # ── 3. Construit le contexte ───────────────────────────
    rag_context = "\n\n".join(
        f"[Source {i+1} — score {c.get('similarity', 0):.2f}]: "
        f"{c.get('content', '')[:800]}"
        for i, c in enumerate(rag_chunks)
    ) if rag_chunks else "No relevant content found in your documents."

    web_context = ""
    if web_was_used and web_sources:
        web_parts = [
            f"[Web: {s['title']}] {s['content'][:500]} ({s['url']})"
            for s in web_sources[:2]
        ]
        web_context = (
            "\n\nNote: Your documents didn't fully cover this topic. "
            "Supplementary web sources were used:\n"
            + "\n\n".join(web_parts)
        )

    context_block = f"""Current chapter: {chapter_title}
Objective: {chapter.get('objective', '')}

--- Content from YOUR study materials ---
{rag_context}
{web_context}"""

    # ── 4. Messages avec historique (3 derniers échanges) ──
    recent_history = request.history[-6:]
    messages = [
        {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
        {"role": "user", "content": f"[Study Context]\n{context_block}"},
        *[{"role": m.role, "content": m.content} for m in recent_history],
        {"role": "user", "content": request.message},
    ]

    # ── 5. Streaming ───────────────────────────────────────
    async def stream_response():
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

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{chapter_id}/exercises", response_model=list[ExerciseSchema], summary="Génère des exercices")
async def get_exercises(
    chapter_id: uuid.UUID,
    request: ExerciseRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await ChapterService.get_or_create_exercises(
            chapter_id=str(chapter_id),
            user_id=current_user["user_id"],
            count=request.count,
            types=request.types,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/exercises/{exercise_id}/grade", response_model=GradingResult, summary="Note une réponse")
async def grade_exercise(
    exercise_id: uuid.UUID,
    request: GradeRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await ChapterService.grade(
            exercise_id=str(exercise_id),
            user_id=current_user["user_id"],
            student_answer=request.answer,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{chapter_id}/complete", summary="Marque un chapitre comme terminé")
async def complete_chapter(
    chapter_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    try:
        return ChapterService.complete_chapter(
            chapter_id=str(chapter_id),
            user_id=current_user["user_id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
