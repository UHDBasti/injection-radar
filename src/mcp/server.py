"""
MCP Server Implementation für InjectionRadar.

Bietet folgende Tools:
- scan_url: Scannt eine URL auf Prompt Injection
- scan_urls: Scannt mehrere URLs parallel
- get_history: Zeigt die Scan-Historie
- check_url: Prüft den Status einer URL in der Datenbank
"""

import asyncio
import json
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    Server = None

import httpx

# Default Orchestrator URL
DEFAULT_API_URL = "http://localhost:8000"


def create_mcp_server(api_url: str = DEFAULT_API_URL) -> "Server":
    """Erstellt einen MCP Server für InjectionRadar.

    Args:
        api_url: URL des Orchestrator API Servers

    Returns:
        Konfigurierter MCP Server
    """
    if not MCP_AVAILABLE:
        raise ImportError(
            "MCP SDK nicht installiert. "
            "Installiere mit: pip install mcp"
        )

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
                            "description": "Anzahl der Einträge (Standard: 10, Max: 50)",
                            "default": 10,
                            "maximum": 50,
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
                            "description": "Anzahl der Einträge (Standard: 20)",
                            "default": 20,
                        },
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Führt ein Tool aus."""
        try:
            if name == "scan_url":
                result = await _scan_url(api_url, arguments.get("url", ""))
            elif name == "scan_urls":
                result = await _scan_urls(api_url, arguments.get("urls", []))
            elif name == "get_history":
                result = await _get_history(api_url, arguments.get("limit", 10))
            elif name == "check_url":
                result = await _check_url(api_url, arguments.get("url", ""))
            elif name == "get_dangerous_domains":
                result = await _get_dangerous_domains(api_url, arguments.get("limit", 20))
            else:
                result = {"error": f"Unbekanntes Tool: {name}"}

            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        except Exception as e:
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e)}, indent=2)
            )]

    return server


async def _scan_url(api_url: str, url: str) -> dict:
    """Scannt eine einzelne URL."""
    if not url:
        return {"error": "URL ist erforderlich"}

    # URL normalisieren
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{api_url}/scan",
            json={"url": url, "task": "summarize"},
        )

        if response.status_code != 200:
            return {
                "error": f"API-Fehler: {response.status_code}",
                "detail": response.text,
            }

        result = response.json()

        # Formatiere Ergebnis für AI
        return {
            "url": url,
            "classification": result.get("classification", "unknown"),
            "severity_score": result.get("severity_score", 0),
            "is_dangerous": result.get("classification") == "dangerous",
            "flags_count": len(result.get("flags", [])),
            "flags": result.get("flags", []),
            "summary": _generate_summary(result),
        }


async def _scan_urls(api_url: str, urls: list[str]) -> dict:
    """Scannt mehrere URLs parallel."""
    if not urls:
        return {"error": "Mindestens eine URL ist erforderlich"}

    if len(urls) > 10:
        return {"error": "Maximal 10 URLs gleichzeitig erlaubt"}

    # URLs normalisieren
    normalized = []
    for url in urls:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        normalized.append(url)

    # Parallel scannen
    async with httpx.AsyncClient(timeout=180) as client:
        tasks = [
            client.post(f"{api_url}/scan", json={"url": url, "task": "summarize"})
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
                "error": str(response),
            })
            error_count += 1
        elif response.status_code != 200:
            results.append({
                "url": url,
                "status": "error",
                "error": f"HTTP {response.status_code}",
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
                "flags_count": len(data.get("flags", [])),
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


async def _get_history(api_url: str, limit: int = 10) -> dict:
    """Holt die Scan-Historie."""
    limit = min(limit, 50)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{api_url}/history", params={"limit": limit})

        if response.status_code != 200:
            return {"error": f"API-Fehler: {response.status_code}"}

        return response.json()


async def _check_url(api_url: str, url: str) -> dict:
    """Prüft den Status einer URL."""
    if not url:
        return {"error": "URL ist erforderlich"}

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{api_url}/url/status", params={"url": url})

        if response.status_code == 404:
            return {
                "url": url,
                "scanned": False,
                "message": "URL wurde noch nicht gescannt",
            }

        if response.status_code != 200:
            return {"error": f"API-Fehler: {response.status_code}"}

        data = response.json()
        data["scanned"] = True
        return data


async def _get_dangerous_domains(api_url: str, limit: int = 20) -> dict:
    """Holt die Liste gefährlicher Domains."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{api_url}/domains/dangerous",
            params={"limit": limit}
        )

        if response.status_code != 200:
            return {"error": f"API-Fehler: {response.status_code}"}

        return response.json()


def _generate_summary(result: dict) -> str:
    """Generiert eine lesbare Zusammenfassung des Scan-Ergebnisses."""
    classification = result.get("classification", "unknown")
    severity = result.get("severity_score", 0)
    flags = result.get("flags", [])

    if classification == "dangerous":
        summary = f"GEFÄHRLICH (Severity: {severity:.1f}/10). "
        if flags:
            flag_types = [f.get("type", "unknown") for f in flags]
            summary += f"Erkannte Bedrohungen: {', '.join(flag_types)}"
    elif classification == "suspicious":
        summary = f"VERDÄCHTIG (Severity: {severity:.1f}/10). "
        if flags:
            summary += f"{len(flags)} verdächtige Muster erkannt."
    else:
        summary = f"SICHER. Keine Prompt Injection Anzeichen gefunden."

    return summary


async def run_mcp_server(api_url: str = DEFAULT_API_URL):
    """Startet den MCP Server.

    Args:
        api_url: URL des Orchestrator API Servers
    """
    if not MCP_AVAILABLE:
        print("Fehler: MCP SDK nicht installiert.")
        print("Installiere mit: pip install mcp")
        return

    server = create_mcp_server(api_url)

    async with stdio_server() as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options(),
        )


def main():
    """Entry Point für MCP Server."""
    import sys

    api_url = DEFAULT_API_URL
    if len(sys.argv) > 1:
        api_url = sys.argv[1]

    asyncio.run(run_mcp_server(api_url))


if __name__ == "__main__":
    main()
