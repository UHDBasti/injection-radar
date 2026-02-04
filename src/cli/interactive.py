"""
Interaktives CLI für InjectionRadar.

Bietet eine benutzerfreundliche Shell-Erfahrung ähnlich wie Claude Code.
Startet automatisch alle benötigten Backend-Services.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.markdown import Markdown

from ..core.logging import (
    setup_logging,
    log_info,
    log_error,
    log_warning,
    log_scan,
    log_llm_call,
    log_error_with_trace,
    get_recent_logs,
    LOG_DIR,
)
from ..core.startup import auto_start_services, ensure_local_requirements, StartupManager

console = Console()

# Logger initialisieren
logger = setup_logging(level="INFO")  # INFO statt DEBUG für weniger Noise

# Konfigurationspfad (wie Claude Code in ~/.config/)
CONFIG_DIR = Path.home() / ".injection-radar"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"


def get_banner():
    """Zeigt das Willkommens-Banner (dezent)."""
    return """
[bold cyan]InjectionRadar[/bold cyan] [dim]v0.1.0[/dim]
[dim]Prompt Injection Scanner für Web-Inhalte[/dim]
"""


def load_config() -> dict:
    """Lädt die gespeicherte Konfiguration."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(config: dict):
    """Speichert die Konfiguration."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    # Nur für den Benutzer lesbar (API-Keys!)
    os.chmod(CONFIG_FILE, 0o600)


def setup_wizard() -> dict:
    """Interaktiver Setup-Wizard für die Erstkonfiguration."""
    console.print("\n[bold green]Willkommen beim InjectionRadar Setup![/bold green]\n")
    console.print("Ich helfe dir, alles einzurichten.\n")

    config = load_config()

    # LLM Provider auswählen
    console.print("[bold]1. LLM Provider[/bold]")
    console.print("   Welchen AI-Provider möchtest du verwenden?\n")

    providers = [
        ("1", "Anthropic Claude", "anthropic", "Empfohlen - beste Injection-Erkennung"),
        ("2", "OpenAI GPT", "openai", "GPT-4o oder GPT-4o-mini"),
        ("3", "Beide", "both", "Für Vergleichstests"),
        ("4", "Keinen (nur Pattern-Scan)", "none", "Funktioniert ohne API-Key"),
    ]

    for num, name, _, desc in providers:
        console.print(f"   [{num}] {name} - [dim]{desc}[/dim]")

    choice = Prompt.ask("\n   Deine Wahl", choices=["1", "2", "3", "4"], default="1")

    provider_map = {"1": "anthropic", "2": "openai", "3": "both", "4": "none"}
    config["provider"] = provider_map[choice]

    # API Keys abfragen
    if config["provider"] in ["anthropic", "both"]:
        console.print("\n[bold]2. Anthropic API Key[/bold]")
        console.print("   Hol dir einen Key von: [link]https://console.anthropic.com/[/link]\n")

        current_key = config.get("anthropic_api_key", "")
        if current_key:
            masked = current_key[:10] + "..." + current_key[-4:]
            console.print(f"   [dim]Aktueller Key: {masked}[/dim]")
            if not Confirm.ask("   Key ändern?", default=False):
                pass
            else:
                key = Prompt.ask("   Anthropic API Key", password=True)
                if key:
                    config["anthropic_api_key"] = key
        else:
            key = Prompt.ask("   Anthropic API Key", password=True)
            if key:
                config["anthropic_api_key"] = key

    if config["provider"] in ["openai", "both"]:
        console.print("\n[bold]3. OpenAI API Key[/bold]")
        console.print("   Hol dir einen Key von: [link]https://platform.openai.com/[/link]\n")

        current_key = config.get("openai_api_key", "")
        if current_key:
            masked = current_key[:10] + "..." + current_key[-4:]
            console.print(f"   [dim]Aktueller Key: {masked}[/dim]")
            if not Confirm.ask("   Key ändern?", default=False):
                pass
            else:
                key = Prompt.ask("   OpenAI API Key", password=True)
                if key:
                    config["openai_api_key"] = key
        else:
            key = Prompt.ask("   OpenAI API Key", password=True)
            if key:
                config["openai_api_key"] = key

    # Modell auswählen
    if config["provider"] != "none":
        console.print("\n[bold]4. Modell-Auswahl[/bold]")

        if config["provider"] in ["anthropic", "both"]:
            models = [
                ("1", "claude-sonnet-4-5-20250929", "Schnell & günstig (empfohlen)"),
                ("2", "claude-opus-4-5-20251101", "Beste Qualität, teurer"),
            ]
            console.print("   Anthropic Modell:")
            for num, name, desc in models:
                console.print(f"   [{num}] {name} - [dim]{desc}[/dim]")
            choice = Prompt.ask("   Wahl", choices=["1", "2"], default="1")
            config["anthropic_model"] = models[int(choice) - 1][1]

        if config["provider"] in ["openai", "both"]:
            models = [
                ("1", "gpt-4o-mini", "Schnell & günstig (empfohlen)"),
                ("2", "gpt-4o", "Beste Qualität"),
            ]
            console.print("   OpenAI Modell:")
            for num, name, desc in models:
                console.print(f"   [{num}] {name} - [dim]{desc}[/dim]")
            choice = Prompt.ask("   Wahl", choices=["1", "2"], default="1")
            config["openai_model"] = models[int(choice) - 1][1]

    # Datenbank
    console.print("\n[bold]5. Datenbank[/bold]")
    console.print("   Wo sollen die Scan-Ergebnisse gespeichert werden?\n")
    console.print("   [1] SQLite (lokal, einfach) - [dim]Empfohlen für Einzelnutzer[/dim]")
    console.print("   [2] PostgreSQL - [dim]Für Teams/Server[/dim]")

    db_choice = Prompt.ask("   Wahl", choices=["1", "2"], default="1")
    config["database_type"] = "sqlite" if db_choice == "1" else "postgresql"

    if config["database_type"] == "postgresql":
        config["db_host"] = Prompt.ask("   PostgreSQL Host", default="localhost")
        config["db_port"] = Prompt.ask("   PostgreSQL Port", default="5432")
        config["db_name"] = Prompt.ask("   Datenbank Name", default="injectionradar")
        config["db_user"] = Prompt.ask("   Benutzer", default="postgres")
        config["db_password"] = Prompt.ask("   Passwort", password=True)

    # Speichern
    save_config(config)

    console.print("\n[bold green]✓ Setup abgeschlossen![/bold green]")
    console.print(f"   Konfiguration gespeichert in: [cyan]{CONFIG_FILE}[/cyan]\n")

    return config


def show_status(config: dict):
    """Zeigt den aktuellen Status."""
    table = Table(title="InjectionRadar Status", show_header=False, box=None)
    table.add_column("Key", style="bold")
    table.add_column("Value")

    # Architektur-Modus
    if config.get("use_local_mode"):
        table.add_row("Architektur", "[yellow]Lokal[/yellow] (kein Docker)")
    else:
        table.add_row("Architektur", "[green]Zwei-System[/green] (Docker)")

    # Provider
    provider = config.get("provider", "none")
    provider_display = {
        "anthropic": "[green]Anthropic Claude[/green]",
        "openai": "[green]OpenAI GPT[/green]",
        "both": "[green]Anthropic + OpenAI[/green]",
        "none": "[yellow]Nur Pattern-Scan[/yellow]",
    }
    table.add_row("Provider", provider_display.get(provider, provider))

    # API Keys
    if config.get("anthropic_api_key"):
        key = config["anthropic_api_key"]
        table.add_row("Anthropic Key", f"[green]✓[/green] {key[:8]}...{key[-4:]}")
    elif provider in ["anthropic", "both"]:
        table.add_row("Anthropic Key", "[red]✗ Nicht konfiguriert[/red]")

    if config.get("openai_api_key"):
        key = config["openai_api_key"]
        table.add_row("OpenAI Key", f"[green]✓[/green] {key[:8]}...{key[-4:]}")
    elif provider in ["openai", "both"]:
        table.add_row("OpenAI Key", "[red]✗ Nicht konfiguriert[/red]")

    # Datenbank
    if config.get("use_local_mode"):
        table.add_row("Datenbank", "[green]SQLite[/green] (lokal)")
    else:
        table.add_row("Datenbank", "[green]PostgreSQL[/green] (Docker)")

    # Modelle
    if config.get("anthropic_model"):
        table.add_row("Anthropic Modell", config["anthropic_model"])
    if config.get("openai_model"):
        table.add_row("OpenAI Modell", config["openai_model"])

    console.print(table)
    console.print()


def show_help():
    """Zeigt die Hilfe."""
    help_text = """
