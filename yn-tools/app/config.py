from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "YN Tools"
    app_env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./yn_tools.db"
    secret_key: str = "change-me-in-production"

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"

    # Stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_all_tools: str = ""  # 全ツールプラン (2,000円/月)

    # Mailer tool
    encryption_key: str = ""  # Fernet key for SMTP password encryption

    # Sales tool
    google_places_api_key: str = ""
    scraping_delay_sec: float = 2.0

    # AI Document Processing (DocAI)
    openai_api_key: str = ""

    # Trial
    trial_days: int = 30

    # Demo mode (DEMO_MODE=true for seminar/public demo at demo.ynfactory.online)
    demo_mode: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @model_validator(mode="after")
    def fix_database_url(self):
        url = self.database_url
        if url.startswith("postgres://"):
            self.database_url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            self.database_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self


settings = Settings()
