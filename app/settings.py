"""Process-level settings, read from environment variables (or a local .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    validate_twilio_signature: bool = True

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"

    # Service
    public_base_url: str = "http://localhost:8000"
    clients_file: str = "config/clients.yaml"
    database_path: str = "data/leads.db"
    admin_token: str = ""

    # Behavior
    dedupe_window_minutes: int = 30
    stale_after_minutes: int = 20
    max_caller_turns: int = 6

    # Abuse limits
    max_new_conversations_per_hour: int = 60  # per client; caps cost if someone spams the number or form
    enable_docs: bool = False  # /docs and /openapi.json stay off in production


@lru_cache
def get_settings() -> Settings:
    return Settings()
