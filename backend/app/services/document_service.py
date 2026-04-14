import uuid
import logging
from typing import Optional
from fastapi import BackgroundTasks
from app.db.supabase_client import supabase
from app.rag.ingestion import run_ingestion_pipeline
from app.schemas.documents import (
    DocumentIngestRequest,
    DocumentIngestResponse,
    DocumentStatusResponse,
    DocumentSchema,
)

logger = logging.getLogger(__name__)


class DocumentService:

    @staticmethod
    def get_project_for_user(project_id: str, user_id: str) -> Optional[dict]:
        result = (
            supabase.table("projects")
            .select("id")
            .eq("id", project_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        return result.data

    @staticmethod
    def start_ingestion(
        request: DocumentIngestRequest,
        user_id: str,
        background_tasks: BackgroundTasks,
    ) -> DocumentIngestResponse:
        """
        Crée l'entrée DB et lance le pipeline en tâche de fond.
        Lève ValueError si le projet n'appartient pas à l'utilisateur.
        """
        project = DocumentService.get_project_for_user(str(request.project_id), user_id)
        if not project:
            raise ValueError("Projet introuvable ou accès refusé")

        doc_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())

        supabase.table("uploaded_documents").insert({
            "id": doc_id,
            "project_id": str(request.project_id),
            "filename": request.filename,
            "storage_url": request.storage_url,
            "source_type": request.source_type,
            "status": "uploaded",
        }).execute()

        background_tasks.add_task(
            run_ingestion_pipeline,
            document_id=doc_id,
            storage_url=request.storage_url,
            project_id=str(request.project_id),
            source_type=request.source_type,
            filename=request.filename,
        )

        logger.info(f"Ingestion lancée: doc_id={doc_id}, user={user_id}")

        return DocumentIngestResponse(
            document_id=uuid.UUID(doc_id),
            job_id=job_id,
            status="uploaded",
            message="Ingestion démarrée. Pollez GET /documents/{id}/status",
        )

    @staticmethod
    def get_status(document_id: str, user_id: str) -> Optional[DocumentStatusResponse]:
        """
        Retourne le statut du document.
        Retourne None si introuvable, lève PermissionError si accès refusé.
        """
        response = (
            supabase.table("uploaded_documents")
            .select("id, status, chunks_count, error_message, filename, project_id")
            .eq("id", document_id)
            .single()
            .execute()
        )
        if not response.data:
            return None

        doc = response.data
        project = DocumentService.get_project_for_user(doc["project_id"], user_id)
        if not project:
            raise PermissionError("Accès refusé")

        return DocumentStatusResponse(
            document_id=uuid.UUID(doc["id"]),
            status=doc["status"],
            chunks_count=doc.get("chunks_count", 0),
            error_message=doc.get("error_message"),
            filename=doc["filename"],
        )

    @staticmethod
    def list_by_project(project_id: str, user_id: str) -> list[dict]:
        """Lève ValueError si le projet n'appartient pas à l'utilisateur."""
        project = DocumentService.get_project_for_user(project_id, user_id)
        if not project:
            raise ValueError("Projet introuvable")

        result = (
            supabase.table("uploaded_documents")
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    @staticmethod
    def delete(document_id: str, user_id: str) -> bool:
        """
        Retourne False si introuvable.
        Lève PermissionError si accès refusé.
        """
        doc = (
            supabase.table("uploaded_documents")
            .select("id, project_id, storage_url")
            .eq("id", document_id)
            .single()
            .execute()
        )
        if not doc.data:
            return False

        project = DocumentService.get_project_for_user(doc.data["project_id"], user_id)
        if not project:
            raise PermissionError("Accès refusé")

        supabase.table("uploaded_documents").delete().eq("id", document_id).execute()
        logger.info(f"Document {document_id} supprimé")
        return True
