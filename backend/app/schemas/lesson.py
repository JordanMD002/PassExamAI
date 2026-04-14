from pydantic import BaseModel, Field
from typing import Optional, List
import uuid


class SourceReference(BaseModel):
    type: str  # 'doc' | 'web'
    url: Optional[str] = None
    excerpt: str
    chunk_id: Optional[str] = None


class ExampleSchema(BaseModel):
    title: str
    content: str


class LessonSchema(BaseModel):
    id: Optional[uuid.UUID] = None
    chapter_id: Optional[uuid.UUID] = None
    content: str = Field(..., description="Contenu principal en Markdown")
    examples: List[ExampleSchema] = []
    source_references: List[SourceReference] = []
    visual_aids_description: Optional[str] = None
    
    
class LessonRequest(BaseModel):
    use_web_enrichment: bool = True