import uuid
import logging
from app.db.supabase_client import supabase

logger = logging.getLogger(__name__)


class ProgressService:

    @staticmethod
    def get_project_summary(project_id: str, user_id: str) -> dict:
        """
        Retourne le résumé complet de progression pour un projet.
        Lève PermissionError si le projet n'appartient pas à l'utilisateur.
        """
        # Vérifie ownership
        project = (
            supabase.table("projects")
            .select("id")
            .eq("id", project_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not project.data:
            raise PermissionError("Projet introuvable ou accès refusé")

        # Roadmap active
        roadmap = (
            supabase.table("roadmaps")
            .select("id")
            .eq("project_id", project_id)
            .eq("status", "ready")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if not roadmap.data:
            return {
                "project_id": project_id,
                "total_chapters": 0,
                "completed_chapters": 0,
                "in_progress_chapters": 0,
                "completion_percentage": 0.0,
                "chapters": [],
            }

        roadmap_id = roadmap.data[0]["id"]

        # Tous les chapitres
        chapters_result = (
            supabase.table("chapters")
            .select("id, title, order_index, status")
            .eq("roadmap_id", roadmap_id)
            .order("order_index")
            .execute()
        )

        # Progression utilisateur indexée par chapter_id
        progress_result = (
            supabase.table("progress")
            .select("chapter_id, completion_status, last_seen_at")
            .eq("user_id", user_id)
            .execute()
        )
        progress_map = {
            str(p["chapter_id"]): p for p in (progress_result.data or [])
        }

        chapters = []
        completed = 0
        in_progress = 0

        for ch in (chapters_result.data or []):
            ch_id = str(ch["id"])
            prog = progress_map.get(ch_id)

            # Priorité : table progress > table chapters (source de vérité utilisateur)
            comp_status = prog["completion_status"] if prog else ch.get("status", "locked")

            if comp_status == "completed":
                completed += 1
            elif comp_status == "in_progress":
                in_progress += 1

            chapters.append({
                "chapter_id": ch["id"],
                "chapter_title": ch["title"],
                "chapter_order": ch["order_index"],
                "completion_status": comp_status,
                "last_seen_at": prog["last_seen_at"] if prog else None,
            })

        total = len(chapters)
        percentage = round((completed / total * 100), 1) if total > 0 else 0.0

        return {
            "project_id": project_id,
            "total_chapters": total,
            "completed_chapters": completed,
            "in_progress_chapters": in_progress,
            "completion_percentage": percentage,
            "chapters": chapters,
        }
