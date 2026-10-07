from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[3] / ".env"),
        env_prefix="AEC_",
        extra="ignore",
    )

    app_name: str = "AI-Exam-Coach"
    api_v1_prefix: str = "/api/v1"
    # Default to SQLite for a runnable local MVP. Set DATABASE_URL to a
    # PostgreSQL URL (postgresql+psycopg2://...) in production per the spec.
    database_url: str = "sqlite:///./data/aiexamcoach.db"
    ai_provider: str = "heuristic"  # heuristic | openai_compatible
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    max_workers: int = 4  # parallel material-parsing workers
    max_upload_mb: int = 100  # per-file upload size limit (heuristic parser reads file into memory)
    auth_session_ttl_hours: int = 168
    auth_cookie_secure: bool = False  # Set true when serving over HTTPS.
    auth_cookie_name: str = "aiec_session"
    demo_username: str = ""
    demo_password: str = ""
    demo_user_id: str = "demo-user"
    demo_course_id: str = ""
    cors_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

settings = Settings()
