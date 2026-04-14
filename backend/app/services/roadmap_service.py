import logging
from typing import Optional
from app.db.supabase_client import supabase
from app.ai.roadmap_generator import generate_roadmap as _generate_roadmap
from app.ai.roadmap_generator import _db_to_roadmap_schema
from app.schemas.roadmap import RoadmapSchema

logger = logging.getLogger(__name__)


class RoadmapService:

    @staticmethod
    def _assert_project_ownership(project_id: str, user_id: str) -> None:
        """Lève PermissionError si le projet n'appartient pas à l'utilisateur."""
        result = (
            supabase.table("projects")
            .select("id")
            .eq("id", project_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not result.data:
            raise PermissionError("Projet introuvable ou accès refusé")

    @staticmethod
    async def generate(project_id: str, user_id: str) -> RoadmapSchema:
        """
        Vérifie ownership, puis délègue au générateur IA.
        Lève PermissionError ou ValueError selon le cas.
        """
        RoadmapService._assert_project_ownership(project_id, user_id)
        return await _generate_roadmap(project_id=project_id, user_id=user_id)

    @staticmethod
    def get_by_id(roadmap_id: str, user_id: str) -> Optional[RoadmapSchema]:
        """
        Retourne la roadmap ou None si introuvable.
        Lève PermissionError si accès refusé.
        """
        result = (
            supabase.table("roadmaps")
            .select("*, chapters(*)")
            .eq("id", roadmap_id)
            .single()
            .execute()
        )
        if not result.data:
            return None

        # Vérifie ownership via le projet
        RoadmapService._assert_project_ownership(result.data["project_id"], user_id)
        return _db_to_roadmap_schema(result.data)

    @staticmethod
    def list_by_project(project_id: str, user_id: str) -> list[RoadmapSchema]:
        """Lève PermissionError si le projet n'appartient pas à l'utilisateur."""
        RoadmapService._assert_project_ownership(project_id, user_id)

        result = (
            supabase.table("roadmaps")
            .select("*, chapters(*)")
            .eq("project_id", project_id)
            .eq("status", "ready")
            .order("created_at", desc=True)
            .execute()
        )
        return [_db_to_roadmap_schema(row) for row in (result.data or [])]
