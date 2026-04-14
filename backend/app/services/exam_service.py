import uuid
import json
import logging
from typing import Optional
from app.db.supabase_client import supabase
from app.ai.exam_generator import generate_exam as _generate_exam
from app.ai.llm_client import llm_complete
from app.schemas.exam import (
    ExamSchema,
    ExamQuestionSchema,
    ExamResult,
    SectionScore,
)
from app.schemas.exercise import MCQOption, RubricStep

logger = logging.getLogger(__name__)


class ExamService:

    @staticmethod
    def _assert_exam_ownership(exam_id: str, user_id: str) -> dict:
        """
        Vérifie ownership roadmap → projet → user.
        Retourne les données de l'examen.
        Lève ValueError si introuvable, PermissionError si accès refusé.
        """
        exam_data = (
            supabase.table("mock_exams")
            .select("*, exam_questions(*)")
            .eq("id", exam_id)
            .single()
            .execute()
        )
        if not exam_data.data:
            raise ValueError("Examen introuvable")

        roadmap = (
            supabase.table("roadmaps")
            .select("project_id")
            .eq("id", exam_data.data["roadmap_id"])
            .single()
            .execute()
        )
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

        return exam_data.data

    @staticmethod
    async def generate(
        roadmap_id: str,
        user_id: str,
        question_count: int = 10,
        time_limit: Optional[int] = None,
    ) -> ExamSchema:
        """
        Vérifie ownership de la roadmap, puis génère l'examen.
        Lève PermissionError ou ValueError selon le cas.
        """
        roadmap = (
            supabase.table("roadmaps")
            .select("id, project_id")
            .eq("id", roadmap_id)
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

        return await _generate_exam(
            roadmap_id=roadmap_id,
            question_count=question_count,
            time_limit=time_limit,
        )

    @staticmethod
    def get_by_id(exam_id: str, user_id: str) -> ExamSchema:
        """Lève ValueError ou PermissionError."""
        data = ExamService._assert_exam_ownership(exam_id, user_id)
        return ExamService._db_to_schema(data)

    @staticmethod
    async def submit(
        exam_id: str,
        user_id: str,
        answers: list,
    ) -> ExamResult:
        """
        Score chaque réponse, génère le feedback global, sauvegarde la soumission.
        Retourne l'ExamResult complet.
        """
        ExamService._assert_exam_ownership(exam_id, user_id)

        questions_result = (
            supabase.table("exam_questions")
            .select("*")
            .eq("mock_exam_id", exam_id)
            .execute()
        )
        questions = {str(q["id"]): q for q in (questions_result.data or [])}
        if not questions:
            raise ValueError("Aucune question trouvée pour cet examen")

        total_score = 0.0
        max_score = 0.0
        chapter_scores: dict[str, dict] = {}

        for item in answers:
            q = questions.get(item.question_id)
            if not q:
                continue

            max_pts = float(q.get("points", 1.0))
            max_score += max_pts
            chapter_id = q.get("chapter_id") or "unknown"

            if chapter_id not in chapter_scores:
                chapter_scores[chapter_id] = {
                    "score": 0.0,
                    "max": 0.0,
                    "title": ExamService._get_chapter_title(chapter_id),
                }
            chapter_scores[chapter_id]["max"] += max_pts

            if q["question_type"] == "mcq":
                pts = ExamService._score_mcq(q, item.answer, max_pts)
            else:
                pts = await ExamService._score_open_answer(q, item.answer, max_pts)

            total_score += pts
            chapter_scores[chapter_id]["score"] += pts

        percentage = (total_score / max_score * 100) if max_score > 0 else 0.0
        feedback = await ExamService._generate_feedback(percentage, chapter_scores)

        submission = supabase.table("exam_submissions").insert({
            "mock_exam_id": exam_id,
            "user_id": user_id,
            "total_score": round(total_score, 2),
            "section_scores": {
                cid: {"score": v["score"], "max": v["max"], "title": v["title"]}
                for cid, v in chapter_scores.items()
            },
            "feedback": feedback,
        }).execute()

        submission_id = submission.data[0]["id"] if submission.data else str(uuid.uuid4())

        section_scores = [
            SectionScore(
                chapter_id=cid,
                chapter_title=v["title"],
                score=round(v["score"], 2),
                max_score=v["max"],
            )
            for cid, v in chapter_scores.items()
        ]

        return ExamResult(
            submission_id=uuid.UUID(submission_id),
            total_score=round(total_score, 2),
            max_score=max_score,
            percentage=round(percentage, 1),
            section_scores=section_scores,
            feedback=feedback,
        )

    # ── Private helpers ───────────────────────────────────

    @staticmethod
    def _get_chapter_title(chapter_id: str) -> str:
        if chapter_id == "unknown":
            return ""
        result = (
            supabase.table("chapters")
            .select("title")
            .eq("id", chapter_id)
            .single()
            .execute()
        )
        return result.data.get("title", "") if result.data else ""

    @staticmethod
    def _score_mcq(question: dict, answer: str, max_pts: float) -> float:
        correct = (question.get("correct_answer") or "").strip().upper()
        return max_pts if answer.strip().upper() == correct else 0.0

    @staticmethod
    async def _score_open_answer(question: dict, answer: str, max_pts: float) -> float:
        rubric = question.get("rubric") or []
        rubric_text = "\n".join(
            f"- {s['description']} ({s['points']} pts)" for s in rubric
        ) or "Award points proportionally based on correctness."

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict exam grader. "
                    "Output ONLY a JSON object: {\"score\": float, \"max\": float} "
                    "where score is points awarded out of max."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question['prompt']}\n"
                    f"Rubric (max {max_pts} pts):\n{rubric_text}\n"
                    f"Student answer: {answer}\n"
                    "Grade it."
                ),
            },
        ]
        try:
            raw = await llm_complete(
                messages=messages,
                task="grader",
                max_tokens=100,
                response_format={"type": "json_object"},
            )
            data = json.loads(raw)
            return min(float(data.get("score", 0)), max_pts)
        except Exception as e:
            logger.warning(f"Open answer scoring failed: {e}")
            return 0.0

    @staticmethod
    async def _generate_feedback(percentage: float, chapter_scores: dict) -> str:
        weak_chapters = [
            v["title"]
            for v in chapter_scores.values()
            if v["max"] > 0 and (v["score"] / v["max"]) < 0.5
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a supportive academic coach. "
                    "Write a 3-4 sentence exam feedback in English. "
                    "Be specific about weak areas. Be encouraging but honest."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Student scored {percentage:.1f}% overall.\n"
                    f"Weak chapters (< 50%): {', '.join(weak_chapters) or 'None'}.\n"
                    "Write the feedback."
                ),
            },
        ]
        try:
            return await llm_complete(messages=messages, task="grader", max_tokens=300)
        except Exception:
            return f"You scored {percentage:.1f}%. Keep studying and reviewing weak areas."

    @staticmethod
    def _db_to_schema(data: dict) -> ExamSchema:
        questions = []
        for q in sorted(data.get("exam_questions", []), key=lambda x: x.get("order_index", 0)):
            options = [MCQOption(**o) for o in (q.get("options") or [])] or None
            rubric = [RubricStep(**r) for r in (q.get("rubric") or [])] or None
            questions.append(
                ExamQuestionSchema(
                    id=uuid.UUID(q["id"]),
                    chapter_id=uuid.UUID(q["chapter_id"]) if q.get("chapter_id") else None,
                    question_type=q["question_type"],
                    prompt=q["prompt"],
                    options=options,
                    correct_answer=q.get("correct_answer"),
                    rubric=rubric,
                    points=q.get("points", 1.0),
                    order_index=q.get("order_index", 0),
                )
            )
        return ExamSchema(
            id=uuid.UUID(data["id"]),
            roadmap_id=uuid.UUID(data["roadmap_id"]),
            title=data["title"],
            time_limit=data.get("time_limit"),
            question_count=data.get("question_count", len(questions)),
            questions=questions,
        )
