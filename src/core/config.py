"""
Konfigurationsmanagement für Prompt Injection Shield.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseSettings):
    """LLM-spezifische Konfiguration."""
    model_config = SettingsConfigDict(extra="ignore")

    primary_analyzer: str = "claude-sonnet-4-5-20250929"
    max_input_tokens: int = 4000
    max_output_tokens: int = 1000
    temperature: float = 0.1


class DatabaseConfig(BaseSettings):
    """Datenbank-Konfiguration."""
    model_config = SettingsConfigDict(env_prefix="PISHIELD_DB_", extra="ignore")

    # SQLite als Default für einfaches Testen
    type: str = "sqlite"  # "sqlite" oder "postgresql"

    # SQLite Pfad
    sqlite_path: str = "data/injectionradar.db"

    # PostgreSQL Settings
    host: str = "localhost"
    port: int = 5432
    name: str = "pishield"
    user: str = "pishield"
    password: str = ""
    pool_size: int = 10
    max_overflow: int = 20

    def __init__(self, **data):
        """Liest Umgebungsvariablen manuell (pydantic-settings Bug bei nested models)."""
        # Umgebungsvariablen mit Prefix PISHIELD_DB_ laden
        env_mapping = {
            "PISHIELD_DB_TYPE": "type",
            "PISHIELD_DB_HOST": "host",
            "PISHIELD_DB_PORT": "port",
            "PISHIELD_DB_NAME": "name",
            "PISHIELD_DB_USER": "user",
            "PISHIELD_DB_PASSWORD": "password",
        }
        for env_key, field_name in env_mapping.items():
            if env_key in os.environ and field_name not in data:
                value = os.environ[env_key]
                if field_name == "port":
                    value = int(value)
                data[field_name] = value
        super().__init__(**data)

    @property
    def url(self) -> str:
        """Generiert die Datenbank-URL."""
        if self.type == "sqlite":
            return f"sqlite:///{self.sqlite_path}"
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def async_url(self) -> str:
        """Generiert die async Datenbank-URL."""
        if self.type == "sqlite":
            return f"sqlite+aiosqlite:///{self.sqlite_path}"
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class ScrapingConfig(BaseSettings):
    """Scraping-Konfiguration."""
    max_concurrent: int = 10
    timeout: int = 30
    delay_between_requests: float = 1.0
    user_agent: str = "PromptInjectionShield/1.0 (Security Research)"
    render_javascript: bool = True
    max_page_size: int = 10485760  # 10 MB


class CrawlingConfig(BaseSettings):
    """Crawling-Management Konfiguration."""
    model_config = SettingsConfigDict(extra="ignore")

    tranco_file: str = "data/top-1m.csv"
    tranco_limit: int = 100
    rescan_interval_safe: int = 30
    rescan_interval_suspicious: int = 7
    rescan_interval_dangerous: int = 3
    checkpoint_interval: int = 50


class APIConfig(BaseSettings):
    """API-Konfiguration."""
    model_config = SettingsConfigDict(extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    rate_limit_per_minute: int = 60


class RedisConfig(BaseSettings):
    """Redis-Konfiguration für Job Queue."""
    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    host: str = "localhost"
    port: int = 6379

    def __init__(self, **data):
        """Liest Umgebungsvariablen manuell."""
        env_mapping = {
            "REDIS_HOST": "host",
            "REDIS_PORT": "port",
        }
        for env_key, field_name in env_mapping.items():
            if env_key in os.environ and field_name not in data:
                value = os.environ[env_key]
                if field_name == "port":
                    value = int(value)
                data[field_name] = value
        super().__init__(**data)
    db: int = 0
    password: Optional[str] = None

    # Queue Settings
    job_timeout_seconds: int = 120
    result_ttl_seconds: int = 3600

    @property
    def url(self) -> str:
        """Generiert die Redis-URL."""
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class Settings(BaseSettings):
    """Hauptkonfiguration."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignoriere unbekannte Felder aus YAML
    )

    # API Keys aus Umgebungsvariablen
    anthropic_api_key: Optional[str] = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, validation_alias="OPENAI_API_KEY")
    google_api_key: Optional[str] = Field(default=None, validation_alias="GOOGLE_API_KEY")
    xai_api_key: Optional[str] = Field(default=None, validation_alias="XAI_API_KEY")

    # Sub-Konfigurationen
    llm: LLMConfig = Field(default_factory=LLMConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    scraping: ScrapingConfig = Field(default_factory=ScrapingConfig)
    crawling: CrawlingConfig = Field(default_factory=CrawlingConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/pishield.log"

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Settings":
        """Lädt Konfiguration aus YAML-Datei."""
        path = Path(path)
        if not path.exists():
            return cls()

        with open(path) as f:
            config_dict = yaml.safe_load(f)

        return cls(**config_dict)


def _load_env_file():
    """Lädt .env Datei in os.environ.

    Nötig weil pydantic-settings .env nur intern liest, aber nested models
    (DatabaseConfig, RedisConfig) os.environ direkt prüfen.
    """
    env_path = Path(".env")
    if not env_path.exists():
        return

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Nicht überschreiben wenn bereits gesetzt (echte Env-Vars haben Vorrang)
            if key and key not in os.environ:
                os.environ[key] = value


def _detect_docker_postgresql() -> bool:
    """Prüft ob Docker PostgreSQL auf localhost:5432 erreichbar ist."""
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex(("localhost", 5432))
        sock.close()
        return result == 0
    except Exception:
        return False


@lru_cache
def get_settings() -> Settings:
    """Singleton für Settings.

    1. Lädt .env in os.environ (damit nested models die Vars finden)
    2. Auto-detect Docker PostgreSQL und setzt PISHIELD_DB_TYPE
    3. Lädt config.yaml oder erstellt Default-Settings
    4. DatabaseConfig.__init__ liest dann automatisch die Env-Vars
    """
    # Schritt 1: .env in os.environ laden
    _load_env_file()

    # Schritt 2: PostgreSQL auto-detect wenn kein expliziter DB-Typ gesetzt
    if "PISHIELD_DB_TYPE" not in os.environ and _detect_docker_postgresql():
        os.environ["PISHIELD_DB_TYPE"] = "postgresql"

    # Schritt 3: Settings laden (DatabaseConfig.__init__ liest jetzt os.environ)
    config_path = Path("config/config.yaml")
    if config_path.exists():
        return Settings.from_yaml(config_path)

    return Settings()
