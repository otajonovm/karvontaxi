from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: str
    supergroup_id: int
    admin_ids: str = ""
    currency: str = "UZS"
    database_url: str = "sqlite+aiosqlite:///./data/karvon.db"
    subscription_price: int = 100_000
    subscription_days: int = 30
    trial_days: int = 7
    payment_card: str = ""
    payment_info: str = ""
    timezone: str = "Asia/Tashkent"

    @field_validator("database_url")
    @classmethod
    def resolve_sqlite_path(cls, value: str) -> str:
        prefix = "sqlite+aiosqlite:///"
        if value.startswith(prefix) and not value.startswith(prefix + "/"):
            relative = value.removeprefix(prefix)
            if relative.startswith("./"):
                absolute = (ROOT_DIR / relative[2:]).resolve()
                absolute.parent.mkdir(parents=True, exist_ok=True)
                return f"{prefix}{absolute.as_posix()}"
        return value

    @property
    def admin_id_list(self) -> list[int]:
        if not self.admin_ids.strip():
            return []
        ids: list[int] = []
        for raw in self.admin_ids.split(","):
            raw = raw.strip()
            if raw:
                ids.append(int(raw))
        return ids

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_id_list


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
