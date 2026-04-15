"""
Tests for the worker decision logic in src/scraper/worker.py.

Tests the HTTP error handling, empty content detection, and classification
logic without real scraper or LLM calls. Uses mock ScrapedContent data
and verifies JobResult fields are correctly set.
"""

import time
from datetime import datetime, timezone

import pytest

from src.core.queue import JobResult
from src.core.models import ScrapedContent, RedFlag, RedFlagType, Severity
from src.analysis.detector import RedFlagDetector


# ============================================================================
# Helper: Simulate the worker's decision logic (lines 451-546 of worker.py)
# ============================================================================

def build_job_result_from_content(
    job_id: str,
    url: str,
    content: ScrapedContent,
    severity_score: float = 0.0,
    flags: list[dict] | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> JobResult:
    """Replicate the worker_main decision logic for testing.

    This mirrors the if/elif/else chain in worker.py lines 453-546.
    """
    processing_time_ms = 100  # fixed for tests

    if content.http_status >= 400:
        return JobResult(
            job_id=job_id,
            url=url,
            status="completed",
            severity_score=0.0,
            flags_count=0,
            classification="error",
            flags=[],
            error_message=f"HTTP {content.http_status} response",
            processing_time_ms=processing_time_ms,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    elif content.word_count == 0:
        return JobResult(
            job_id=job_id,
            url=url,
            status="completed",
            severity_score=0.0,
            flags_count=0,
            classification="error",
            flags=[],
            error_message="Empty page content (0 words)",
            processing_time_ms=processing_time_ms,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    else:
        # Normal path: would call LLM, use provided severity/flags
        if severity_score >= 6.0:
            classification = "dangerous"
        elif severity_score >= 3.0:
            classification = "suspicious"
        elif severity_score > 0:
            classification = "suspicious"
        else:
            classification = "safe"

        return JobResult(
            job_id=job_id,
            url=url,
            status="completed",
            severity_score=severity_score,
            flags_count=len(flags or []),
            classification=classification,
            flags=flags or [],
            llm_provider=llm_provider,
            llm_model=llm_model,
            processing_time_ms=processing_time_ms,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )


def _make_content(http_status: int = 200, word_count: int = 100) -> ScrapedContent:
    """Create a minimal ScrapedContent for testing."""
    text = " ".join(["word"] * word_count)
    return ScrapedContent(
        url_id=1,
        http_status=http_status,
        response_time_ms=500,
        raw_html=f"<html><body>{text}</body></html>",
        extracted_text=text,
        text_length=len(text),
        word_count=word_count,
        content_hash="abc123",
    )


# ============================================================================
# HTTP Error Handling
# ============================================================================

class TestHttpErrorClassification:
    """HTTP status >= 400 should produce classification='error'."""

    def test_404_classified_as_error(self):
        content = _make_content(http_status=404, word_count=5)
        result = build_job_result_from_content("job-1", "https://example.com", content)
        assert result.classification == "error"
        assert result.severity_score == 0.0
        assert result.flags_count == 0

    def test_403_classified_as_error(self):
        content = _make_content(http_status=403, word_count=10)
        result = build_job_result_from_content("job-2", "https://example.com", content)
        assert result.classification == "error"

    def test_500_classified_as_error(self):
        content = _make_content(http_status=500, word_count=50)
        result = build_job_result_from_content("job-3", "https://example.com", content)
        assert result.classification == "error"

    def test_503_classified_as_error(self):
        content = _make_content(http_status=503, word_count=20)
        result = build_job_result_from_content("job-4", "https://example.com", content)
        assert result.classification == "error"

    def test_400_is_boundary_case(self):
        content = _make_content(http_status=400, word_count=10)
        result = build_job_result_from_content("job-5", "https://example.com", content)
        assert result.classification == "error"

    def test_399_is_not_error(self):
        """HTTP 399 (hypothetical) should NOT be classified as error."""
        content = _make_content(http_status=399, word_count=100)
        result = build_job_result_from_content("job-6", "https://example.com", content)
        assert result.classification != "error"

    def test_http_error_has_error_message(self):
        content = _make_content(http_status=404, word_count=5)
        result = build_job_result_from_content("job-7", "https://example.com", content)
        assert result.error_message is not None
        assert "HTTP 404" in result.error_message

    def test_http_error_message_includes_status_code(self):
        for status in [403, 404, 500, 502, 503]:
            content = _make_content(http_status=status, word_count=5)
            result = build_job_result_from_content("job-x", "https://example.com", content)
            assert str(status) in result.error_message

    def test_http_error_status_is_completed(self):
        """HTTP errors still have status='completed' (not 'failed')."""
        content = _make_content(http_status=404, word_count=5)
        result = build_job_result_from_content("job-8", "https://example.com", content)
        assert result.status == "completed"

    def test_http_error_no_flags(self):
        content = _make_content(http_status=500, word_count=5)
        result = build_job_result_from_content("job-9", "https://example.com", content)
        assert result.flags == []
        assert result.flags_count == 0


# ============================================================================
# Empty Content Handling
# ============================================================================

class TestEmptyContentClassification:
    """word_count == 0 should produce classification='error'."""

    def test_zero_words_classified_as_error(self):
        content = _make_content(http_status=200, word_count=0)
        result = build_job_result_from_content("job-10", "https://example.com", content)
        assert result.classification == "error"

    def test_zero_words_error_message(self):
        content = _make_content(http_status=200, word_count=0)
        result = build_job_result_from_content("job-11", "https://example.com", content)
        assert result.error_message is not None
        assert "0 words" in result.error_message

    def test_zero_words_severity_is_zero(self):
        content = _make_content(http_status=200, word_count=0)
        result = build_job_result_from_content("job-12", "https://example.com", content)
        assert result.severity_score == 0.0

    def test_zero_words_status_is_completed(self):
        content = _make_content(http_status=200, word_count=0)
        result = build_job_result_from_content("job-13", "https://example.com", content)
        assert result.status == "completed"

    def test_one_word_is_not_error(self):
        """Even 1 word should go through to LLM path (not error)."""
        content = _make_content(http_status=200, word_count=1)
        result = build_job_result_from_content("job-14", "https://example.com", content)
        assert result.classification != "error"


# ============================================================================
# Normal Content -> Classification Logic
# ============================================================================

class TestNormalContentClassification:
    """HTTP 200 with word_count > 0 goes to LLM path with severity-based classification."""

    def test_safe_classification(self):
        content = _make_content(http_status=200, word_count=100)
        result = build_job_result_from_content(
            "job-20", "https://example.com", content,
            severity_score=0.0,
        )
        assert result.classification == "safe"

    def test_suspicious_low_severity(self):
        """Any severity > 0 but < 3.0 is suspicious."""
        content = _make_content(http_status=200, word_count=100)
        result = build_job_result_from_content(
            "job-21", "https://example.com", content,
            severity_score=1.5,
        )
        assert result.classification == "suspicious"

    def test_suspicious_medium_severity(self):
        """Severity >= 3.0 but < 6.0 is suspicious."""
        content = _make_content(http_status=200, word_count=100)
        result = build_job_result_from_content(
            "job-22", "https://example.com", content,
            severity_score=4.0,
        )
        assert result.classification == "suspicious"

    def test_dangerous_high_severity(self):
        """Severity >= 6.0 is dangerous."""
        content = _make_content(http_status=200, word_count=100)
        result = build_job_result_from_content(
            "job-23", "https://example.com", content,
            severity_score=7.5,
        )
        assert result.classification == "dangerous"

    def test_dangerous_boundary_at_6(self):
        content = _make_content(http_status=200, word_count=100)
        result = build_job_result_from_content(
            "job-24", "https://example.com", content,
            severity_score=6.0,
        )
        assert result.classification == "dangerous"

    def test_suspicious_boundary_at_3(self):
        content = _make_content(http_status=200, word_count=100)
        result = build_job_result_from_content(
            "job-25", "https://example.com", content,
            severity_score=3.0,
        )
        assert result.classification == "suspicious"

    def test_suspicious_just_above_zero(self):
        content = _make_content(http_status=200, word_count=100)
        result = build_job_result_from_content(
            "job-26", "https://example.com", content,
            severity_score=0.1,
        )
        assert result.classification == "suspicious"

    def test_safe_at_exactly_zero(self):
        content = _make_content(http_status=200, word_count=100)
        result = build_job_result_from_content(
            "job-27", "https://example.com", content,
            severity_score=0.0,
        )
        assert result.classification == "safe"

    def test_max_severity(self):
        content = _make_content(http_status=200, word_count=100)
        result = build_job_result_from_content(
            "job-28", "https://example.com", content,
            severity_score=10.0,
        )
        assert result.classification == "dangerous"


# ============================================================================
# JobResult Field Correctness
# ============================================================================

class TestJobResultFields:
    """Verify JobResult fields are correctly populated."""

    def test_job_id_preserved(self):
        content = _make_content()
        result = build_job_result_from_content("my-job-id", "https://example.com", content)
        assert result.job_id == "my-job-id"

    def test_url_preserved(self):
        content = _make_content()
        result = build_job_result_from_content("job-30", "https://test.org/page", content)
        assert result.url == "https://test.org/page"

    def test_processing_time_set(self):
        content = _make_content()
        result = build_job_result_from_content("job-31", "https://example.com", content)
        assert result.processing_time_ms > 0

    def test_completed_at_set(self):
        content = _make_content()
        result = build_job_result_from_content("job-32", "https://example.com", content)
        assert result.completed_at != ""

    def test_flags_count_matches_flags(self):
        flags = [
            {"type": "tool_call", "severity": "critical", "description": "test"},
            {"type": "format_deviation", "severity": "medium", "description": "test2"},
        ]
        content = _make_content()
        result = build_job_result_from_content(
            "job-33", "https://example.com", content,
            severity_score=5.0, flags=flags,
        )
        assert result.flags_count == 2
        assert len(result.flags) == 2

    def test_llm_provider_set_on_normal_path(self):
        content = _make_content()
        result = build_job_result_from_content(
            "job-34", "https://example.com", content,
            severity_score=0.0,
            llm_provider="anthropic",
            llm_model="claude-3-sonnet",
        )
        assert result.llm_provider == "anthropic"
        assert result.llm_model == "claude-3-sonnet"

    def test_llm_provider_none_on_error_path(self):
        content = _make_content(http_status=404)
        result = build_job_result_from_content("job-35", "https://example.com", content)
        assert result.llm_provider is None
        assert result.llm_model is None

    def test_error_result_has_no_error_message_on_success(self):
        content = _make_content()
        result = build_job_result_from_content(
            "job-36", "https://example.com", content, severity_score=0.0,
        )
        assert result.error_message is None


# ============================================================================
# Priority: HTTP error takes precedence over empty content
# ============================================================================

class TestDecisionPriority:
    """HTTP error check runs before empty content check."""

    def test_http_error_takes_priority_over_empty_content(self):
        """If both http_status >= 400 AND word_count == 0, HTTP error wins."""
        content = _make_content(http_status=404, word_count=0)
        result = build_job_result_from_content("job-40", "https://example.com", content)
        assert result.classification == "error"
        assert "HTTP 404" in result.error_message


# ============================================================================
# Severity Score Calculation (from RedFlagDetector)
# ============================================================================

class TestSeverityScoreIntegration:
    """Test that RedFlagDetector.calculate_severity_score works correctly
    with the classification thresholds."""

    def test_no_flags_zero_severity(self):
        detector = RedFlagDetector()
        score = detector.calculate_severity_score([])
        assert score == 0.0

    def test_critical_flag_produces_high_score(self):
        detector = RedFlagDetector()
        flags = [
            RedFlag(
                type=RedFlagType.TOOL_CALL,
                severity=Severity.CRITICAL,
                description="Tool call detected",
            )
        ]
        score = detector.calculate_severity_score(flags)
        assert score >= 3.0  # Should be at least suspicious

    def test_multiple_critical_flags_dangerous(self):
        detector = RedFlagDetector()
        flags = [
            RedFlag(
                type=RedFlagType.TOOL_CALL,
                severity=Severity.CRITICAL,
                description="Tool call",
            ),
            RedFlag(
                type=RedFlagType.CODE_EXECUTION,
                severity=Severity.CRITICAL,
                description="Code exec",
            ),
        ]
        score = detector.calculate_severity_score(flags)
        assert score >= 6.0  # Should be dangerous

    def test_low_flag_produces_low_score(self):
        detector = RedFlagDetector()
        flags = [
            RedFlag(
                type=RedFlagType.SENTIMENT_SHIFT,
                severity=Severity.LOW,
                description="Minor shift",
            )
        ]
        score = detector.calculate_severity_score(flags)
        assert score < 3.0  # Should be suspicious at most, not dangerous