## Verfügbare Befehle

| Befehl | Beschreibung |
|--------|--------------|
| `scan <url>` | Scannt eine URL (automatisch bester Modus) |
| `scan <url> --local` | Lokaler Scan ohne Docker |
| `scan <url> --quick` | Schneller Scan ohne LLM |
| `status` | Zeigt den aktuellen Status |
| `services` | Zeigt Docker-Service-Status |
| `restart` | Startet alle Services neu |
| `config` | Öffnet den Konfigurations-Wizard |
| `logs` | Zeigt die letzten Log-Einträge |
| `logs -f` | Zeigt Pfad zur Log-Datei |
| `help` | Diese Hilfe |
| `exit` / `quit` | Beendet InjectionRadar |

## Automatischer Start

Beim Start von `injection-radar` werden automatisch alle Docker-Services gestartet:
- PostgreSQL (Datenbank)
- Redis (Job Queue)
- Orchestrator (API Server)
- Scraper (Sandbox Worker)

Falls Docker nicht verfügbar ist, wird automatisch der lokale Modus verwendet.

## Beispiele

```
> scan https://example.com            # Automatisch via Docker
> scan https://example.com --local    # Erzwinge lokalen Modus
> services                            # Zeige Container-Status
> restart                             # Services neu starten
```

## Tastenkürzel

