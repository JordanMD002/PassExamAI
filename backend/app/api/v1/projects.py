import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.deps import get_current_user
from app.services.project_service import ProjectService
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Schemas ──────────────────────────────────────────────

class ProjectCreateRequest(BaseModel):
    title: str
    subject: Optional[str] = None
    target_exam_type: Optional[str] = None


class ProjectSchema(BaseModel):
    id: uuid.UUID
    user_id: str
    title: str
    subject: Optional[str] = None
    target_exam_type: Optional[str] = None
    created_at: Optional[datetime] = None


# ── Routes ───────────────────────────────────────────────

@router.post("", response_model=ProjectSchema, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: ProjectCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        project = ProjectService.create(
            user_id=current_user["user_id"],
            title=request.title,
            subject=request.subject,
            target_exam_type=request.target_exam_type,
        )
        return project
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=list[ProjectSchema])
async def list_projects(current_user: dict = Depends(get_current_user)):
    return ProjectService.get_all_by_user(current_user["user_id"])


@router.get("/{project_id}", response_model=ProjectSchema)
async def get_project(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    project = ProjectService.get_by_id(str(project_id), current_user["user_id"])
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    deleted = ProjectService.delete(str(project_id), current_user["user_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Projet introuvable")
