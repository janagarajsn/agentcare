from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings parses .env into our Settings object, but libraries that
# read os.environ directly (e.g. google-genai, used internally by ADK for
# GOOGLE_API_KEY) never see those values unless .env is also loaded into the
# real process environment. Load it explicitly, once, at import time.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite:///./agentcare.db"

    # Auth / JWT
    jwt_secret_key: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 10080

    # LLM / Agent
    google_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    use_litellm: bool = False
    llm_model: str = "gemini/gemini-3.5-flash"

    # File storage
    document_storage_dir: str = "./storage/documents"
    max_upload_size_mb: int = 10

    # App
    environment: str = "development"
    cors_allow_origins: str = "http://localhost:8501,http://localhost:8000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def document_storage_path(self) -> Path:
        path = Path(self.document_storage_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
