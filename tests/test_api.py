"""
Integration Tests for the InjectionRadar REST API.

Tests hit the REAL running API at http://localhost:8000.
Requires Docker services to be running: docker compose up -d
"""

import pytest
import httpx

API_URL = "http://localhost:8000"


@pytest.fixture
def client():
    """Synchronous httpx client for API calls."""
    with httpx.Client(base_url=API_URL, timeout=10) as c:
        yield c


@pytest.fixture
async def async_client():
    """Async httpx client for API calls."""
    async with httpx.AsyncClient(base_url=API_URL, timeout=10) as c:
        yield c


def _api_reachable() -> bool:
    """Check if the API is reachable."""
    try:
        resp = httpx.get(f"{API_URL}/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


# Skip all tests if API is not running
pytestmark = pytest.mark.skipif(
    not _api_reachable(),
    reason="API not reachable at http://localhost:8000",
)


# ============================================================================
# Health Check
# ============================================================================

class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_status_is_healthy(self, client):
        data = client.get("/health").json()
        assert data["status"] == "healthy"

    def test_health_has_redis_connected(self, client):
        data = client.get("/health").json()
        assert "redis_connected" in data
        assert data["redis_connected"] is True

    def test_health_has_timestamp(self, client):
        data = client.get("/health").json()
        assert "timestamp" in data
        assert len(data["timestamp"]) > 10


# ============================================================================
# Status
# ============================================================================

class TestStatusEndpoint:
    """Tests for GET /status."""

    def test_status_returns_200(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200

    def test_status_response_structure(self, client):
        data = client.get("/status").json()
        expected_keys = [
            "status", "total_urls", "total_domains",
            "dangerous_count", "suspicious_count",
            "pending_count", "queue_length",
        ]
        for key in expected_keys:
            assert key in data, f"Missing key: {key}"

    def test_status_is_operational(self, client):
        data = client.get("/status").json()
        assert data["status"] == "operational"

    def test_status_counts_are_integers(self, client):
        data = client.get("/status").json()
        for key in ["total_urls", "total_domains", "dangerous_count",
                     "suspicious_count", "pending_count", "queue_length"]:
            assert isinstance(data[key], int), f"{key} should be int"


# ============================================================================
# Queue Stats
# ============================================================================

class TestQueueStatsEndpoint:
    """Tests for GET /queue/stats."""

    def test_queue_stats_returns_200(self, client):
        resp = client.get("/queue/stats")
        assert resp.status_code == 200

    def test_queue_stats_has_queue_length(self, client):
        data = client.get("/queue/stats").json()
        assert "queue_length" in data
        assert isinstance(data["queue_length"], int)
        assert data["queue_length"] >= 0

    def test_queue_stats_has_redis_info(self, client):
        data = client.get("/queue/stats").json()
        assert "redis_host" in data
        assert "redis_port" in data


# ============================================================================
# History
# ============================================================================

class TestHistoryEndpoint:
    """Tests for GET /history."""

    def test_history_returns_200(self, client):
        resp = client.get("/history")
        assert resp.status_code == 200

    def test_history_returns_array(self, client):
        data = client.get("/history").json()
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_history_has_total(self, client):
        data = client.get("/history").json()
        assert "total" in data
        assert isinstance(data["total"], int)

    def test_history_respects_limit(self, client):
        data = client.get("/history", params={"limit": 3}).json()
        assert len(data["history"]) <= 3

    def test_history_entry_structure(self, client):
        data = client.get("/history").json()
        if data["history"]:
            entry = data["history"][0]
            assert "url" in entry
            assert "status" in entry
            assert "http_status" in entry
            assert "scanned_at" in entry


# ============================================================================
# Async Scan Flow
# ============================================================================

class TestAsyncScanFlow:
    """Tests for POST /scan/async + GET /scan/{job_id}/status."""

    def test_async_scan_returns_job_id(self, client):
        resp = client.post("/scan/async", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "url" in data
        assert data["status"] == "queued"
        assert "message" in data

    def test_job_status_returns_valid_response(self, client):
        # Submit a job first
        resp = client.post("/scan/async", json={"url": "https://example.com"})
        job_id = resp.json()["job_id"]

        # Check status (might be pending or completed depending on timing)
        status_resp = client.get(f"/scan/{job_id}/status")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("pending", "completed", "failed")

    def test_async_scan_invalid_url_returns_422(self, client):
        resp = client.post("/scan/async", json={"url": "not-a-url"})
        assert resp.status_code == 422


# ============================================================================
# URL Status
# ============================================================================

class TestUrlStatusEndpoint:
    """Tests for GET /url/status."""

    def test_known_url_returns_200(self, client):
        resp = client.get("/url/status", params={"url": "https://example.com/"})
        assert resp.status_code == 200

    def test_known_url_response_structure(self, client):
        data = client.get(
            "/url/status", params={"url": "https://example.com/"}
        ).json()
        expected_keys = ["url", "status", "confidence", "scan_count"]
        for key in expected_keys:
            assert key in data, f"Missing key: {key}"

    def test_known_url_has_valid_status(self, client):
        data = client.get(
            "/url/status", params={"url": "https://example.com/"}
        ).json()
        valid_statuses = ["safe", "suspicious", "dangerous", "pending", "error"]
        assert data["status"] in valid_statuses

    def test_unknown_url_returns_404(self, client):
        resp = client.get(
            "/url/status",
            params={"url": "https://nonexistent-test-domain-12345.com/"},
        )
        assert resp.status_code == 404

    def test_unknown_url_error_detail(self, client):
        data = client.get(
            "/url/status",
            params={"url": "https://nonexistent-test-domain-12345.com/"},
        ).json()
        assert "detail" in data


# ============================================================================
# Dangerous Domains
# ============================================================================

class TestDangerousDomainsEndpoint:
    """Tests for GET /domains/dangerous."""

    def test_dangerous_domains_returns_200(self, client):
        resp = client.get("/domains/dangerous")
        assert resp.status_code == 200

    def test_dangerous_domains_response_structure(self, client):
        data = client.get("/domains/dangerous").json()
        assert "dangerous_domains" in data
        assert isinstance(data["dangerous_domains"], list)
        assert "total" in data

    def test_dangerous_domains_respects_limit(self, client):
        data = client.get("/domains/dangerous", params={"limit": 5}).json()
        assert len(data["dangerous_domains"]) <= 5


# ============================================================================
# Error Cases
# ============================================================================

class TestErrorCases:
    """Tests for error handling."""

    def test_nonexistent_endpoint_returns_404(self, client):
        resp = client.get("/nonexistent-endpoint")
        assert resp.status_code == 404

    def test_scan_missing_url_returns_422(self, client):
        resp = client.post("/scan", json={})
        assert resp.status_code == 422

    def test_scan_async_missing_body_returns_422(self, client):
        resp = client.post("/scan/async")
        assert resp.status_code == 422

    def test_results_nonexistent_id_returns_404(self, client):
        resp = client.get("/results/999999")
        assert resp.status_code == 404

    def test_domain_stats_nonexistent_returns_404(self, client):
        resp = client.get("/domains/nonexistent-test-domain-12345.com/stats")
        assert resp.status_code == 404

    def test_history_invalid_limit_returns_422(self, client):
        resp = client.get("/history", params={"limit": 0})
        assert resp.status_code == 422

    def test_history_limit_too_high_returns_422(self, client):
        resp = client.get("/history", params={"limit": 999})
        assert resp.status_code == 422


# ============================================================================
# Rate Limiting & Request ID Middleware
# ============================================================================

def _rate_limit_active() -> bool:
    """Check if the rate limiting middleware is deployed."""
    try:
        resp = httpx.get(f"{API_URL}/health", timeout=3)
        return "x-ratelimit-limit" in resp.headers
    except Exception:
        return False


_skip_no_ratelimit = pytest.mark.skipif(
    not _rate_limit_active(),
    reason="Rate limiting middleware not active (container needs rebuild)",
)


@_skip_no_ratelimit
class TestRequestIDMiddleware:
    """Tests for X-Request-ID header."""

    def test_request_id_present_on_get(self, client):
        resp = client.get("/health")
        assert "x-request-id" in resp.headers

    def test_request_id_is_uuid_format(self, client):
        resp = client.get("/health")
        request_id = resp.headers["x-request-id"]
        # UUID4 format: 8-4-4-4-12 hex chars
        parts = request_id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8

    def test_request_id_unique_per_request(self, client):
        id1 = client.get("/health").headers["x-request-id"]
        id2 = client.get("/health").headers["x-request-id"]
        assert id1 != id2

    def test_request_id_present_on_post(self, client):
        resp = client.post("/scan/async", json={"url": "https://example.com"})
        assert "x-request-id" in resp.headers

    def test_request_id_present_on_error(self, client):
        resp = client.get("/results/999999")
        assert resp.status_code == 404
        assert "x-request-id" in resp.headers


@_skip_no_ratelimit
class TestRateLimitHeaders:
    """Tests for X-RateLimit-Limit and X-RateLimit-Remaining headers."""

    def test_health_has_rate_limit_headers(self, client):
        resp = client.get("/health")
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers

    def test_status_has_rate_limit_headers(self, client):
        resp = client.get("/status")
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers

    def test_history_has_rate_limit_headers(self, client):
        resp = client.get("/history")
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers

    def test_scan_async_has_rate_limit_headers(self, client):
        resp = client.post("/scan/async", json={"url": "https://example.com"})
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers


@_skip_no_ratelimit
class TestRateLimitTiers:
    """Tests that rate limit values match the configured tiers."""

    def test_read_only_limit_is_60(self, client):
        resp = client.get("/health")
        assert resp.headers["x-ratelimit-limit"] == "60"

    def test_status_limit_is_60(self, client):
        resp = client.get("/status")
        assert resp.headers["x-ratelimit-limit"] == "60"

    def test_history_limit_is_60(self, client):
        resp = client.get("/history")
        assert resp.headers["x-ratelimit-limit"] == "60"

    def test_queue_stats_limit_is_60(self, client):
        resp = client.get("/queue/stats")
        assert resp.headers["x-ratelimit-limit"] == "60"

    def test_scan_async_limit_is_20(self, client):
        resp = client.post("/scan/async", json={"url": "https://example.com"})
        assert resp.headers["x-ratelimit-limit"] == "20"

    def test_scan_status_limit_is_10(self, client):
        """GET /scan/{id}/status starts with /scan so gets the /scan tier."""
        resp = client.get("/scan/fake-job-id/status")
        assert resp.headers["x-ratelimit-limit"] == "10"

    def test_remaining_is_less_than_limit(self, client):
        resp = client.get("/health")
        limit = int(resp.headers["x-ratelimit-limit"])
        remaining = int(resp.headers["x-ratelimit-remaining"])
        assert remaining < limit
        assert remaining >= 0

    def test_remaining_decreases(self, client):
        resp1 = client.get("/health")
        remaining1 = int(resp1.headers["x-ratelimit-remaining"])
        resp2 = client.get("/health")
        remaining2 = int(resp2.headers["x-ratelimit-remaining"])
        assert remaining2 < remaining1


# ============================================================================
# Rate Limit Status Endpoint
# ============================================================================

@_skip_no_ratelimit
class TestRateLimitStatusEndpoint:
    """Tests for GET /rate-limit/status."""

    def test_rate_limit_status_returns_200(self, client):
        resp = client.get("/rate-limit/status")
        assert resp.status_code == 200

    def test_rate_limit_status_structure(self, client):
        data = client.get("/rate-limit/status").json()
        assert "enabled" in data
        assert "window_seconds" in data
        assert "client_ip" in data
        assert "tiers" in data

    def test_rate_limit_status_tiers_present(self, client):
        data = client.get("/rate-limit/status").json()
        tiers = data["tiers"]
        assert "/scan" in tiers
        assert "/scan/async" in tiers
        assert "default" in tiers

    def test_rate_limit_status_tier_fields(self, client):
        data = client.get("/rate-limit/status").json()
        for tier_name, tier_data in data["tiers"].items():
            assert "limit" in tier_data, f"{tier_name} missing 'limit'"
            assert "used" in tier_data, f"{tier_name} missing 'used'"
            assert "remaining" in tier_data, f"{tier_name} missing 'remaining'"
            assert isinstance(tier_data["limit"], int)
            assert isinstance(tier_data["used"], int)
            assert isinstance(tier_data["remaining"], int)

    def test_rate_limit_status_enabled_is_bool(self, client):
        data = client.get("/rate-limit/status").json()
        assert isinstance(data["enabled"], bool)

    def test_rate_limit_status_window_is_positive(self, client):
        data = client.get("/rate-limit/status").json()
        assert data["window_seconds"] > 0

    def test_rate_limit_status_remaining_lte_limit(self, client):
        data = client.get("/rate-limit/status").json()
        for tier_name, tier_data in data["tiers"].items():
            assert tier_data["remaining"] <= tier_data["limit"], (
                f"{tier_name}: remaining ({tier_data['remaining']}) > limit ({tier_data['limit']})"
            )
