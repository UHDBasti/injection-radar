"""
Unit tests for the InjectionRadar debug dashboard logic.

Tests cover:
1. JobTracker state machine (finish/fail guards, idempotency)
2. _parse_log_line JSON extraction (pure JSON, Docker-prefixed, non-JSON, empty)
3. _find_tracker partial matching (full ID, 8-char prefix, non-existing)
4. _show_final_results timing (elapsed uses end_time, not current time)
"""

import json
import io
import os
import time

import pytest
from rich.console import Console

from src.cli.debug_dashboard import (
    JobState,
    StepEntry,
    JobTracker,
    DebugDashboard,
)


# ============================================================================
# Helper: create a DebugDashboard with a devnull console
# ============================================================================

def make_dashboard(**kwargs) -> DebugDashboard:
    config = kwargs.pop("config", {"orchestrator_url": "http://localhost:8000"})
    console = Console(file=open(os.devnull, "w"))
    return DebugDashboard(config=config, console=console)


# ============================================================================
# 1. JobTracker State Machine
# ============================================================================

class TestJobTrackerStateMachine:
    """Thorough tests for the JobTracker state-machine guards."""

    # --- Initial state ---

    def test_initial_state_is_queued(self):
        tracker = JobTracker(job_id="test-001", url="https://example.com")
        assert tracker.state == JobState.QUEUED

    def test_initial_has_one_step(self):
        tracker = JobTracker(job_id="test-001", url="https://example.com")
        assert len(tracker.steps) == 1
        assert tracker.steps[0].label == "Job in Queue"
        assert tracker.steps[0].state == "ok"

    def test_initial_end_time_is_none(self):
        tracker = JobTracker(job_id="test-001", url="https://example.com")
        assert tracker.end_time is None

    # --- finish() ---

    def test_finish_sets_state_to_done(self):
        tracker = JobTracker(job_id="test-001", url="https://example.com")
        tracker.finish(classification="safe", severity=0.0)
        assert tracker.state == JobState.DONE

    def test_finish_sets_end_time(self):
        tracker = JobTracker(job_id="test-001", url="https://example.com")
        before = time.time()
        tracker.finish(classification="safe", severity=0.0)
        after = time.time()
        assert tracker.end_time is not None
        assert before <= tracker.end_time <= after

    def test_finish_adds_step(self):
        tracker = JobTracker(job_id="test-001", url="https://example.com")
        tracker.finish(classification="dangerous", severity=8.5)
        # Should have initial step + finish step = 2
        assert len(tracker.steps) == 2
        last = tracker.steps[-1]
        assert "dangerous" in last.label
        assert "8.5" in last.label
        assert last.state == "ok"

    def test_finish_again_no_duplicate_step(self):
        """Calling finish() twice should NOT add a second finish step (guard)."""
        tracker = JobTracker(job_id="test-001", url="https://example.com")
        tracker.finish(classification="safe", severity=0.0)
        step_count_after_first = len(tracker.steps)
        end_time_after_first = tracker.end_time

        tracker.finish(classification="dangerous", severity=9.0)
        assert len(tracker.steps) == step_count_after_first, \
            "Second finish() should NOT add another step"
        assert tracker.state == JobState.DONE
        assert tracker.end_time == end_time_after_first, \
            "end_time should not change on second finish()"

    # --- fail() ---

    def test_fail_sets_state_to_failed(self):
        tracker = JobTracker(job_id="test-002", url="https://fail.com")
        tracker.fail("Connection timeout")
        assert tracker.state == JobState.FAILED

    def test_fail_sets_end_time(self):
        tracker = JobTracker(job_id="test-002", url="https://fail.com")
        before = time.time()
        tracker.fail("timeout")
        after = time.time()
        assert tracker.end_time is not None
        assert before <= tracker.end_time <= after

    def test_fail_sets_error(self):
        tracker = JobTracker(job_id="test-002", url="https://fail.com")
        tracker.fail("Connection timeout")
        assert tracker.error == "Connection timeout"

    def test_fail_adds_step(self):
        tracker = JobTracker(job_id="test-002", url="https://fail.com")
        tracker.fail("Connection timeout")
        assert len(tracker.steps) == 2  # initial + fail
        last = tracker.steps[-1]
        assert last.state == "failed"
        assert "Fehler:" in last.label

    def test_fail_again_no_duplicate_step(self):
        """Calling fail() twice should NOT add a second fail step (guard)."""
        tracker = JobTracker(job_id="test-002", url="https://fail.com")
        tracker.fail("first error")
        step_count_after_first = len(tracker.steps)
        end_time_after_first = tracker.end_time

        tracker.fail("second error")
        assert len(tracker.steps) == step_count_after_first, \
            "Second fail() should NOT add another step"
        assert tracker.state == JobState.FAILED
        assert tracker.error == "first error", \
            "Error message should not change on second fail()"
        assert tracker.end_time == end_time_after_first

    # --- Cross-guard: finish on FAILED, fail on DONE ---

    def test_finish_on_failed_tracker_stays_failed(self):
        """Once FAILED, calling finish() should be a no-op."""
        tracker = JobTracker(job_id="test-003", url="https://cross.com")
        tracker.fail("something broke")
        step_count = len(tracker.steps)

        tracker.finish(classification="safe", severity=0.0)
        assert tracker.state == JobState.FAILED, \
            "finish() on a FAILED tracker must not change state"
        assert len(tracker.steps) == step_count, \
            "finish() on a FAILED tracker must not add steps"

    def test_fail_on_done_tracker_stays_done(self):
        """Once DONE, calling fail() should be a no-op."""
        tracker = JobTracker(job_id="test-004", url="https://cross.com")
        tracker.finish(classification="safe", severity=0.0)
        step_count = len(tracker.steps)
        original_end_time = tracker.end_time

        tracker.fail("late error")
        assert tracker.state == JobState.DONE, \
            "fail() on a DONE tracker must not change state"
        assert len(tracker.steps) == step_count, \
            "fail() on a DONE tracker must not add steps"
        assert tracker.error is None, \
            "error should remain None when fail() is called on DONE tracker"
        assert tracker.end_time == original_end_time

    # --- Running steps cleared on finish/fail ---

    def test_finish_clears_running_steps(self):
        tracker = JobTracker(job_id="test-005", url="https://example.com")
        tracker.update_running_step("Working...")
        assert any(s.state == "running" for s in tracker.steps)
        tracker.finish("safe", 0.0)
        assert not any(s.state == "running" for s in tracker.steps)

    def test_fail_marks_running_as_failed(self):
        tracker = JobTracker(job_id="test-005", url="https://example.com")
        tracker.update_running_step("Working...")
        tracker.fail("crash")
        working = [s for s in tracker.steps if s.label == "Working..."]
        assert working[0].state == "failed"


