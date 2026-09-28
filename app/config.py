from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./dev.db"
    secret_key: str = DEV_SECRET
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    dev_login: bool = False
    dev_telegram_id: int = 1

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def dev_login_enabled(self) -> bool:
        return self.dev_login and not self.is_production

    @property
    def sqlalchemy_url(self) -> str:
        # Railway hands out postgres:// URLs; SQLAlchemy needs the psycopg driver named.
        for prefix in ("postgres://", "postgresql://"):
            if self.database_url.startswith(prefix):
                return "postgresql+psycopg://" + self.database_url[len(prefix):]
        return self.database_url

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> "Settings":
        if self.is_production and self.secret_key == DEV_SECRET:
            raise ValueError("SECRET_KEY must be set in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
