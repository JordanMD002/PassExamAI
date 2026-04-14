# app/api/v1/sources.py

import uuid
import logging
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, status
from app.core.deps import get_current_user
from app.db.supabase_client import supabase
from app.rag.ingestion_links import ingest_user_link
from pydantic import BaseModel, HttpUrl
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


class SourceAddRequest(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    project_id: uuid.UUID


class SourceSchema(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    title: Optional[str] = None
    status: str
    chunks_count: int = 0
    error_message: Optional[str] = None


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ajoute un lien comme source d'étude",
)
async def add_source(
    request: SourceAddRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    # Vérifie ownership projet
    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", str(request.project_id))
        .eq("user_id", current_user["user_id"])
        .single()
        .execute()
    )
    if not project.data:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    source_id = str(uuid.uuid4())
    supabase.table("user_sources").insert({
        "id": source_id,
        "project_id": str(request.project_id),
        "url": request.url,
        "title": request.title,
        "description": request.description,
        "status": "pending",
    }).execute()

    # Lance l'ingestion en arrière-plan (même pattern que les PDFs)
    background_tasks.add_task(
        ingest_user_link,
        source_id=source_id,
        url=request.url,
        project_id=str(request.project_id),
    )

    return {"source_id": source_id, "status": "pending", "message": "Ingestion démarrée"}


@router.get(
    "",
    response_model=list[SourceSchema],
    summary="Liste les sources d'un projet",
)
async def list_sources(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    project = (
        supabase.table("projects").select("id")
        .eq("id", str(project_id))
        .eq("user_id", current_user["user_id"])
        .single().execute()
    )
    if not project.data:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    result = (
        supabase.table("user_sources")
        .select("*")
        .eq("project_id", str(project_id))
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


@router.get("/{source_id}/status", summary="Statut d'ingestion d'une source")
async def get_source_status(
    source_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("user_sources").select("*")
        .eq("id", str(source_id)).single().execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Source introuvable")
    return result.data