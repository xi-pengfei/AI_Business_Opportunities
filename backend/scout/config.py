from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://scout:scout@127.0.0.1:55436/scout"
    redis_url: str = "redis://127.0.0.1:56386/0"
    admin_token: str = ""
    display_token: str = ""
    tavily_api_key: str = ""
    allow_demo: bool = False
    lease_seconds: int = Field(default=180, ge=150)
    max_attempts: int = Field(default=3, ge=1, le=10)


@lru_cache
def settings():
    return Settings()
