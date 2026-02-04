"""
Interaktives CLI für InjectionRadar.

Bietet eine benutzerfreundliche Shell-Erfahrung ähnlich wie Claude Code.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.markdown import Markdown

console = Console()

# Konfigurationspfad (wie Claude Code in ~/.config/)
CONFIG_DIR = Path.home() / ".injection-radar"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"


def get_banner():
    """Zeigt das Willkommens-Banner."""
    return """
[bold blue]╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   [bold white]██╗███╗   ██╗     ██╗███████╗ ██████╗████████╗██╗ ██████╗ ███╗   ██╗[/bold white]   ║
║   [bold white]██║████╗  ██║     ██║██╔════╝██╔════╝╚══██╔══╝██║██╔═══██╗████╗  ██║[/bold white]   ║
║   [bold white]██║██╔██╗ ██║     ██║█████╗  ██║        ██║   ██║██║   ██║██╔██╗ ██║[/bold white]   ║
║   [bold white]██║██║╚██╗██║██   ██║██╔══╝  ██║        ██║   ██║██║   ██║██║╚██╗██║[/bold white]   ║
║   [bold white]██║██║ ╚████║╚█████╔╝███████╗╚██████╗   ██║   ██║╚██████╔╝██║ ╚████║[/bold white]   ║
║   [bold white]╚═╝╚═╝  ╚═══╝ ╚════╝ ╚══════╝ ╚═════╝   ╚═╝   ╚═╝ ╚═════╝ ╚═╝  ╚═══╝[/bold white]   ║
║                                                              ║
║             [bold cyan]██████╗  █████╗ ██████╗  █████╗ ██████╗[/bold cyan]             ║
║             [bold cyan]██╔══██╗██╔══██╗██╔══██╗██╔══██╗██╔══██╗[/bold cyan]            ║
║             [bold cyan]██████╔╝███████║██║  ██║███████║██████╔╝[/bold cyan]            ║
║             [bold cyan]██╔══██╗██╔══██║██║  ██║██╔══██║██╔══██╗[/bold cyan]            ║
║             [bold cyan]██║  ██║██║  ██║██████╔╝██║  ██║██║  ██║[/bold cyan]            ║
║             [bold cyan]╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝[/bold cyan]            ║
║                                                              ║
║        [dim]Prompt Injection Scanner für Web-Inhalte[/dim]            ║
║                      [dim]v0.1.0[/dim]                                 ║
╚══════════════════════════════════════════════════════════════╝[/bold blue]
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
    db_type = config.get("database_type", "sqlite")
    if db_type == "sqlite":
        table.add_row("Datenbank", "[green]SQLite[/green] (lokal)")
    else:
        host = config.get("db_host", "localhost")
        table.add_row("Datenbank", f"[green]PostgreSQL[/green] ({host})")

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
| `scan <url>` | Scannt eine URL auf Prompt Injection |
| `scan <url> --quick` | Schneller Scan ohne LLM (nur Patterns) |
| `status` | Zeigt den aktuellen Status |
| `config` | Öffnet den Konfigurations-Wizard |
| `history` | Zeigt letzte Scans |
| `help` | Diese Hilfe |
| `exit` / `quit` | Beendet InjectionRadar |

## Beispiele

```
> scan https://example.com
> scan https://suspicious-site.com --quick
> config
```

## Tastenkürzel

- `Ctrl+C` - Aktuellen Befehl abbrechen
- `Ctrl+D` - InjectionRadar beenden
"""
    console.print(Markdown(help_text))


async def do_scan(url: str, config: dict, quick: bool = False):
    """Führt einen Scan durch."""
    from ..analysis.detector import RedFlagDetector
    from ..core.models import ScrapedContent
    import httpx
    import hashlib

    console.print(f"\n[bold]Scanne:[/bold] {url}")
    console.print(f"[dim]Modus: {'Pattern-Scan (schnell)' if quick else 'Vollständiger LLM-Scan'}[/dim]\n")

    detector = RedFlagDetector()

    # Website laden
    with console.status("[bold green]Lade Website..."):
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
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
            console.print(f"[red]Fehler beim Laden: {e}[/red]")
            return

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

                    console.print(f"[dim]LLM: {client.provider_name}/{client.model}[/dim]")
                    console.print(f"[dim]Tokens: {result.tokens_input} → {result.tokens_output}[/dim]")
                    console.print(f"[dim]Kosten: ${result.cost_estimated:.4f}[/dim]")
                else:
                    console.print("[yellow]Kein API-Key konfiguriert. Verwende Pattern-Scan.[/yellow]")
                    flags = detector.detect_all(
                        llm_output=content.extracted_text,
                        tool_calls=[],
                        expected_format="text",
                    )
                    severity = detector.calculate_severity_score(flags)
            except Exception as e:
                console.print(f"[red]LLM-Fehler: {e}[/red]")
                console.print("[yellow]Fallback auf Pattern-Scan...[/yellow]")
                flags = detector.detect_all(
                    llm_output=content.extracted_text,
                    tool_calls=[],
                    expected_format="text",
                )
                severity = detector.calculate_severity_score(flags)

    # Ergebnis anzeigen
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

        from ..core.models import Severity
        severity_colors = {
            Severity.CRITICAL: "red",
            Severity.HIGH: "orange1",
            Severity.MEDIUM: "yellow",
            Severity.LOW: "blue",
        }

        for flag in flags:
            color = severity_colors.get(flag.severity, "white")
            table.add_row(
                flag.type.value,
                f"[{color}]{flag.severity.value}[/{color}]",
                flag.description,
            )

        console.print(table)
    else:
        console.print("[green]Keine verdächtigen Muster gefunden.[/green]")

    console.print()


def interactive_shell():
    """Startet die interaktive Shell."""
    config = load_config()

    # Erstes Setup wenn nötig
    if not config or not config.get("provider"):
        config = setup_wizard()

    # Banner
    console.print(get_banner())

    # Status
    show_status(config)

    # Hilfe-Hinweis
    console.print("[dim]Tippe 'help' für verfügbare Befehle oder 'scan <url>' zum Starten.[/dim]\n")

    # REPL
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

                asyncio.run(do_scan(url, config, quick))

            elif command == "history":
                console.print("[dim]History-Feature kommt bald...[/dim]")

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
            console.print(f"[red]Fehler: {e}[/red]")


def main():
    """Entry Point."""
    interactive_shell()


if __name__ == "__main__":
    main()