# ============================================================================
# 2. _parse_log_line JSON Extraction
# ============================================================================

class TestParseLogLine:
    """Tests for _parse_log_line JSON extraction from various line formats."""

    @pytest.fixture
    def dashboard(self):
        db = make_dashboard()
        tracker = JobTracker(job_id="abc12345-6789-0123", url="https://example.com")
        db.jobs["abc12345-6789-0123"] = tracker
        return db

    def test_pure_json_line(self, dashboard):
        """Pure JSON with event and job_id should update tracker."""
        line = '{"event":"job_processing","job_id":"abc12345-6789-0123"}'
        dashboard._parse_log_line(line)
        tracker = dashboard.jobs["abc12345-6789-0123"]
        assert tracker.state == JobState.SCRAPING

    def test_docker_prefixed_json_line(self, dashboard):
        """Docker log format: timestamp [LEVEL] name: {JSON} should be parsed."""
        line = (
            '2026-02-20 12:12:55,672 [INFO] injection-radar: '
            '{"event":"website_scraped","job_id":"abc12345-6789-0123","word_count":1000}'
        )
        dashboard._parse_log_line(line)
        tracker = dashboard.jobs["abc12345-6789-0123"]
        assert tracker.state == JobState.SCRAPED
        assert tracker.word_count == 1000

    def test_non_json_line(self, dashboard):
        """A plain text line should not crash and should be added to log."""
        initial_log_count = len(dashboard.log_lines)
        dashboard._parse_log_line("Some random text")
        # Should add to log_lines (as non-JSON fallback)
        assert len(dashboard.log_lines) == initial_log_count + 1

    def test_empty_line(self, dashboard):
        """An empty line should not crash and should not add to logs."""
        initial_log_count = len(dashboard.log_lines)
        dashboard._parse_log_line("")
        # Empty line: json.loads("") raises JSONDecodeError,
        # then the non-JSON handler checks `if line` which is False for ""
        assert len(dashboard.log_lines) == initial_log_count

    def test_docker_prefix_extracts_correct_json(self, dashboard):
        """Ensure only the JSON part after ': {' is parsed, not the prefix."""
        line = (
            '2026-02-20 12:12:55,672 [INFO] injection-radar: '
            '{"event":"job_completed","job_id":"abc12345-6789-0123",'
            '"severity":3.5,"classification":"suspicious"}'
        )
        dashboard._parse_log_line(line)
        tracker = dashboard.jobs["abc12345-6789-0123"]
        assert tracker.state == JobState.DONE

    def test_partial_job_id_in_json(self, dashboard):
        """JSON log with 8-char partial job_id should match via _find_tracker."""
        line = '{"event":"job_processing","job_id":"abc12345"}'
        dashboard._parse_log_line(line)
        tracker = dashboard.jobs["abc12345-6789-0123"]
        assert tracker.state == JobState.SCRAPING


