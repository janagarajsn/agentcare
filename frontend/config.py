from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    backend_api_url: str = "http://localhost:8000"
    cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
