"""Core configuration module."""

from pathlib import Path

from pydantic_settings import BaseSettings


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_path(value: str) -> str:
    """Resolve a path relative to the repository root when needed."""
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((PROJECT_ROOT / path).resolve())


class Settings(BaseSettings):
    APP_NAME: str = "intelligent-learning-agent"
    APP_ENV: str = "development"
    BACKEND_PORT: int = 8000

    # Database
    DATABASE_URL: str = "sqlite:///./data/app.db"

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # ChromaDB
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_COLLECTION_NAME: str = "course_chunks"

    # Embedding
    EMBEDDING_PROVIDER: str = "hash_mock"
    EMBEDDING_DIM: int = 384
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    RAG_RETRIEVAL_MODE: str = "ChromaDB course-filtered vector search"
    # Spark LLM (placeholder)
    SPARK_APP_ID: str = ""
    SPARK_API_SECRET: str = ""

    # Spark Provider — production
    SPARK_ENABLED: bool = False
    SPARK_BASE_URL: str = "https://spark-api-open.xf-yun.com/x2"
    SPARK_API_KEY: str = ""
    SPARK_API_PASSWORD: str = ""
    SPARK_MODEL: str = "spark-x"
    SPARK_TIMEOUT_SECONDS: int = 30
    SPARK_FALLBACK_PROVIDER: str = "deepseek"

    # LLM Provider
    LLM_PROVIDER: str = "deepseek"

    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-v4-pro"
    DEEPSEEK_TIMEOUT_SECONDS: int = 60

    LLM_TIMEOUT_SECONDS: int = 60
    LLM_MAX_RETRIES: int = 2

    # Virtual Human / Digital Avatar
    VIRTUAL_HUMAN_ENABLED: bool = False
    XFYUN_VH_API_KEY: str = ""
    XFYUN_VH_API_SECRET: str = ""
    XFYUN_VH_BASE_URL: str = "https://vms.cn-huadong-1.xf-yun.com"
    XFYUN_VH_AVATAR_ID: str = ""
    XFYUN_VH_VOICE_ID: str = "x4_xiaoxuan"
    VH_TIMEOUT_SECONDS: int = 30

    # Admin panel
    ADMIN_ENABLED: bool = False

    # File upload
    FILE_UPLOAD_MAX_MB: int = 80

    # Generated files
    GENERATED_DIR: str = "./data/generated"

    model_config = {
        "env_file": [".env", "../.env"],  # CWD first, then project root fallback
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
settings.DATABASE_URL = _resolve_path(settings.DATABASE_URL.replace("sqlite:///./", "", 1)) if settings.DATABASE_URL.startswith("sqlite:///./") else settings.DATABASE_URL
settings.CHROMA_PERSIST_DIR = _resolve_path(settings.CHROMA_PERSIST_DIR)
settings.GENERATED_DIR = _resolve_path(settings.GENERATED_DIR)