# ============================================================================
# 3. _find_tracker Partial Matching
# ============================================================================

class TestFindTracker:
    """Tests for _find_tracker with full and partial job IDs."""

    @pytest.fixture
    def dashboard(self):
        db = make_dashboard()
        tracker = JobTracker(
            job_id="abcd1234-5678-9012",
            url="https://example.com",
        )
        db.jobs["abcd1234-5678-9012"] = tracker
        return db

    def test_find_by_full_id(self, dashboard):
        result = dashboard._find_tracker("abcd1234-5678-9012")
        assert result is not None
        assert result.job_id == "abcd1234-5678-9012"

    def test_find_by_first_8_chars(self, dashboard):
        result = dashboard._find_tracker("abcd1234")
        assert result is not None
        assert result.job_id == "abcd1234-5678-9012"

    def test_find_by_nonexisting_id(self, dashboard):
        result = dashboard._find_tracker("xxxxxxxx-0000-0000")
        assert result is None

    def test_find_short_partial_less_than_8_returns_none(self, dashboard):
        """Partial IDs shorter than 8 chars should not match (guard in code)."""
        result = dashboard._find_tracker("abcd")
        assert result is None

    def test_find_partial_prefix_mismatch(self, dashboard):
        """8-char string that doesn't match any prefix should return None."""
        result = dashboard._find_tracker("zzzz1234")
        assert result is None

    def test_find_with_multiple_trackers(self):
        """With multiple jobs, partial match should find the right one."""
        db = make_dashboard()
        t1 = JobTracker(job_id="aaaa1111-xxxx-xxxx", url="https://a.com")
        t2 = JobTracker(job_id="bbbb2222-yyyy-yyyy", url="https://b.com")
        db.jobs["aaaa1111-xxxx-xxxx"] = t1
        db.jobs["bbbb2222-yyyy-yyyy"] = t2

        found = db._find_tracker("bbbb2222")
        assert found is not None
        assert found.job_id == "bbbb2222-yyyy-yyyy"

        found = db._find_tracker("aaaa1111")
        assert found is not None
        assert found.job_id == "aaaa1111-xxxx-xxxx"


# ============================================================================
# 4. _show_final_results Timing
# ============================================================================