- `Ctrl+C` - Aktuellen Befehl abbrechen
- `Ctrl+D` - InjectionRadar beenden
"""
    console.print(Markdown(help_text))


def show_services_status():
    """Zeigt den Status der Docker-Services."""
    manager = StartupManager()

    if not manager.check_docker():
        console.print("[yellow]Docker nicht verfügbar[/yellow]")
        return

    all_running, status = manager.are_containers_running()

    table = Table(title="Docker Services", show_header=True)
    table.add_column("Service")
    table.add_column("Status")

    for service, running in status.items():
        if running:
            table.add_row(service, "[green]● Läuft[/green]")
        else:
            table.add_row(service, "[red]○ Gestoppt[/red]")

    console.print(table)

    # Queue-Status wenn möglich
    if status.get("redis"):
        try:
            import httpx
            response = httpx.get("http://localhost:8000/queue/stats", timeout=2)
            if response.status_code == 200:
                data = response.json()
                console.print(f"\n[dim]Jobs in Queue: {data.get('queue_length', 0)}[/dim]")
        except Exception:
            pass


def show_logs(show_path: bool = False):
    """Zeigt die Logs an."""
    from ..core.logging import get_recent_logs, get_log_files, CURRENT_LOG

    if show_path:
        console.print(f"[bold]Log-Verzeichnis:[/bold] {LOG_DIR}")
        console.print(f"[bold]Aktuelles Log:[/bold] {CURRENT_LOG}")
        console.print()
        console.print("[bold]Log-Dateien:[/bold]")
        for log_file in get_log_files()[:5]:
            size = log_file.stat().st_size / 1024
            console.print(f"  {log_file.name} ({size:.1f} KB)")
        return

    logs = get_recent_logs(50)
    if not logs:
        console.print("[dim]Keine Logs vorhanden.[/dim]")
        return

    console.print(f"[bold]Letzte {len(logs)} Log-Einträge:[/bold]\n")
    for line in logs:
        try:
            entry = json.loads(line)
            level = entry.get("level", "info").upper()
            event = entry.get("event", "")
            timestamp = entry.get("timestamp", "")[:19]

            level_colors = {
                "DEBUG": "dim",
                "INFO": "blue",
                "WARNING": "yellow",
                "ERROR": "red",
            }
            color = level_colors.get(level, "white")

            console.print(f"[{color}]{timestamp} [{level}][/{color}] {event}")

            # Zeige zusätzliche Infos bei Scans
            if "url" in entry:
                console.print(f"  [dim]URL: {entry['url']}[/dim]")
            if "severity_score" in entry:
                console.print(f"  [dim]Severity: {entry['severity_score']}[/dim]")
            if "error_message" in entry:
                console.print(f"  [red]Error: {entry['error_message']}[/red]")
        except json.JSONDecodeError:
            # Falls kein JSON, zeige Zeile direkt
            console.print(f"[dim]{line.strip()}[/dim]")


async def do_scan_via_api(url: str, config: dict):
    """Führt einen Scan via Orchestrator-API durch (Zwei-System-Architektur).

    Der CLI ruft die API auf, die wiederum über Redis mit dem
    Scraper-Subsystem kommuniziert. So sieht der Orchestrator
    niemals die Rohdaten.
    """
    import httpx

    api_url = config.get("orchestrator_url", "http://localhost:8000")
    log_info("api_scan_started", url=url, api=api_url)

    console.print(f"\n[bold]Scanne via API:[/bold] {url}")
    console.print(f"[dim]Orchestrator: {api_url}[/dim]\n")

    try:
        with console.status("[bold green]Sende an Orchestrator..."):
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    f"{api_url}/scan",
                    json={"url": url, "task": "summarize"},
                )

                if response.status_code != 200:
                    error = response.json().get("detail", "Unknown error")
                    log_error("api_scan_failed", url=url, status=response.status_code, error=error)
                    console.print(f"[red]API-Fehler ({response.status_code}): {error}[/red]")
                    return

                result = response.json()

        # Ergebnis anzeigen
        status = result.get("status")
        if status == "timeout":
            console.print("[yellow]Scan-Timeout. Der Scraper ist möglicherweise überlastet.[/yellow]")
            return
        elif status == "failed":
            console.print(f"[red]Scan fehlgeschlagen: {result.get('error_message')}[/red]")
            return

        severity = result.get("severity_score", 0)
        flags = result.get("flags", [])
        classification = result.get("classification", "unknown")

        log_info(
            "api_scan_completed",
            url=url,
            classification=classification,
            severity=severity,
            flags_count=len(flags),
        )

        # LLM-Info anzeigen
        if result.get("llm_provider"):
            console.print(f"[dim]LLM: {result['llm_provider']}/{result.get('llm_model', 'unknown')}[/dim]")
        if result.get("processing_time_ms"):
            console.print(f"[dim]Verarbeitung: {result['processing_time_ms']}ms[/dim]")

        _display_scan_result(severity, flags, classification)

    except httpx.ConnectError:
        log_error("api_connection_failed", url=api_url)
        console.print(f"[red]Keine Verbindung zum Orchestrator ({api_url})[/red]")
        console.print("[yellow]Tipp: Starte den Orchestrator mit 'docker-compose up' oder nutze '--local' für lokalen Scan[/yellow]")
    except Exception as e:
        log_error_with_trace("api_scan_error", e)
        console.print(f"[red]Fehler: {e}[/red]")


async def do_scan_local(url: str, config: dict, quick: bool = False):
    """Führt einen lokalen Scan durch (ohne Docker/Redis).

    Dieser Modus ist für Entwicklung und Tests gedacht.
    ACHTUNG: Hier läuft alles in einem Prozess, keine Isolation!
    """
    from ..analysis.detector import RedFlagDetector
    from ..core.models import ScrapedContent
    import httpx
    import hashlib

    scan_mode = "pattern" if quick else "llm"
    log_info("local_scan_started", url=url, mode=scan_mode, provider=config.get("provider", "none"))

    console.print(f"\n[bold]Scanne (lokal):[/bold] {url}")
    console.print(f"[dim]Modus: {'Pattern-Scan (schnell)' if quick else 'Vollständiger LLM-Scan'}[/dim]")
    console.print("[dim yellow]⚠ Lokaler Modus - keine Sandbox-Isolation![/dim yellow]\n")

    detector = RedFlagDetector()

    # Website laden
    with console.status("[bold green]Lade Website..."):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; InjectionRadar/0.1; +https://github.com/injection-radar)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "de,en;q=0.5",
            }
            async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=headers) as client:
                response = await client.get(url)
                html = response.text

                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                text = soup.get_text(separator=" ", strip=True)

                content = ScrapedContent(
                    url_id=0,
                    http_status=response.status_code,
                    response_time_ms=0,
                    raw_html=html,
                    extracted_text=text,
                    text_length=len(text),
                    word_count=len(text.split()),
                    content_hash=hashlib.sha256(html.encode()).hexdigest(),
                )
        except Exception as e:
            log_error("website_load_failed", url=url, error=str(e))
            console.print(f"[red]Fehler beim Laden: {e}[/red]")
            return

    log_info("website_loaded", url=url, text_length=content.text_length, word_count=content.word_count)
    console.print(f"[green]✓[/green] Website geladen ({content.text_length:,} Zeichen)")

    # Analyse
    if quick or config.get("provider") == "none":
        # Nur Pattern-Analyse
        with console.status("[bold green]Analysiere Patterns..."):
            flags = detector.detect_all(
                llm_output=content.extracted_text,
                tool_calls=[],
                expected_format="text",
            )
            severity = detector.calculate_severity_score(flags)
    else:
        # LLM-Analyse
        with console.status("[bold green]Analysiere mit LLM..."):
            try:
                # LLM Client erstellen
                if config.get("provider") in ["anthropic", "both"] and config.get("anthropic_api_key"):
                    from ..llm import AnthropicClient, DUMMY_TOOLS
                    from ..llm.anthropic import SUMMARIZE_SYSTEM_PROMPT, SUMMARIZE_USER_PROMPT_TEMPLATE

                    client = AnthropicClient(
                        api_key=config["anthropic_api_key"],
                        model=config.get("anthropic_model", "claude-sonnet-4-5-20250929"),
                    )

                    user_prompt = SUMMARIZE_USER_PROMPT_TEMPLATE.format(
                        content=content.extracted_text[:4000]
                    )

                    result = await client.generate(
                        system_prompt=SUMMARIZE_SYSTEM_PROMPT,
                        user_prompt=user_prompt,
                        tools=DUMMY_TOOLS,
                    )

                    flags = detector.detect_all(
                        llm_output=result.text,
                        tool_calls=result.tool_calls,
                        expected_format="text",
                        original_content=content.extracted_text,
                    )
                    severity = detector.calculate_severity_score(flags)

                    log_llm_call(
                        provider=client.provider_name,
                        model=client.model,
                        tokens_in=result.tokens_input,
                        tokens_out=result.tokens_output,
                        cost=result.cost_estimated,
                    )
                    console.print(f"[dim]LLM: {client.provider_name}/{client.model}[/dim]")
                    console.print(f"[dim]Tokens: {result.tokens_input} → {result.tokens_output}[/dim]")
                    console.print(f"[dim]Kosten: ${result.cost_estimated:.4f}[/dim]")

                elif config.get("provider") in ["openai", "both"] and config.get("openai_api_key"):
                    from ..llm import OpenAIClient
                    from ..llm.anthropic import SUMMARIZE_SYSTEM_PROMPT, SUMMARIZE_USER_PROMPT_TEMPLATE, DUMMY_TOOLS

                    client = OpenAIClient(
                        api_key=config["openai_api_key"],
                        model=config.get("openai_model", "gpt-4o-mini"),
                    )

                    user_prompt = SUMMARIZE_USER_PROMPT_TEMPLATE.format(
                        content=content.extracted_text[:4000]
                    )

                    result = await client.generate(
                        system_prompt=SUMMARIZE_SYSTEM_PROMPT,
                        user_prompt=user_prompt,
                        tools=DUMMY_TOOLS,
                    )

                    flags = detector.detect_all(
                        llm_output=result.text,
                        tool_calls=result.tool_calls,
                        expected_format="text",
                        original_content=content.extracted_text,
                    )
                    severity = detector.calculate_severity_score(flags)

                    log_llm_call(
                        provider=client.provider_name,
                        model=client.model,
                        tokens_in=result.tokens_input,
                        tokens_out=result.tokens_output,
                        cost=result.cost_estimated,
                    )
                    console.print(f"[dim]LLM: {client.provider_name}/{client.model}[/dim]")
                    console.print(f"[dim]Tokens: {result.tokens_input} → {result.tokens_output}[/dim]")
                    console.print(f"[dim]Kosten: ${result.cost_estimated:.4f}[/dim]")
                else:
                    log_warning("no_api_key_configured", provider=config.get("provider"))
                    console.print("[yellow]Kein API-Key konfiguriert. Verwende Pattern-Scan.[/yellow]")
                    flags = detector.detect_all(
                        llm_output=content.extracted_text,
                        tool_calls=[],
                        expected_format="text",
                    )
                    severity = detector.calculate_severity_score(flags)
            except Exception as e:
                log_error_with_trace("llm_call_failed", e)
                console.print(f"[red]LLM-Fehler: {e}[/red]")
                console.print("[yellow]Fallback auf Pattern-Scan...[/yellow]")
                flags = detector.detect_all(
                    llm_output=content.extracted_text,
                    tool_calls=[],
                    expected_format="text",
                )
                severity = detector.calculate_severity_score(flags)

    # Ergebnis anzeigen
    classification = "dangerous" if severity >= 6 else "suspicious" if severity >= 3 else "safe"
    _display_scan_result(severity, flags, classification, is_local=True)

    # Scan-Ergebnis loggen
    log_scan(
        url=url,
        result={
            "severity_score": severity,
            "flags_count": len(flags),
            "classification": classification,
            "flags": [{"type": f.type.value, "severity": f.severity.value} for f in flags],
        }
    )


def _display_scan_result(severity: float, flags: list, classification: str, is_local: bool = False):
    """Zeigt das Scan-Ergebnis an (wiederverwendbar für beide Modi)."""
    console.print()

    if severity >= 6:
        rating = "[bold red]GEFÄHRLICH[/bold red]"
    elif severity >= 3:
        rating = "[bold yellow]VERDÄCHTIG[/bold yellow]"
    elif severity > 0:
        rating = "[bold blue]LEICHT VERDÄCHTIG[/bold blue]"
    else:
        rating = "[bold green]SICHER[/bold green]"

    console.print(Panel(
        f"Severity Score: [bold]{severity:.1f}/10[/bold]\n"
        f"Bewertung: {rating}\n"
        f"Red Flags: {len(flags)}",
        title="Scan-Ergebnis",
    ))

    if flags:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Typ")
        table.add_column("Schweregrad")
        table.add_column("Beschreibung")

        # Für lokalen Scan haben wir RedFlag-Objekte, für API haben wir dicts
        severity_color_map = {
            "critical": "red",
            "high": "orange1",
            "medium": "yellow",
            "low": "blue",
        }

        for flag in flags:
            if is_local:
                # RedFlag-Objekt
                from ..core.models import Severity
                color = {
                    Severity.CRITICAL: "red",
                    Severity.HIGH: "orange1",
                    Severity.MEDIUM: "yellow",
                    Severity.LOW: "blue",
                }.get(flag.severity, "white")
                table.add_row(
                    flag.type.value,
                    f"[{color}]{flag.severity.value}[/{color}]",
                    flag.description,
                )
            else:
                # Dict von API
                sev = flag.get("severity", "low")
                color = severity_color_map.get(sev, "white")
                table.add_row(
                    flag.get("type", "unknown"),
                    f"[{color}]{sev}[/{color}]",
                    flag.get("description", ""),
                )

        console.print(table)
    else:
        console.print("[green]Keine verdächtigen Muster gefunden.[/green]")

    console.print()


async def do_scan(url: str, config: dict, quick: bool = False, local: bool = False):
    """Führt einen Scan durch (wählt automatisch den Modus).

    Args:
        url: Die zu scannende URL
        config: Konfiguration (API-Keys, etc.)
        quick: Nur Pattern-Scan ohne LLM
        local: Lokaler Modus ohne API (für Entwicklung)
    """
    # Wenn local=True oder API nicht konfiguriert, nutze lokalen Modus
    use_local = local or config.get("use_local_mode", False)

    if use_local:
        await do_scan_local(url, config, quick)
    else:
        # Prüfe ob Orchestrator erreichbar ist
        api_url = config.get("orchestrator_url", "http://localhost:8000")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2) as client:
                await client.get(f"{api_url}/health")
            # API erreichbar, nutze sie
            await do_scan_via_api(url, config)
        except Exception:
            # API nicht erreichbar, Fallback auf lokalen Modus
            console.print("[yellow]Orchestrator nicht erreichbar - nutze lokalen Modus[/yellow]")
            await do_scan_local(url, config, quick)


def interactive_shell():
    """Startet die interaktive Shell mit automatischem Service-Start."""
    log_info("interactive_shell_started")

    # Banner zuerst
    console.print(get_banner())

    config = load_config()

    # Erstes Setup wenn nötig
    if not config or not config.get("provider"):
        log_info("running_setup_wizard")
        config = setup_wizard()

    # =========================================================================
    # AUTOMATISCHER SERVICE-START
    # =========================================================================
    services_ready, use_local = auto_start_services(console)

    if use_local:
        # Lokaler Modus - stelle sicher dass SQLite etc. bereit ist
        ensure_local_requirements()
        config["use_local_mode"] = True
        console.print("[dim]Modus: Lokal (SQLite, kein Docker)[/dim]")
    else:
        config["use_local_mode"] = False
        console.print("[dim]Modus: Zwei-System-Architektur (Docker)[/dim]")

    console.print()

    # Status anzeigen
    show_status(config)

    # Hilfe-Hinweis
    console.print("[dim]Tippe 'help' für verfügbare Befehle oder 'scan <url>' zum Starten.[/dim]\n")

    # Event Loop für die gesamte Session (vermeidet "Event loop is closed" Fehler)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # REPL
    try:
        while True:
            try:
                cmd = Prompt.ask("[bold cyan]>[/bold cyan]")
                cmd = cmd.strip()

                if not cmd:
                    continue

                parts = cmd.split()
                command = parts[0].lower()
                args = parts[1:]

                if command in ["exit", "quit", "q"]:
                    console.print("\n[dim]Auf Wiedersehen![/dim]\n")
                    break

                elif command == "help":
                    show_help()

                elif command == "status":
                    show_status(config)

                elif command == "config":
                    config = setup_wizard()

                elif command == "scan":
                    if not args:
                        console.print("[red]Bitte gib eine URL an: scan <url>[/red]")
                        continue

                    url = args[0]
                    if not url.startswith(("http://", "https://")):
                        url = "https://" + url

                    quick = "--quick" in args or "-q" in args
                    local = "--local" in args or "-l" in args

                    # Nutze den persistenten Event Loop
                    loop.run_until_complete(do_scan(url, config, quick, local))

                elif command == "logs":
                    show_path = "-f" in args or "--file" in args
                    show_logs(show_path)

                elif command == "history":
                    console.print("[dim]History-Feature kommt bald...[/dim]")

                elif command == "services":
                    show_services_status()

                elif command == "restart":
                    # Services neu starten
                    console.print("[dim]Starte Services neu...[/dim]")
                    manager = StartupManager()
                    if manager.check_docker():
                        manager.stop_containers()
                        services_ready, use_local = auto_start_services(console)
                        config["use_local_mode"] = use_local
                    else:
                        console.print("[yellow]Docker nicht verfügbar[/yellow]")

                else:
                    console.print(f"[red]Unbekannter Befehl: {command}[/red]")
                    console.print("[dim]Tippe 'help' für verfügbare Befehle.[/dim]")

            except KeyboardInterrupt:
                console.print("\n[dim]Abgebrochen. Tippe 'exit' zum Beenden.[/dim]")
                continue

            except EOFError:
                console.print("\n[dim]Auf Wiedersehen![/dim]\n")
                break

            except Exception as e:
                log_error_with_trace("repl_error", e)
                console.print(f"[red]Fehler: {e}[/red]")

    finally:
        # Event Loop sauber schließen
        try:
            # Alle pending tasks canceln
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            # Loop schließen
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
        except Exception:
            pass


def main():
    """Entry Point."""
    interactive_shell()


if __name__ == "__main__":
    main()
