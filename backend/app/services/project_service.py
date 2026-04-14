import logging
from typing import Optional
from app.db.supabase_client import supabase

logger = logging.getLogger(__name__)


class ProjectService:

    @staticmethod
    def create(user_id: str, title: str, subject: Optional[str], target_exam_type: Optional[str]) -> dict:
        logger.info(f"Creating project for user {user_id}: {title}")
        result = supabase.table("projects").insert({
            "user_id": user_id,
            "title": title,
            "subject": subject,
            "target_exam_type": target_exam_type,
        }).execute()

        if not result.data:
            raise RuntimeError("Erreur lors de la création du projet")

        logger.info(f"Project created: {result.data[0]['id']}")
        return result.data[0]

    @staticmethod
    def get_all_by_user(user_id: str) -> list[dict]:
        result = (
            supabase.table("projects")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    @staticmethod
    def get_by_id(project_id: str, user_id: str) -> Optional[dict]:
        result = (
            supabase.table("projects")
            .select("*")
            .eq("id", project_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data

    @staticmethod
    def delete(project_id: str, user_id: str) -> bool:
        """Returns False if project not found or not owned by user."""
        existing = ProjectService.get_by_id(project_id, user_id)
        if not existing:
            return False

        supabase.table("projects").delete().eq("id", project_id).execute()
        logger.info(f"Project {project_id} deleted by user {user_id}")
        return True