class TestShowFinalResultsTiming:
    """Tests that _show_final_results uses end_time for elapsed, not current time."""

    def test_elapsed_uses_end_time_not_current_time(self):
        """If a job finished 100s ago, elapsed should reflect
        (end_time - start_time), not (now - start_time)."""
        buf = io.StringIO()
        console = Console(file=buf, width=120, force_terminal=False)
        config = {"orchestrator_url": "http://localhost:8000"}
        db = DebugDashboard(config=config, console=console)

        # Create a tracker with known fixed times
        tracker = JobTracker(job_id="timing-test-1234", url="https://example.com")
        tracker.start_time = 1000.0  # Arbitrary epoch value
        tracker.end_time = 1005.5    # 5.5 seconds later
        tracker.state = JobState.DONE
        tracker.result = {
            "classification": "safe",
            "severity_score": 0.0,
            "flags": [],
        }
        db.jobs["timing-test-1234"] = tracker

        db._show_final_results()

        output = buf.getvalue()
        # The elapsed should be 5.5s (end_time - start_time),
        # NOT hundreds of thousands of seconds (now - start_time)
        assert "5.5s" in output, (
            f"Expected '5.5s' in output for elapsed time. Got:\n{output}"
        )

    def test_total_time_uses_earliest_start_to_latest_end(self):
        """Total time should span from earliest start to latest end."""
        buf = io.StringIO()
        console = Console(file=buf, width=120, force_terminal=False)
        config = {"orchestrator_url": "http://localhost:8000"}
        db = DebugDashboard(config=config, console=console)

        # Job 1: starts at t=1000, ends at t=1003
        t1 = JobTracker(job_id="job-a-12345678", url="https://a.com")
        t1.start_time = 1000.0
        t1.end_time = 1003.0
        t1.state = JobState.DONE
        t1.result = {"classification": "safe", "severity_score": 0.0, "flags": []}
        db.jobs["job-a-12345678"] = t1

        # Job 2: starts at t=1001, ends at t=1008
        t2 = JobTracker(job_id="job-b-12345678", url="https://b.com")
        t2.start_time = 1001.0
        t2.end_time = 1008.0
        t2.state = JobState.DONE
        t2.result = {"classification": "suspicious", "severity_score": 3.0, "flags": []}
        db.jobs["job-b-12345678"] = t2

        db._show_final_results()

        output = buf.getvalue()
        # Total time = latest_end (1008) - earliest_start (1000) = 8.0s
        assert "8.0s" in output, (
            f"Expected '8.0s' for total time. Got:\n{output}"
        )

    def test_failed_job_elapsed_uses_end_time(self):
        """Even for failed jobs, elapsed should use end_time."""
        buf = io.StringIO()
        console = Console(file=buf, width=120, force_terminal=False)
        config = {"orchestrator_url": "http://localhost:8000"}
        db = DebugDashboard(config=config, console=console)

        tracker = JobTracker(job_id="fail-test-12345678", url="https://fail.com")
        tracker.start_time = 2000.0
        tracker.end_time = 2012.3
        tracker.state = JobState.FAILED
        tracker.error = "timeout"
        db.jobs["fail-test-12345678"] = tracker

        db._show_final_results()

        output = buf.getvalue()
        assert "12.3s" in output, (
            f"Expected '12.3s' for failed job elapsed. Got:\n{output}"
        )

    def test_pending_job_falls_back_to_now(self):
        """A job with no end_time should fall back to time.time() for elapsed.
        We just verify it doesn't crash and produces a reasonable value."""
        buf = io.StringIO()
        console = Console(file=buf, width=120, force_terminal=False)
        config = {"orchestrator_url": "http://localhost:8000"}
        db = DebugDashboard(config=config, console=console)

        tracker = JobTracker(job_id="pending-12345678", url="https://pending.com")
        tracker.start_time = time.time() - 2.0  # started 2 seconds ago
        tracker.end_time = None  # still running
        tracker.state = JobState.QUEUED
        db.jobs["pending-12345678"] = tracker

        # Should not crash
        db._show_final_results()
        output = buf.getvalue()
        # Output should contain some elapsed time > 0
        assert "s" in output  # basic sanity


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
