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
    model_config = SettingsConfigDict(env_prefix="PISHIELD_DB_")

    host: str = "localhost"
    port: int = 5432
    name: str = "pishield"
    user: str = "pishield"
    password: str = ""
    pool_size: int = 10
    max_overflow: int = 20

    @property
    def url(self) -> str:
        """Generiert die Datenbank-URL."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


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


@lru_cache
def get_settings() -> Settings:
    """Singleton für Settings."""
    config_path = Path("config/config.yaml")
    if config_path.exists():
        return Settings.from_yaml(config_path)
    return Settings()
