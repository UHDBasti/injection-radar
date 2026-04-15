"""
Tests for the Debug Dashboard components.

Tests JobTracker state machine, StepEntry, DebugDashboard parsing,
and load_urls_from_csv.
"""

import json
import tempfile
import time
import os

import pytest
from rich.console import Console
from rich.panel import Panel

from src.cli.debug_dashboard import (
    JobState,
    StepEntry,
    JobTracker,
    DebugDashboard,
)
from src.cli.interactive import load_urls_from_csv


# ============================================================================
# JobState Enum
# ============================================================================

class TestJobState:
    """Tests for JobState enum."""

    def test_all_states_exist(self):
        assert JobState.QUEUED.value == "queued"
        assert JobState.SCRAPING.value == "scraping"
        assert JobState.SAVED.value == "saved"
        assert JobState.ANALYZING.value == "analyzing"
        assert JobState.DONE.value == "done"
        assert JobState.FAILED.value == "failed"

    def test_state_count(self):
        assert len(JobState) == 6


# ============================================================================
# StepEntry
# ============================================================================

class TestStepEntry:
    """Tests for StepEntry dataclass."""

    def test_create_step(self):
        step = StepEntry(label="Test step", state="ok")
        assert step.label == "Test step"
        assert step.state == "ok"
        assert step.detail == ""
        assert step.elapsed == 0.0

    def test_step_with_detail(self):
        step = StepEntry(label="Scrape", state="running", detail="200 OK", elapsed=1.5)
        assert step.detail == "200 OK"
        assert step.elapsed == 1.5

    def test_step_states(self):
        for state in ("ok", "running", "failed"):
            step = StepEntry(label="Test", state=state)
            assert step.state == state


# ============================================================================
# JobTracker State Machine
# ============================================================================

