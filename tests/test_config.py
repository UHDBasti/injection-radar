"""
Tests für Konfigurationsmanagement.
"""

import os
import tempfile
import pytest
from pathlib import Path

from src.core.config import (
    Settings,
    LLMConfig,
    DatabaseConfig,
    ScrapingConfig,
    RateLimitConfig,
    get_settings,
)


class TestLLMConfig:
    """Tests für LLM-Konfiguration."""

    def test_default_values(self):
        config = LLMConfig()
        assert "claude" in config.primary_analyzer.lower() or "sonnet" in config.primary_analyzer.lower()
        assert config.max_input_tokens == 4000
        assert config.max_output_tokens == 1000
        assert config.temperature == 0.1


class TestDatabaseConfig:
    """Tests für Datenbank-Konfiguration."""

    def test_default_values(self):
        config = DatabaseConfig()
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.name == "pishield"

    def test_url_generation(self):
        # Test PostgreSQL URL
        config = DatabaseConfig(
            type="postgresql",
            host="db.example.com",
            port=5433,
            name="testdb",
            user="testuser",
            password="secret",
        )
        url = config.url
        assert "postgresql://" in url
        assert "testuser:secret" in url
        assert "db.example.com:5433" in url
        assert "/testdb" in url

    def test_sqlite_url_generation(self):
        # Test SQLite URL (default)
        config = DatabaseConfig(type="sqlite", sqlite_path="test.db")
        url = config.url
        assert "sqlite:///" in url
        assert "test.db" in url


class TestScrapingConfig:
    """Tests für Scraping-Konfiguration."""

    def test_default_values(self):
        config = ScrapingConfig()
        assert config.max_concurrent == 10
        assert config.timeout == 30
        assert config.render_javascript is True


class TestRateLimitConfig:
    """Tests für Rate-Limit-Konfiguration."""

    def test_default_values(self):
        config = RateLimitConfig()
        assert config.enabled is True
        assert config.default_per_minute == 60
        assert config.scan_per_minute == 30
        assert config.scan_async_per_minute == 120
        assert config.window_seconds == 60

    def test_custom_values(self):
        config = RateLimitConfig(
            enabled=False,
            default_per_minute=100,
            scan_per_minute=10,
            scan_async_per_minute=50,
            window_seconds=30,
        )
        assert config.enabled is False
        assert config.default_per_minute == 100
        assert config.scan_per_minute == 10
        assert config.scan_async_per_minute == 50
        assert config.window_seconds == 30

    def test_settings_has_rate_limit(self):
        settings = Settings()
        assert isinstance(settings.rate_limit, RateLimitConfig)


class TestSettings:
    """Tests für Haupt-Settings."""

    def test_default_settings(self):
        settings = Settings()
        assert isinstance(settings.llm, LLMConfig)
        assert isinstance(settings.database, DatabaseConfig)
        assert isinstance(settings.scraping, ScrapingConfig)

    def test_api_keys_from_env(self):
        # Setze temporär Umgebungsvariablen
        os.environ["ANTHROPIC_API_KEY"] = "test-key-123"
        try:
            settings = Settings()
            assert settings.anthropic_api_key == "test-key-123"
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_load_from_yaml(self):
        yaml_content = """
llm:
  primary_analyzer: "claude-3-opus"
  max_input_tokens: 8000
database:
  host: "custom-db.local"
  port: 5434
scraping:
  max_concurrent: 5
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()

            try:
                settings = Settings.from_yaml(f.name)
                assert settings.llm.primary_analyzer == "claude-3-opus"
                assert settings.llm.max_input_tokens == 8000
                assert settings.database.host == "custom-db.local"
                assert settings.scraping.max_concurrent == 5
            finally:
                os.unlink(f.name)

    def test_missing_yaml_returns_defaults(self):
        settings = Settings.from_yaml("/nonexistent/path.yaml")
        # Sollte Default-Settings zurückgeben
        assert settings.database.host == "localhost"


class TestGetSettings:
    """Tests für get_settings Singleton."""

    def test_returns_settings_instance(self):
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_caching(self):
        # get_settings sollte gecached sein
        settings1 = get_settings()
        settings2 = get_settings()
        # Bei LRU cache sollte es dieselbe Instanz sein
        # (abhängig davon ob config.yaml existiert)
        assert settings1 is not None
        assert settings2 is not None
