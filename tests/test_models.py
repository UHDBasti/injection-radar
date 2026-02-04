"""
Tests für Pydantic Datenmodelle.
"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from src.core.models import (
    Classification,
    Severity,
    RedFlagType,
    RedFlag,
    Domain,
    URL,
    ScrapedContent,
    ScanResult,
    AnalysisResult,
)


class TestEnums:
    """Tests für Enum-Typen."""

    def test_classification_values(self):
        assert Classification.SAFE.value == "safe"
        assert Classification.SUSPICIOUS.value == "suspicious"
        assert Classification.DANGEROUS.value == "dangerous"
        assert Classification.ERROR.value == "error"
        assert Classification.PENDING.value == "pending"

    def test_severity_values(self):
        assert Severity.CRITICAL.value == "critical"
        assert Severity.HIGH.value == "high"
        assert Severity.MEDIUM.value == "medium"
        assert Severity.LOW.value == "low"

    def test_red_flag_types(self):
        assert RedFlagType.TOOL_CALL.value == "tool_call"
        assert RedFlagType.CODE_EXECUTION.value == "code_execution"
        assert RedFlagType.SYSTEM_PROMPT_LEAK.value == "system_prompt_leak"


class TestRedFlag:
    """Tests für RedFlag Model."""

    def test_create_red_flag(self):
        flag = RedFlag(
            type=RedFlagType.TOOL_CALL,
            severity=Severity.CRITICAL,
            description="Tool call attempt detected",
            evidence="send_email function called",
        )
        assert flag.type == RedFlagType.TOOL_CALL
        assert flag.severity == Severity.CRITICAL
        assert "Tool call" in flag.description

    def test_red_flag_optional_evidence(self):
        flag = RedFlag(
            type=RedFlagType.FORMAT_DEVIATION,
            severity=Severity.MEDIUM,
            description="Format mismatch",
        )
        assert flag.evidence is None


class TestDomain:
    """Tests für Domain Model."""

    def test_create_domain(self):
        domain = Domain(domain="example.com")
        assert domain.domain == "example.com"
        assert domain.total_urls_scanned == 0
        assert domain.risk_score == 0.0

    def test_domain_with_stats(self):
        domain = Domain(
            domain="malicious.com",
            total_urls_scanned=100,
            dangerous_urls_count=50,
            suspicious_urls_count=30,
            risk_score=0.8,
        )
        assert domain.dangerous_urls_count == 50
        assert domain.risk_score == 0.8


class TestURL:
    """Tests für URL Model."""

    def test_create_url(self):
        url = URL(url="https://example.com/page")
        assert str(url.url) == "https://example.com/page"
        assert url.current_status == Classification.PENDING
        assert url.scan_count == 0

    def test_url_invalid_format(self):
        with pytest.raises(ValidationError):
            URL(url="not-a-valid-url")


class TestScrapedContent:
    """Tests für ScrapedContent Model."""

    def test_create_scraped_content(self):
        content = ScrapedContent(
            url_id=1,
            http_status=200,
            response_time_ms=500,
            raw_html="<html><body>Test</body></html>",
            extracted_text="Test",
            text_length=4,
            word_count=1,
            content_hash="abc123",
        )
        assert content.http_status == 200
        assert content.text_length == 4

    def test_scraped_content_defaults(self):
        content = ScrapedContent(
            url_id=1,
            http_status=200,
            response_time_ms=100,
            raw_html="<html></html>",
            extracted_text="",
            text_length=0,
            word_count=0,
            content_hash="xyz",
        )
        assert content.meta_tags == {}
        assert content.scripts_content == []
        assert content.external_links == []


class TestScanResult:
    """Tests für ScanResult Model."""

    def test_create_scan_result(self):
        result = ScanResult(
            url_id=1,
            task_name="summarize",
            llm_provider="anthropic",
            llm_model="claude-3-sonnet",
            output_length=500,
            output_word_count=100,
            output_format_detected="text",
        )
        assert result.task_name == "summarize"
        assert result.tool_calls_attempted is False
        assert result.flags_detected == []

    def test_scan_result_with_flags(self):
        flag = RedFlag(
            type=RedFlagType.TOOL_CALL,
            severity=Severity.CRITICAL,
            description="Tool call detected",
        )
        result = ScanResult(
            url_id=1,
            task_name="summarize",
            llm_provider="anthropic",
            llm_model="claude-3-sonnet",
            output_length=500,
            output_word_count=100,
            output_format_detected="text",
            tool_calls_attempted=True,
            tool_calls_count=1,
            flags_detected=[flag],
        )
        assert len(result.flags_detected) == 1
        assert result.tool_calls_attempted is True


class TestAnalysisResult:
    """Tests für AnalysisResult Model."""

    def test_create_analysis_result(self):
        result = AnalysisResult(
            url_id=1,
            scan_result_id=1,
            classification=Classification.DANGEROUS,
            confidence=0.95,
            severity_score=8.5,
            reasoning="Multiple tool calls detected indicating prompt injection",
        )
        assert result.classification == Classification.DANGEROUS
        assert result.confidence == 0.95
        assert result.severity_score == 8.5
