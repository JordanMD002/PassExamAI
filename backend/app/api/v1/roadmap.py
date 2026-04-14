import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.deps import get_current_user
from app.services.roadmap_service import RoadmapService
from app.schemas.roadmap import RoadmapSchema, RoadmapGenerateRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/generate",
    response_model=RoadmapSchema,
    summary="Génère la roadmap (RAG + web enrichment) — 10 à 30s",
)
async def generate_roadmap_endpoint(
    request: RoadmapGenerateRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await RoadmapService.generate(
            project_id=str(request.project_id),
            user_id=current_user["user_id"],
        )
    except PermissionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Roadmap generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{roadmap_id}", response_model=RoadmapSchema, summary="Récupère une roadmap")
async def get_roadmap(
    roadmap_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    try:
        roadmap = RoadmapService.get_by_id(str(roadmap_id), current_user["user_id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not roadmap:
        raise HTTPException(status_code=404, detail="Roadmap introuvable")
    return roadmap


@router.get("", response_model=list[RoadmapSchema], summary="Liste les roadmaps d'un projet")
async def list_roadmaps(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    try:
        return RoadmapService.list_by_project(str(project_id), current_user["user_id"])
    except PermissionError as e:
        raise HTTPException(status_code=404, detail=str(e))
