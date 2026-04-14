import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from app.core.deps import get_current_user
from app.services.progress_service import ProgressService
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────

class ProgressSchema(BaseModel):
    chapter_id: uuid.UUID
    chapter_title: str
    chapter_order: int
    completion_status: str
    last_seen_at: Optional[str] = None

class ProjectProgressSummary(BaseModel):
    project_id: uuid.UUID
    total_chapters: int
    completed_chapters: int
    in_progress_chapters: int
    completion_percentage: float
    chapters: list[ProgressSchema]


# ── Routes ────────────────────────────────────────────────

@router.get("", response_model=ProjectProgressSummary, summary="Progression complète d'un projet")
async def get_progress(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    try:
        data = ProgressService.get_project_summary(
            project_id=str(project_id),
            user_id=current_user["user_id"],
        )
        return ProjectProgressSummary(**data)
    except PermissionError as e:
        raise HTTPException(status_code=404, detail=str(e))
