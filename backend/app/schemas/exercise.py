from pydantic import BaseModel, Field
from typing import Optional, List, Literal
import uuid

QuestionType = Literal["mcq", "short_answer", "structured"]


class MCQOption(BaseModel):
    label: str     # "A", "B", "C", "D"
    content: str


class RubricStep(BaseModel):
    description: str
    points: float


class ExerciseSchema(BaseModel):
    id: Optional[uuid.UUID] = None
    chapter_id: Optional[uuid.UUID] = None
    question_type: QuestionType
    prompt: str
    options: Optional[List[MCQOption]] = None          # MCQ seulement
    correct_answer: Optional[str] = None               # MCQ : "A"
    expected_answer_schema: Optional[List[RubricStep]] = None
    difficulty: int = Field(default=2, ge=1, le=3)

class ExerciseRequest(BaseModel):
    count: int = 5
    types: Optional[list[str]] = None


class GradingResult(BaseModel):
    exercise_id: Optional[uuid.UUID] = None
    score: float = Field(..., ge=0.0, le=100.0)
    is_correct: bool
    feedback: str
    correct_answer: Optional[str] = None
    improvement_suggestions: List[str] = []
    

class GradeRequest(BaseModel):
    answer: str