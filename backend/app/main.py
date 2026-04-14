from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1 import documents, roadmap, chapters, exam, progress, projects, sources

app = FastAPI(
    title="PassExamAI Backend",
    description="AI-powered exam preparation platform — GCD4F 2026",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api/v1/projects", tags=["Projects"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
app.include_router(roadmap.router, prefix="/api/v1/roadmap", tags=["Roadmap"])
app.include_router(chapters.router, prefix="/api/v1/chapters", tags=["Chapters"])
app.include_router(exam.router, prefix="/api/v1/exam", tags=["Exam"])
app.include_router(progress.router, prefix="/api/v1/progress", tags=["Progress"])
app.include_router(sources.router, prefix="/api/v1/sources", tags=["Sources"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "PassExamAI Backend"}