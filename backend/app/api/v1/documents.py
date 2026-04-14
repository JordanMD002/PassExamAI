import uuid
import logging
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, status
from app.core.deps import get_current_user
from app.services.document_service import DocumentService
from app.schemas.documents import (
    DocumentIngestRequest,
    DocumentIngestResponse,
    DocumentStatusResponse,
    DocumentSchema,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/ingest",
    response_model=DocumentIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Lance l'ingestion d'un document PDF",
)
async def ingest_document(
    request: DocumentIngestRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    try:
        return DocumentService.start_ingestion(request, current_user["user_id"], background_tasks)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Statut de l'ingestion (à poller toutes les 3s)",
)
async def get_document_status(
    document_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    try:
        doc_status = DocumentService.get_status(str(document_id), current_user["user_id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not doc_status:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return doc_status


@router.get("", response_model=list[DocumentSchema], summary="Liste les documents d'un projet")
async def list_documents(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    try:
        return DocumentService.list_by_project(str(project_id), current_user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    try:
        deleted = DocumentService.delete(str(document_id), current_user["user_id"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    if not deleted:
        raise HTTPException(status_code=404, detail="Document introuvable")
