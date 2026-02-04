"""Tests für die Redis Job Queue."""

import pytest
from src.core.queue import ScanJob, JobResult, QueueConfig


class TestScanJob:
    """Tests für das ScanJob Model."""

    def test_create_job_with_defaults(self):
        """Job mit automatischer ID und Timestamp."""
        job = ScanJob(url="https://example.com")

        assert job.url == "https://example.com"
        assert job.task_name == "summarize"
        assert job.priority == 5
        assert len(job.job_id) == 36  # UUID format
        assert job.created_at != ""

    def test_create_job_with_custom_values(self):
        """Job mit benutzerdefinierten Werten."""
        job = ScanJob(
            url="https://test.com",
            task_name="extract",
            priority=10,
        )

        assert job.url == "https://test.com"
        assert job.task_name == "extract"
        assert job.priority == 10

    def test_job_serialization(self):
        """Job kann zu JSON serialisiert werden."""
        job = ScanJob(url="https://example.com")
        json_str = job.model_dump_json()

        # Deserialize
        loaded = ScanJob.model_validate_json(json_str)
        assert loaded.url == job.url
        assert loaded.job_id == job.job_id


class TestJobResult:
    """Tests für das JobResult Model."""

    def test_create_completed_result(self):
        """Erfolgreiche Job-Ergebnis."""
        result = JobResult(
            job_id="test-123",
            url="https://example.com",
            status="completed",
            severity_score=2.5,
            flags_count=1,
            classification="suspicious",
            flags=[{"type": "sentiment_shift", "severity": "low"}],
        )

        assert result.status == "completed"
        assert result.severity_score == 2.5
        assert result.flags_count == 1
        assert result.classification == "suspicious"
        assert len(result.flags) == 1

    def test_create_failed_result(self):
        """Fehlgeschlagenes Job-Ergebnis."""
        result = JobResult(
            job_id="test-456",
            url="https://bad-site.com",
            status="failed",
            error_message="Connection timeout",
        )

        assert result.status == "failed"
        assert result.error_message == "Connection timeout"
        assert result.severity_score == 0.0

    def test_result_with_llm_metadata(self):
        """Ergebnis mit LLM-Metadaten."""
        result = JobResult(
            job_id="test-789",
            url="https://example.com",
            status="completed",
            llm_provider="anthropic",
            llm_model="claude-sonnet-4-5-20250929",
            tokens_input=500,
            tokens_output=100,
            cost_estimated=0.0025,
        )

        assert result.llm_provider == "anthropic"
        assert result.llm_model == "claude-sonnet-4-5-20250929"
        assert result.tokens_input == 500
        assert result.cost_estimated == 0.0025

    def test_result_serialization(self):
        """Result kann zu JSON serialisiert werden."""
        result = JobResult(
            job_id="test-123",
            url="https://example.com",
            status="completed",
            severity_score=5.0,
            flags=[{"type": "tool_call", "severity": "critical"}],
        )
        json_str = result.model_dump_json()

        # Deserialize
        loaded = JobResult.model_validate_json(json_str)
        assert loaded.job_id == result.job_id
        assert loaded.severity_score == result.severity_score
        assert loaded.flags == result.flags


class TestQueueConfig:
    """Tests für QueueConfig."""

    def test_default_config(self):
        """Standard-Konfiguration."""
        config = QueueConfig()

        assert config.host == "localhost"
        assert config.port == 6379
        assert config.db == 0
        assert config.password is None

    def test_redis_url_without_password(self):
        """Redis URL ohne Passwort."""
        config = QueueConfig(host="redis-server", port=6380, db=1)

        assert config.redis_url == "redis://redis-server:6380/1"

    def test_redis_url_with_password(self):
        """Redis URL mit Passwort."""
        config = QueueConfig(password="secret123")

        assert config.redis_url == "redis://:secret123@localhost:6379/0"

    def test_queue_names(self):
        """Queue-Namen korrekt."""
        config = QueueConfig()

        assert "injection_radar:jobs" in config.jobs_queue
        assert "injection_radar:result:" in config.results_prefix
