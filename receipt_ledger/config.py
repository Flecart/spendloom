from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Spendloom"
    app_password: str = Field(min_length=12)
    session_secret: str = Field(min_length=24)
    app_origin: str = "http://localhost:8080"
    data_dir: Path = Path("./data")
    database_url: str | None = None
    timezone: str = "Europe/London"
    base_currency: str = "EUR"
    max_upload_mb: int = 50
    max_pdf_pages: int = 20
    confidence_threshold: float = 0.88

    ai_provider: str = "openai"
    ai_model: str = "gpt-5.6-luna"
    chat_model: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None

    telegram_bot_token: str | None = None
    # Optional defence in depth: only this private Telegram account may claim
    # or use the bot.  It is intentionally configuration, not browser state.
    telegram_allowed_user_id: str | None = None
    telegram_poll_timeout: int = 30

    cookie_secure: bool = False
    log_level: str = "INFO"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'receipt-ledger.db').resolve()}"

    @property
    def receipts_dir(self) -> Path:
        return self.data_dir / "receipts"

    @property
    def previews_dir(self) -> Path:
        return self.data_dir / "previews"

    @property
    def resolved_chat_model(self) -> str:
        return self.chat_model or self.ai_model


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.receipts_dir.mkdir(parents=True, exist_ok=True)
    settings.previews_dir.mkdir(parents=True, exist_ok=True)
    return settings
