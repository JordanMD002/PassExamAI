from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

    # LLM
    openai_api_key: str
    gemini_api_key: str
    groq_api_key: str
    openrouter_api_key: str

    # Parsing
    llama_parse_api_key: str

    # Web Search
    tavily_api_key: str
    firecrawl_api_key: str

    # App
    environment: str = "development"
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

# LLM Routing — modèles par tâche (FULL GROQ)
    
    # Raisonnement complexe, analyse de documents et pédagogie (70B)
    model_roadmap: str = "groq/llama-3.3-70b-versatile"
    model_exam: str = "groq/llama-3.3-70b-versatile"
    model_grader: str = "groq/llama-3.3-70b-versatile"
    
    # Interaction rapide, exercices et réécriture (70B ou 8B selon besoin de précision)
    model_chat: str = "groq/llama-3.3-70b-versatile"
    model_lesson: str = "groq/llama-3.3-70b-versatile"
    model_exercise: str = "groq/llama-3.3-70b-versatile"
    
    # Tâches utilitaires ultra-rapides (8B)
    model_query_rewriter: str = "groq/llama-3.1-8b-instant"
    
    # Embeddings (On garde Gemini car Groq ne fait pas d'embeddings)
    model_embeddings: str = "gemini/text-embedding-004"
    embedding_dimensions: int = 768

    # RAG
    chunk_size: int = 512
    chunk_overlap: int = 50
    top_k_retrieval: int = 10
    top_k_final: int = 3
    rag_similarity_threshold: float = 0.45  # En dessous → web search activé
    rag_min_chunks_threshold: int = 2  # Moins de N chunks pertinents → web search


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
