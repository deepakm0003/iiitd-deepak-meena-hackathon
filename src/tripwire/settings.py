"""Runtime settings.

Precedence (highest first): explicit arguments, environment variables, .env file, config/settings.yaml,
field defaults. Secrets (API keys) are read only from the environment or .env, never from YAML.
"""

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRIPWIRE_",
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        yaml_file=CONFIG_DIR / "settings.yaml",
        extra="ignore",
        populate_by_name=True,
    )

    mode: Literal["lite", "full"] = "lite"
    queue: Literal["memory", "redis"] = "memory"
    sources: Literal["replay", "live"] = "replay"
    database_url: str = f"sqlite:///{(ROOT / 'var' / 'tripwire.db').as_posix()}"
    redis_url: str = "redis://localhost:6379/0"
    data_dir: Path = ROOT / "data"
    var_dir: Path = ROOT / "var"
    # Demo mode: treat this time as "now" (the snapshot export time), so "last 24 h / 7 days" views stay meaningful.
    as_of: datetime | None = None
    # Some networks (e.g. the college server) advertise IPv6 but cannot route it; Python then waits for each
    # IPv6 attempt to time out. TRIPWIRE_FORCE_IPV4=true makes HTTP and websocket clients use IPv4 only.
    force_ipv4: bool = False

    finnhub_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("FINNHUB_API_KEY", "TRIPWIRE_FINNHUB_API_KEY")
    )
    sec_user_agent: str | None = Field(
        default=None, validation_alias=AliasChoices("SEC_USER_AGENT", "TRIPWIRE_SEC_USER_AGENT")
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, dotenv_settings, YamlConfigSettingsSource(settings_cls))


@lru_cache
def get_settings() -> Settings:
    return Settings()
