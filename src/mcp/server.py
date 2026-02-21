"""
MCP Server Implementation für InjectionRadar.

Bietet folgende Tools:
- scan_url: Scannt eine URL auf Prompt Injection
- scan_urls: Scannt mehrere URLs parallel
- get_history: Zeigt die Scan-Historie
- check_url: Prüft den Status einer URL in der Datenbank
- get_dangerous_domains: Listet gefährliche Domains
- get_system_status: Zeigt kombinierten System-Status
- get_scan_statistics: Zeigt formatierte Scan-Statistiken
"""

import asyncio
import json
from typing import Any
from urllib.parse import urlparse

import structlog

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    Server = None

import httpx

from ..core.config import get_settings, MCPConfig

log = structlog.get_logger("mcp.server")


def _get_mcp_config() -> MCPConfig:
    """Returns MCPConfig from settings."""
    try:
        settings = get_settings()
        return settings.mcp
    except Exception:
        return MCPConfig()


def _validate_url(url: str) -> str | None:
    """Validates and normalizes a URL. Returns error message or None if valid."""
    if not url or not url.strip():
        return "URL is required. Provide a valid URL like https://example.com"
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        return f"Invalid URL '{url}': must contain a valid domain (e.g. example.com)"
    return None


def _normalize_url(url: str) -> str:
    """Adds https:// prefix if missing."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _validate_limit(limit: int, min_val: int = 1, max_val: int = 100) -> int:
    """Clamps limit to valid range."""
    return max(min_val, min(limit, max_val))


async def _api_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    max_retries: int = 3,
    **kwargs,
) -> httpx.Response:
    """Makes an API request with exponential backoff retry logic."""
    last_error = None
    for attempt in range(max_retries):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            last_error = e
            if attempt == max_retries - 1:
                raise
            wait_time = 2 ** attempt
            log.warning(
                "api_request_retry",
                url=url,
                attempt=attempt + 1,
                max_retries=max_retries,
                wait_seconds=wait_time,
                error=str(e),
            )
            await asyncio.sleep(wait_time)
        except httpx.HTTPStatusError:
            raise
    raise last_error  # Should not reach here, but just in case


def create_mcp_server(api_url: str | None = None) -> tuple["Server", httpx.AsyncClient]:
    """Erstellt einen MCP Server für InjectionRadar.

    Args:
        api_url: URL des Orchestrator API Servers (uses config default if None)

    Returns:
        Tuple of (MCP Server, httpx client). Caller must close the client.
    """
    if not MCP_AVAILABLE:
        raise ImportError(
            "MCP SDK nicht installiert. "
            "Installiere mit: pip install mcp"
        )

    config = _get_mcp_config()
    if api_url is None:
        api_url = config.api_url

    # Shared HTTP client for connection pooling
    client = httpx.AsyncClient(
        timeout=config.timeout_seconds,
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=5,
        ),
    )
    max_retries = config.max_retries

    server = Server("injection-radar")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Listet alle verfügbaren Tools."""
        return [
            Tool(
                name="scan_url",
                description=(
                    "Scannt eine URL auf Prompt Injection Angriffe. "
                    "Gibt Klassifizierung (safe/suspicious/dangerous), "
                    "Severity Score (0-10) und erkannte Red Flags zurück."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Die zu scannende URL (z.B. https://example.com)",
                        },
                    },
                    "required": ["url"],
                },
            ),
            Tool(
                name="scan_urls",
                description=(
                    "Scannt mehrere URLs parallel auf Prompt Injection. "
                    "Maximal 10 URLs gleichzeitig. "
                    "Gibt eine Zusammenfassung aller Ergebnisse zurück."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Liste der zu scannenden URLs",
                            "maxItems": 10,
                        },
                    },
                    "required": ["urls"],
                },
            ),
            Tool(
                name="get_history",
                description=(
                    "Zeigt die letzten Scan-Ergebnisse aus der Datenbank. "
                    "Nützlich um zu sehen, welche URLs bereits gescannt wurden."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Anzahl der Einträge (Standard: 10, Max: 100)",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                },
            ),
            Tool(
                name="check_url",
                description=(
                    "Prüft ob eine URL bereits gescannt wurde und zeigt den Status. "
                    "Gibt cached Ergebnisse zurück wenn vorhanden."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Die zu prüfende URL",
                        },
                    },
                    "required": ["url"],
                },
            ),
            Tool(
                name="get_dangerous_domains",
                description=(
                    "Listet alle als gefährlich eingestuften Domains. "
                    "Nützlich für Blocklisten und Sicherheitsüberprüfungen."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Anzahl der Einträge (Standard: 20, Max: 100)",
                            "default": 20,
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                },
            ),
            Tool(
                name="get_system_status",
                description=(
                    "Zeigt den kombinierten System-Status inkl. Health Check, "
                    "Queue-Status und Scan-Statistiken. "
                    "Nützlich um zu prüfen ob das System betriebsbereit ist."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="get_scan_statistics",
                description=(
                    "Zeigt formatierte Scan-Statistiken: Anzahl gescannter URLs, "
                    "Domains, Klassifizierungen und Queue-Auslastung."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Führt ein Tool aus."""
        log.info("tool_called", tool=name, arguments=arguments)
        try:
            if name == "scan_url":
                result = await _scan_url(client, api_url, max_retries, arguments.get("url", ""))
            elif name == "scan_urls":
                result = await _scan_urls(client, api_url, max_retries, arguments.get("urls", []))
            elif name == "get_history":
                result = await _get_history(client, api_url, max_retries, arguments.get("limit", 10))
            elif name == "check_url":
                result = await _check_url(client, api_url, max_retries, arguments.get("url", ""))
            elif name == "get_dangerous_domains":
                result = await _get_dangerous_domains(client, api_url, max_retries, arguments.get("limit", 20))
            elif name == "get_system_status":
                result = await _get_system_status(client, api_url, max_retries)
            elif name == "get_scan_statistics":
                result = await _get_scan_statistics(client, api_url, max_retries)
            else:
                result = {"error": f"Unknown tool: {name}. Available tools: scan_url, scan_urls, get_history, check_url, get_dangerous_domains, get_system_status, get_scan_statistics"}

            log.info("tool_completed", tool=name, success="error" not in result)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except httpx.ConnectError:
            error_msg = (
                f"Cannot connect to InjectionRadar API at {api_url}. "
                "Ensure the orchestrator is running (docker compose up -d or injection-radar)."
            )
            log.error("tool_connection_error", tool=name, api_url=api_url)
            return [TextContent(type="text", text=json.dumps({"error": error_msg}, indent=2))]

        except httpx.TimeoutException:
            error_msg = (
                f"Request to {api_url} timed out after {config.timeout_seconds}s. "
                "The scan may still be processing. Try again or check system status."
            )
            log.error("tool_timeout", tool=name, api_url=api_url)
            return [TextContent(type="text", text=json.dumps({"error": error_msg}, indent=2))]

        except httpx.HTTPStatusError as e:
            error_msg = f"API returned HTTP {e.response.status_code}: {e.response.text[:200]}"
            log.error("tool_http_error", tool=name, status_code=e.response.status_code)
            return [TextContent(type="text", text=json.dumps({"error": error_msg}, indent=2))]

        except Exception as e:
            log.error("tool_error", tool=name, error=str(e), error_type=type(e).__name__)
            return [TextContent(
                type="text",
                text=json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"}, indent=2)
            )]

    return server, client


async def _scan_url(client: httpx.AsyncClient, api_url: str, max_retries: int, url: str) -> dict:
    """Scannt eine einzelne URL."""
    error = _validate_url(url)
    if error:
        return {"error": error}

    url = _normalize_url(url)
    log.info("scanning_url", url=url)

    response = await _api_request(
        client, "POST", f"{api_url}/scan",
        max_retries=max_retries,
        json={"url": url, "task": "summarize"},
    )

    result = response.json()
    return {
        "url": url,
        "classification": result.get("classification", "unknown"),
        "severity_score": result.get("severity_score", 0),
        "is_dangerous": result.get("classification") == "dangerous",
        "flags_count": len(result.get("flags") or []),
        "flags": result.get("flags") or [],
        "summary": _generate_summary(result),
    }


async def _scan_urls(client: httpx.AsyncClient, api_url: str, max_retries: int, urls: list[str]) -> dict:
    """Scannt mehrere URLs parallel."""
    if not urls:
        return {"error": "At least one URL is required. Provide a list of URLs to scan."}

    if len(urls) > 10:
        return {"error": f"Too many URLs ({len(urls)}). Maximum is 10 URLs per request."}

    # Validate and normalize all URLs
    normalized = []
    for url in urls:
        error = _validate_url(url)
        if error:
            return {"error": f"Invalid URL in list: {error}"}
        normalized.append(_normalize_url(url))

    log.info("scanning_urls", count=len(normalized))

    # Parallel scannen using shared client
    tasks = [
        _api_request(
            client, "POST", f"{api_url}/scan",
            max_retries=max_retries,
            json={"url": url, "task": "summarize"},
        )
        for url in normalized
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    dangerous_count = 0
    suspicious_count = 0
    safe_count = 0
    error_count = 0

    for url, response in zip(normalized, responses):
        if isinstance(response, Exception):
            results.append({
                "url": url,
                "status": "error",
                "error": f"{type(response).__name__}: {response}",
            })
            error_count += 1
        else:
            data = response.json()
            classification = data.get("classification", "unknown")

            if classification == "dangerous":
                dangerous_count += 1
            elif classification == "suspicious":
                suspicious_count += 1
            else:
                safe_count += 1

            results.append({
                "url": url,
                "classification": classification,
                "severity_score": data.get("severity_score", 0),
                "flags_count": len(data.get("flags") or []),
            })

    return {
        "total_scanned": len(urls),
        "summary": {
            "dangerous": dangerous_count,
            "suspicious": suspicious_count,
            "safe": safe_count,
            "errors": error_count,
        },
        "has_dangerous_urls": dangerous_count > 0,
        "results": results,
    }


async def _get_history(client: httpx.AsyncClient, api_url: str, max_retries: int, limit: int = 10) -> dict:
    """Holt die Scan-Historie."""
    limit = _validate_limit(limit, 1, 100)

    response = await _api_request(
        client, "GET", f"{api_url}/history",
        max_retries=max_retries,
        params={"limit": limit},
    )
    return response.json()


async def _check_url(client: httpx.AsyncClient, api_url: str, max_retries: int, url: str) -> dict:
    """Prüft den Status einer URL."""
    error = _validate_url(url)
    if error:
        return {"error": error}

    url = _normalize_url(url)

    try:
        response = await _api_request(
            client, "GET", f"{api_url}/url/status",
            max_retries=max_retries,
            params={"url": url},
        )
        data = response.json()
        data["scanned"] = True
        return data
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {
                "url": url,
                "scanned": False,
                "message": "URL has not been scanned yet. Use scan_url to scan it.",
            }
        raise


async def _get_dangerous_domains(client: httpx.AsyncClient, api_url: str, max_retries: int, limit: int = 20) -> dict:
    """Holt die Liste gefährlicher Domains."""
    limit = _validate_limit(limit, 1, 100)

    response = await _api_request(
        client, "GET", f"{api_url}/domains/dangerous",
        max_retries=max_retries,
        params={"limit": limit},
    )
    return response.json()


async def _get_system_status(client: httpx.AsyncClient, api_url: str, max_retries: int) -> dict:
    """Holt kombinierten System-Status von /health und /status."""
    health_data = None
    status_data = None
    errors = []

    # Fetch health and status in parallel
    health_task = _api_request(client, "GET", f"{api_url}/health", max_retries=max_retries)
    status_task = _api_request(client, "GET", f"{api_url}/status", max_retries=max_retries)

    results = await asyncio.gather(health_task, status_task, return_exceptions=True)

    if isinstance(results[0], Exception):
        errors.append(f"Health check failed: {results[0]}")
    else:
        health_data = results[0].json()

    if isinstance(results[1], Exception):
        errors.append(f"Status check failed: {results[1]}")
    else:
        status_data = results[1].json()

    combined = {
        "api_reachable": health_data is not None,
    }

    if health_data:
        combined["health"] = {
            "status": health_data.get("status", "unknown"),
            "redis_connected": health_data.get("redis_connected", False),
            "timestamp": health_data.get("timestamp"),
        }

    if status_data:
        combined["system"] = {
            "status": status_data.get("status", "unknown"),
            "total_urls": status_data.get("total_urls", 0),
            "total_domains": status_data.get("total_domains", 0),
            "queue_length": status_data.get("queue_length", 0),
            "last_scan": status_data.get("last_scan"),
        }

    if errors:
        combined["errors"] = errors

    return combined


async def _get_scan_statistics(client: httpx.AsyncClient, api_url: str, max_retries: int) -> dict:
    """Holt und formatiert Scan-Statistiken."""
    response = await _api_request(
        client, "GET", f"{api_url}/status",
        max_retries=max_retries,
    )
    data = response.json()

    total = data.get("total_urls", 0)
    dangerous = data.get("dangerous_count", 0)
    suspicious = data.get("suspicious_count", 0)
    pending = data.get("pending_count", 0)
    safe = total - dangerous - suspicious - pending
    if safe < 0:
        safe = 0

    danger_pct = (dangerous / total * 100) if total > 0 else 0
    suspicious_pct = (suspicious / total * 100) if total > 0 else 0
    safe_pct = (safe / total * 100) if total > 0 else 0

    return {
        "total_urls_scanned": total,
        "total_domains": data.get("total_domains", 0),
        "classifications": {
            "dangerous": {"count": dangerous, "percentage": round(danger_pct, 1)},
            "suspicious": {"count": suspicious, "percentage": round(suspicious_pct, 1)},
            "safe": {"count": safe, "percentage": round(safe_pct, 1)},
            "pending": pending,
        },
        "queue_length": data.get("queue_length", 0),
        "last_scan": data.get("last_scan"),
        "system_status": data.get("status", "unknown"),
    }


def _generate_summary(result: dict) -> str:
    """Generiert eine lesbare Zusammenfassung des Scan-Ergebnisses."""
    classification = result.get("classification", "unknown")
    severity = result.get("severity_score", 0)
    flags = result.get("flags") or []

    if classification == "dangerous":
        summary = f"DANGEROUS (Severity: {severity:.1f}/10). "
        if flags:
            flag_types = [f.get("type", "unknown") for f in flags]
            summary += f"Detected threats: {', '.join(flag_types)}"
    elif classification == "suspicious":
        summary = f"SUSPICIOUS (Severity: {severity:.1f}/10). "
        if flags:
            summary += f"{len(flags)} suspicious patterns detected."
    else:
        summary = "SAFE. No prompt injection indicators found."

    return summary


async def _check_api_health(api_url: str, timeout: float = 5.0) -> bool:
    """Checks if the API is reachable on startup."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{api_url}/health")
            return response.status_code == 200
    except Exception:
        return False


async def run_mcp_server(api_url: str | None = None):
    """Startet den MCP Server.

    Args:
        api_url: URL des Orchestrator API Servers (uses config default if None)
    """
    if not MCP_AVAILABLE:
        print("Error: MCP SDK not installed.")
        print("Install with: pip install 'injection-radar[mcp]'")
        return

    config = _get_mcp_config()
    if api_url is None:
        api_url = config.api_url

    # Health check on startup
    log.info("mcp_server_starting", api_url=api_url)
    api_healthy = await _check_api_health(api_url)
    if api_healthy:
        log.info("api_health_check_passed", api_url=api_url)
    else:
        log.warning(
            "api_health_check_failed",
            api_url=api_url,
            message="API not reachable. Tools will retry on each request.",
        )

    server, client = create_mcp_server(api_url)

    try:
        async with stdio_server() as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )
    finally:
        await client.aclose()


def main():
    """Entry Point für MCP Server."""
    import sys

    api_url = None
    if len(sys.argv) > 1:
        api_url = sys.argv[1]

    asyncio.run(run_mcp_server(api_url))


if __name__ == "__main__":
    main()
