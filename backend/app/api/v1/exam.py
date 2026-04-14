import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from app.core.deps import get_current_user
from app.services.exam_service import ExamService
from app.schemas.exam import ExamSchema, ExamGenerateRequest, ExamResult
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class SubmitAnswerItem(BaseModel):
    question_id: str
    answer: str

class ExamSubmitRequest(BaseModel):
    answers: list[SubmitAnswerItem]


@router.post("/generate", response_model=ExamSchema, summary="Génère un examen blanc complet")
async def generate_exam_endpoint(
    request: ExamGenerateRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await ExamService.generate(
            roadmap_id=str(request.roadmap_id),
            user_id=current_user["user_id"],
            question_count=request.question_count,
            time_limit=request.time_limit,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Exam generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{exam_id}", response_model=ExamSchema, summary="Récupère un examen avec ses questions")
async def get_exam(
    exam_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
):
    try:
        return ExamService.get_by_id(str(exam_id), current_user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{exam_id}/submit", response_model=ExamResult, summary="Soumet les réponses et retourne le score")
async def submit_exam(
    exam_id: uuid.UUID,
    request: ExamSubmitRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        return await ExamService.submit(
            exam_id=str(exam_id),
            user_id=current_user["user_id"],
            answers=request.answers,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Exam submit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
