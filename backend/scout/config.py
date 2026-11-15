from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://scout:scout@127.0.0.1:55436/scout"
    redis_url: str = "redis://127.0.0.1:56386/0"
    display_token: str = ""
    admin_username: str = "admin"
    admin_password: str = "admin123456"
    tavily_api_key: str = ""
    searxng_engines: str = "duckduckgo,brave"
    searxng_url: str = "http://searxng:8080"
    xiaohongshu_url: str = "http://xiaohongshu:18060"
    xiaohongshu_token: str = ""
    dingtalk_enabled: bool = False
    dingtalk_app_key: str = ""
    dingtalk_app_secret: str = ""
    dingtalk_robot_code: str = ""
    dingtalk_conversation_id: str = ""
    dingtalk_group_name: str = "钉钉群"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"
    allow_demo: bool = False
    lease_seconds: int = Field(default=180, ge=150)
    max_attempts: int = Field(default=3, ge=1, le=10)


@lru_cache
def settings():
    return Settings()