class TestJobTracker:
    """Tests for JobTracker state machine."""

    def test_initial_state_is_queued(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        assert tracker.state == JobState.QUEUED

    def test_initial_step_is_created(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        assert len(tracker.steps) == 1
        assert tracker.steps[0].label == "Job in Queue"
        assert tracker.steps[0].state == "ok"

    def test_start_time_is_set(self):
        before = time.time()
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        after = time.time()
        assert before <= tracker.start_time <= after

    def test_add_step(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        tracker.add_step("Website scraped", state="ok", detail="200 OK")
        assert len(tracker.steps) == 2
        assert tracker.steps[1].label == "Website scraped"
        assert tracker.steps[1].detail == "200 OK"

    def test_add_step_has_elapsed_time(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        # Set start_time a bit in the past
        tracker.start_time = time.time() - 2.0
        tracker.add_step("Later step")
        assert tracker.steps[-1].elapsed >= 1.5

    def test_update_running_step(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        tracker.update_running_step("Scraping...", detail="loading page")
        # Previous running steps should be set to ok
        running_steps = [s for s in tracker.steps if s.state == "running"]
        assert len(running_steps) == 1
        assert running_steps[0].label == "Scraping..."

    def test_update_running_step_replaces_previous(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        tracker.update_running_step("Step 1")
        tracker.update_running_step("Step 2")
        running_steps = [s for s in tracker.steps if s.state == "running"]
        assert len(running_steps) == 1
        assert running_steps[0].label == "Step 2"
        # Step 1 should now be "ok"
        step1 = [s for s in tracker.steps if s.label == "Step 1"]
        assert step1[0].state == "ok"

    def test_full_state_machine_flow(self):
        """Test the full QUEUED -> SCRAPING -> SAVED -> ANALYZING -> DONE flow."""
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        assert tracker.state == JobState.QUEUED

        # Scraping
        tracker.state = JobState.SCRAPING
        tracker.update_running_step("Scrape laeuft...")
        assert tracker.state == JobState.SCRAPING

        # Saved
        tracker.state = JobState.SAVED
        tracker.add_step("In DB gespeichert")
        assert tracker.state == JobState.SAVED

        # Analyzing
        tracker.state = JobState.ANALYZING
        tracker.add_step("LLM-Analyse abgeschlossen (2 Flags)")
        assert tracker.state == JobState.ANALYZING

        # Done
        tracker.finish(classification="suspicious", severity=4.5)
        assert tracker.state == JobState.DONE
        # All running steps should be ok now
        running = [s for s in tracker.steps if s.state == "running"]
        assert len(running) == 0

    def test_finish_sets_done_state(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        tracker.update_running_step("Working...")
        tracker.finish(classification="safe", severity=0.0)
        assert tracker.state == JobState.DONE
        # Last step should contain classification info
        assert "safe" in tracker.steps[-1].label

    def test_finish_clears_running_steps(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        tracker.update_running_step("Processing...")
        tracker.finish(classification="safe", severity=0.0)
        running = [s for s in tracker.steps if s.state == "running"]
        assert len(running) == 0

    def test_fail_path(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        tracker.update_running_step("Scraping...")
        tracker.fail("Connection timeout")
        assert tracker.state == JobState.FAILED
        assert tracker.error == "Connection timeout"

    def test_fail_marks_running_as_failed(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        tracker.update_running_step("Scraping...")
        tracker.fail("Error")
        # The previously running step should be "failed"
        scraping_step = [s for s in tracker.steps if s.label == "Scraping..."]
        assert scraping_step[0].state == "failed"

    def test_fail_adds_error_step(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        tracker.fail("Something went wrong")
        last_step = tracker.steps[-1]
        assert last_step.state == "failed"
        assert "Fehler:" in last_step.label

    def test_fail_truncates_long_error(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        long_error = "A" * 200
        tracker.fail(long_error)
        last_step = tracker.steps[-1]
        # Error should be truncated to 60 chars in the label
        assert len(last_step.label) < 80

    def test_result_and_error_initially_none(self):
        tracker = JobTracker(job_id="test-123", url="https://example.com")
        assert tracker.result is None
        assert tracker.error is None


# ============================================================================
# DebugDashboard._parse_log_line
# ============================================================================

class TestDashboardParseLogLine:
    """Tests for DebugDashboard._parse_log_line with structlog JSON events."""

    @pytest.fixture
    def dashboard(self):
        config = {"orchestrator_url": "http://localhost:8000"}
        console = Console(file=open(os.devnull, "w"))
        db = DebugDashboard(config=config, console=console)
        # Add a test tracker
        tracker = JobTracker(job_id="abc-123", url="https://example.com")
        db.jobs["abc-123"] = tracker
        return db

    def test_parse_job_processing(self, dashboard):
        line = json.dumps({
            "event": "job_processing",
            "job_id": "abc-123",
            "timestamp": "2026-01-01T00:00:00",
        })
        dashboard._parse_log_line(line)
        tracker = dashboard.jobs["abc-123"]
        assert tracker.state == JobState.SCRAPING

    def test_parse_website_scraped(self, dashboard):
        dashboard.jobs["abc-123"].state = JobState.SCRAPING
        line = json.dumps({
            "event": "website_scraped",
            "job_id": "abc-123",
            "word_count": 1500,
        })
        dashboard._parse_log_line(line)
        steps = dashboard.jobs["abc-123"].steps
        scraped_steps = [s for s in steps if "gescraped" in s.label.lower()]
        assert len(scraped_steps) == 1
        assert "1,500" in scraped_steps[0].label

    def test_parse_scraped_content_saved(self, dashboard):
        line = json.dumps({
            "event": "scraped_content_saved",
            "job_id": "abc-123",
        })
        dashboard._parse_log_line(line)
        assert dashboard.jobs["abc-123"].state == JobState.SAVED

    def test_parse_llm_test_completed(self, dashboard):
        line = json.dumps({
            "event": "llm_test_completed",
            "job_id": "abc-123",
            "flags_count": 3,
        })
        dashboard._parse_log_line(line)
        assert dashboard.jobs["abc-123"].state == JobState.ANALYZING

    def test_parse_job_completed(self, dashboard):
        line = json.dumps({
            "event": "job_completed",
            "job_id": "abc-123",
            "severity": 2.5,
            "classification": "suspicious",
        })
        dashboard._parse_log_line(line)
        assert dashboard.jobs["abc-123"].state == JobState.DONE

    def test_parse_job_failed(self, dashboard):
        line = json.dumps({
            "event": "job_failed",
            "job_id": "abc-123",
            "error_message": "Timeout",
        })
        dashboard._parse_log_line(line)
        assert dashboard.jobs["abc-123"].state == JobState.FAILED

    def test_parse_unknown_event_adds_log(self, dashboard):
        line = json.dumps({
            "event": "some_other_event",
            "timestamp": "2026-01-01T12:00:00",
        })
        initial_log_count = len(dashboard.log_lines)
        dashboard._parse_log_line(line)
        assert len(dashboard.log_lines) == initial_log_count + 1

    def test_parse_non_json_line(self, dashboard):
        initial_log_count = len(dashboard.log_lines)
        dashboard._parse_log_line("Just a plain text line")
        assert len(dashboard.log_lines) == initial_log_count + 1

    def test_parse_attaching_line_ignored(self, dashboard):
        initial_log_count = len(dashboard.log_lines)
        dashboard._parse_log_line("Attaching to scraper-1")
        assert len(dashboard.log_lines) == initial_log_count

    def test_parse_unknown_job_id_no_crash(self, dashboard):
        """Parsing a log line with unknown job_id should not raise."""
        line = json.dumps({
            "event": "job_processing",
            "job_id": "unknown-id",
        })
        dashboard._parse_log_line(line)


# ============================================================================
# DebugDashboard._update_tracker_from_status
# ============================================================================

class TestDashboardUpdateTracker:
    """Tests for DebugDashboard._update_tracker_from_status."""

    @pytest.fixture
    def dashboard(self):
        config = {"orchestrator_url": "http://localhost:8000"}
        console = Console(file=open(os.devnull, "w"))
        return DebugDashboard(config=config, console=console)

    def test_pending_status_keeps_queued(self, dashboard):
        tracker = JobTracker(job_id="t1", url="https://example.com")
        dashboard._update_tracker_from_status(tracker, {"status": "pending"})
        assert tracker.state == JobState.QUEUED

    def test_completed_status_finishes_job(self, dashboard):
        tracker = JobTracker(job_id="t1", url="https://example.com")
        data = {
            "status": "completed",
            "result": {
                "classification": "safe",
                "severity_score": 0.5,
            },
        }
        dashboard._update_tracker_from_status(tracker, data)
        assert tracker.state == JobState.DONE
        assert tracker.result is not None

    def test_failed_status_with_result(self, dashboard):
        tracker = JobTracker(job_id="t1", url="https://example.com")
        data = {
            "status": "failed",
            "result": {
                "classification": "error",
                "severity_score": 0,
                "error_message": "Connection refused",
            },
        }
        dashboard._update_tracker_from_status(tracker, data)
        assert tracker.state == JobState.FAILED

    def test_failed_status_without_result(self, dashboard):
        tracker = JobTracker(job_id="t1", url="https://example.com")
        data = {"status": "failed", "result": None}
        dashboard._update_tracker_from_status(tracker, data)
        assert tracker.state == JobState.FAILED

    def test_completed_with_null_severity(self, dashboard):
        tracker = JobTracker(job_id="t1", url="https://example.com")
        data = {
            "status": "completed",
            "result": {
                "classification": "safe",
                "severity_score": None,
            },
        }
        dashboard._update_tracker_from_status(tracker, data)
        assert tracker.state == JobState.DONE


# ============================================================================
# DebugDashboard._render
# ============================================================================

class TestDashboardRender:
    """Tests for DebugDashboard._render."""

    def test_render_returns_panel(self):
        config = {"orchestrator_url": "http://localhost:8000"}
        console = Console(file=open(os.devnull, "w"))
        db = DebugDashboard(config=config, console=console)
        result = db._render()
        assert isinstance(result, Panel)

    def test_render_with_jobs(self):
        config = {"orchestrator_url": "http://localhost:8000"}
        console = Console(file=open(os.devnull, "w"))
        db = DebugDashboard(config=config, console=console)
        db.jobs["job-1"] = JobTracker(job_id="job-1", url="https://example.com")
        db.jobs["job-1"].finish("safe", 0.0)
        result = db._render()
        assert isinstance(result, Panel)

    def test_render_with_failed_job(self):
        config = {"orchestrator_url": "http://localhost:8000"}
        console = Console(file=open(os.devnull, "w"))
        db = DebugDashboard(config=config, console=console)
        db.jobs["job-1"] = JobTracker(job_id="job-1", url="https://example.com")
        db.jobs["job-1"].fail("Connection refused")
        result = db._render()
        assert isinstance(result, Panel)

    def test_render_with_log_lines(self):
        config = {"orchestrator_url": "http://localhost:8000"}
        console = Console(file=open(os.devnull, "w"))
        db = DebugDashboard(config=config, console=console)
        db._add_log("Test log line 1")
        db._add_log("Test log line 2")
        result = db._render()
        assert isinstance(result, Panel)


# ============================================================================
# DebugDashboard._add_log
# ============================================================================

class TestDashboardAddLog:
    """Tests for log line management."""

    def test_add_log_appends(self):
        config = {}
        console = Console(file=open(os.devnull, "w"))
        db = DebugDashboard(config=config, console=console)
        db._add_log("Test message")
        assert len(db.log_lines) == 1
        assert "Test message" in db.log_lines[0]

    def test_add_log_includes_timestamp(self):
        config = {}
        console = Console(file=open(os.devnull, "w"))
        db = DebugDashboard(config=config, console=console)
        db._add_log("Hello")
        # Timestamp format: HH:MM:SS
        assert ":" in db.log_lines[0]

    def test_add_log_respects_max_lines(self):
        config = {}
        console = Console(file=open(os.devnull, "w"))
        db = DebugDashboard(config=config, console=console)
        for i in range(20):
            db._add_log(f"Line {i}")
        assert len(db.log_lines) <= db.max_log_lines


# ============================================================================
# load_urls_from_csv
# ============================================================================

class TestLoadUrlsFromCsv:
    """Tests for load_urls_from_csv."""

    def test_simple_url_list(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("https://example.com\n")
            f.write("https://test.org\n")
            f.write("https://sample.net\n")
            f.flush()
            try:
                urls = load_urls_from_csv(f.name)
                assert len(urls) == 3
                assert "https://example.com" in urls
                assert "https://test.org" in urls
            finally:
                os.unlink(f.name)

    def test_csv_with_url_header(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("url,status\n")
            f.write("https://example.com,active\n")
            f.write("https://test.org,active\n")
            f.flush()
            try:
                urls = load_urls_from_csv(f.name)
                assert len(urls) == 2
                assert "https://example.com" in urls
            finally:
                os.unlink(f.name)

    def test_csv_with_domain_header(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("domain,category\n")
            f.write("example.com,news\n")
            f.write("test.org,blog\n")
            f.flush()
            try:
                urls = load_urls_from_csv(f.name)
                assert len(urls) == 2
                # Domains should be prefixed with https://
                assert "https://example.com" in urls
            finally:
                os.unlink(f.name)

    def test_tranco_format(self):
        """Tranco format: rank,domain (first row consumed as header for detection)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("1,google.com\n")
            f.write("2,facebook.com\n")
            f.write("3,youtube.com\n")
            f.flush()
            try:
                urls = load_urls_from_csv(f.name)
                # First row is consumed as header for format detection
                assert len(urls) == 2
                assert "https://facebook.com" in urls
                assert "https://youtube.com" in urls
            finally:
                os.unlink(f.name)

    def test_domains_without_protocol_get_https(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("example.com\n")
            f.write("test.org\n")
            f.flush()
            try:
                urls = load_urls_from_csv(f.name)
                for url in urls:
                    assert url.startswith("https://")
            finally:
                os.unlink(f.name)

    def test_empty_lines_are_skipped(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("https://example.com\n")
            f.write("\n")
            f.write("https://test.org\n")
            f.write("\n")
            f.flush()
            try:
                urls = load_urls_from_csv(f.name)
                assert len(urls) == 2
            finally:
                os.unlink(f.name)

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            load_urls_from_csv("/nonexistent/path/to/file.csv")

    def test_urls_with_http_prefix_kept(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False
        ) as f:
            f.write("http://insecure.example.com\n")
            f.write("https://secure.example.com\n")
            f.flush()
            try:
                urls = load_urls_from_csv(f.name)
                assert "http://insecure.example.com" in urls
                assert "https://secure.example.com" in urls
            finally:
                os.unlink(f.name)
