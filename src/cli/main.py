"""
CLI-Tool für InjectionRadar.

Ermöglicht das Scannen von URLs, Anzeigen von Status und Ergebnissen.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from ..core.config import Settings, get_settings
from ..core.models import Classification, RedFlagType, Severity
from ..core.database import (
    get_async_engine,
    get_async_session_factory,
    init_db,
    DomainDB,
    URLDB,
    AnalysisResultDB,
)
from ..scraper.worker import ScraperWorker
from ..analysis.detector import RedFlagDetector

app = typer.Typer(
    name="injection-radar",
    help="InjectionRadar - Prompt Injection Scanner für Web-Inhalte",
    add_completion=False,
)
console = Console()


@app.command()
def init(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Pfad zur config.yaml (erstellt Beispiel wenn nicht vorhanden)",
    ),
):
    """Initialisiert InjectionRadar und die Datenbank."""
    console.print(Panel.fit(
        "[bold blue]InjectionRadar Setup[/bold blue]",
        subtitle="Initialisierung",
    ))

    # Config prüfen
    config_file = config_path or Path("config/config.yaml")
    example_file = Path("config/config.example.yaml")

    if not config_file.exists():
        if example_file.exists():
            console.print(f"[yellow]Keine Konfiguration gefunden.[/yellow]")
            console.print(f"Kopiere [cyan]{example_file}[/cyan] nach [cyan]{config_file}[/cyan] und passe sie an.")

            # Kopieren
            import shutil
            config_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(example_file, config_file)
            console.print(f"[green]✓[/green] Beispiel-Konfiguration erstellt: {config_file}")
        else:
            console.print("[red]Fehler: Keine Konfigurationsdatei gefunden.[/red]")
            raise typer.Exit(1)

    # Settings laden
    try:
        settings = Settings.from_yaml(config_file)
        console.print(f"[green]✓[/green] Konfiguration geladen")
    except Exception as e:
        console.print(f"[red]Fehler beim Laden der Konfiguration: {e}[/red]")
        raise typer.Exit(1)

    # API Keys prüfen
    if settings.anthropic_api_key:
        console.print(f"[green]✓[/green] Anthropic API Key konfiguriert")
    elif settings.openai_api_key:
        console.print(f"[green]✓[/green] OpenAI API Key konfiguriert")
    else:
        console.print("[yellow]⚠[/yellow] Kein LLM API Key konfiguriert (ANTHROPIC_API_KEY oder OPENAI_API_KEY)")

    # Datenbank initialisieren
    console.print("\n[bold]Initialisiere Datenbank...[/bold]")

    async def setup_db():
        engine = get_async_engine(settings.database.url)
        await init_db(engine)
        return True

    try:
        asyncio.run(setup_db())
        if settings.database.type == "sqlite":
            console.print(f"[green]✓[/green] SQLite Datenbank initialisiert: {settings.database.sqlite_path}")
        else:
            console.print(f"[green]✓[/green] PostgreSQL Datenbank initialisiert: {settings.database.host}:{settings.database.port}/{settings.database.name}")
    except Exception as e:
        console.print(f"[red]Fehler bei Datenbankverbindung: {e}[/red]")
        if settings.database.type == "postgresql":
            console.print("[dim]Ist PostgreSQL gestartet? Prüfe die Verbindungsdaten in der config.yaml[/dim]")

    console.print("\n[bold green]Setup abgeschlossen![/bold green]")


@app.command()
def scan(
    url: str = typer.Argument(..., help="URL zum Scannen"),
    task: str = typer.Option("summarize", "--task", "-t", help="Test-Task (summarize, extract)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Ausführliche Ausgabe"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Nur Pattern-Analyse ohne LLM (kein API-Key nötig)"),
    use_httpx: bool = typer.Option(False, "--simple", "-s", help="Einfaches HTTP statt Playwright (schneller)"),
):
    """Scannt eine einzelne URL auf Prompt Injection."""
    mode = "Pattern-Scan" if no_llm else f"LLM-Test ({task})"
    console.print(Panel.fit(
        f"[bold]Scanne:[/bold] {url}",
        subtitle=f"Modus: {mode}",
    ))

    settings = get_settings()
    detector = RedFlagDetector()

    async def run_scan():
        if use_httpx:
            # Einfaches HTTP ohne Playwright
            import httpx
            import hashlib
            from datetime import datetime
            from ..core.models import ScrapedContent

            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                response = await client.get(url)
                html = response.text

                # Einfache Text-Extraktion
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
                return content, None
        else:
            # Playwright-basiertes Scraping
            worker = ScraperWorker()
            await worker.start()
            try:
                content = await worker.scrape_url(url)
                if not no_llm:
                    result = await worker.run_llm_test(content, task)
                    return content, result
                return content, None
            finally:
                await worker.stop()

    async def run_simple_scan():
        # Einfaches HTTP ohne Playwright
        import httpx
        import hashlib
        from ..core.models import ScrapedContent

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(url)
            html = response.text

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)

            return ScrapedContent(
                url_id=0,
                http_status=response.status_code,
                response_time_ms=0,
                raw_html=html,
                extracted_text=text,
                text_length=len(text),
                word_count=len(text.split()),
                content_hash=hashlib.sha256(html.encode()).hexdigest(),
            )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task_id = progress.add_task("Lade Website...", total=None)

        if use_httpx:
            content = asyncio.run(run_simple_scan())
            result = None
        else:
            content, result = asyncio.run(run_scan())

        progress.update(task_id, description="Analysiere...")

        # Pattern-Analyse auf Website-Text
        if no_llm:
            text_flags = detector.detect_all(
                llm_output=content.extracted_text,
                tool_calls=[],
                expected_format="text",
            )
            severity = detector.calculate_severity_score(text_flags)
        else:
            text_flags = result.flags_detected if result else []
            severity = detector.calculate_severity_score(text_flags)

        progress.update(task_id, description="Fertig!")

    # Ergebnisse anzeigen
    console.print("\n[bold]Scraping-Ergebnis:[/bold]")
    console.print(f"  HTTP Status: {content.http_status}")
    console.print(f"  Text-Länge: {content.text_length:,} Zeichen")
    console.print(f"  Wörter: {content.word_count:,}")
    if hasattr(content, 'external_links') and content.external_links:
        console.print(f"  Externe Links: {len(content.external_links)}")

    if no_llm:
        console.print("\n[bold]Pattern-Analyse:[/bold]")
        console.print(f"  Modus: Ohne LLM (Pattern-Matching)")
        console.print(f"  Severity Score: {severity:.1f}/10")
    else:
        console.print("\n[bold]LLM-Scan-Ergebnis:[/bold]")
        if result:
            console.print(f"  LLM: {result.llm_provider}/{result.llm_model}")
            console.print(f"  Output-Format: {result.output_format_detected}")
            console.print(f"  Tool-Calls: {result.tool_calls_count}")

    # Red Flags anzeigen
    flags_to_show = text_flags if no_llm else (result.flags_detected if result else [])

    if flags_to_show:
        console.print(f"\n[bold red]⚠ {len(flags_to_show)} Red Flag(s) erkannt:[/bold red]")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Typ")
        table.add_column("Schweregrad")
        table.add_column("Beschreibung")

        severity_colors = {
            Severity.CRITICAL: "red",
            Severity.HIGH: "orange1",
            Severity.MEDIUM: "yellow",
            Severity.LOW: "blue",
        }

        for flag in flags_to_show:
            color = severity_colors.get(flag.severity, "white")
            table.add_row(
                flag.type.value,
                f"[{color}]{flag.severity.value}[/{color}]",
                flag.description,
            )

        console.print(table)

        if verbose:
            console.print("\n[bold]Evidence:[/bold]")
            for flag in flags_to_show:
                if flag.evidence:
                    console.print(f"  [{flag.type.value}]: {flag.evidence[:200]}")
    else:
        console.print("\n[bold green]✓ Keine Red Flags erkannt[/bold green]")


@app.command()
def status():
    """Zeigt den aktuellen Scan-Status an."""
    settings = get_settings()

    async def get_status():
        engine = get_async_engine(settings.database.url)
        SessionFactory = get_async_session_factory(engine)

        async with SessionFactory() as session:
            from sqlalchemy import select, func

            # URLs nach Status zählen
            result = await session.execute(
                select(
                    URLDB.current_status,
                    func.count(URLDB.id)
                ).group_by(URLDB.current_status)
            )
            status_counts = dict(result.fetchall())

            # Domains zählen
            domain_count = await session.scalar(
                select(func.count(DomainDB.id))
            )

            # Letzte Analysen
            result = await session.execute(
                select(AnalysisResultDB)
                .order_by(AnalysisResultDB.analyzed_at.desc())
                .limit(5)
            )
            recent = result.scalars().all()

            return status_counts, domain_count, recent

    try:
        status_counts, domain_count, recent = asyncio.run(get_status())

        console.print(Panel.fit("[bold blue]InjectionRadar Status[/bold blue]"))

        # Übersicht
        table = Table(title="URL-Status", show_header=True)
        table.add_column("Status")
        table.add_column("Anzahl", justify="right")

        status_colors = {
            Classification.SAFE: "green",
            Classification.SUSPICIOUS: "yellow",
            Classification.DANGEROUS: "red",
            Classification.ERROR: "orange1",
            Classification.PENDING: "dim",
        }

        total = 0
        for status in Classification:
            count = status_counts.get(status, 0)
            total += count
            color = status_colors.get(status, "white")
            table.add_row(
                f"[{color}]{status.value}[/{color}]",
                str(count),
            )

        table.add_row("[bold]Gesamt[/bold]", f"[bold]{total}[/bold]")
        console.print(table)

        console.print(f"\nDomains erfasst: {domain_count}")

        if recent:
            console.print("\n[bold]Letzte Analysen:[/bold]")
            for analysis in recent:
                color = status_colors.get(analysis.classification, "white")
                console.print(
                    f"  [{color}]{analysis.classification.value}[/{color}] "
                    f"URL #{analysis.url_id} - {analysis.analyzed_at.strftime('%Y-%m-%d %H:%M')}"
                )

    except Exception as e:
        console.print(f"[red]Fehler: {e}[/red]")
        console.print("[dim]Ist die Datenbank erreichbar? Führe 'injection-radar init' aus.[/dim]")


@app.command()
def report(
    output: Path = typer.Option(
        Path("report.json"),
        "--output", "-o",
        help="Ausgabedatei für den Report",
    ),
    format: str = typer.Option(
        "json",
        "--format", "-f",
        help="Ausgabeformat (json, csv)",
    ),
    limit: int = typer.Option(
        100,
        "--limit", "-l",
        help="Maximale Anzahl Ergebnisse",
    ),
):
    """Exportiert Scan-Ergebnisse als Report."""
    settings = get_settings()

    async def export_report():
        engine = get_async_engine(settings.database.url)
        SessionFactory = get_async_session_factory(engine)

        async with SessionFactory() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(AnalysisResultDB, URLDB)
                .join(URLDB, AnalysisResultDB.url_id == URLDB.id)
                .order_by(AnalysisResultDB.severity_score.desc())
                .limit(limit)
            )
            rows = result.fetchall()

            data = []
            for analysis, url in rows:
                data.append({
                    "url": str(url.url),
                    "classification": analysis.classification.value,
                    "confidence": analysis.confidence,
                    "severity_score": analysis.severity_score,
                    "flags_count": len(analysis.flags_triggered),
                    "reasoning": analysis.reasoning,
                    "analyzed_at": analysis.analyzed_at.isoformat(),
                })

            return data

    try:
        data = asyncio.run(export_report())

        if format == "json":
            import json
            with open(output, "w") as f:
                json.dump(data, f, indent=2)
        elif format == "csv":
            import csv
            with open(output, "w", newline="") as f:
                if data:
                    writer = csv.DictWriter(f, fieldnames=data[0].keys())
                    writer.writeheader()
                    writer.writerows(data)

        console.print(f"[green]✓[/green] Report exportiert: {output} ({len(data)} Einträge)")

    except Exception as e:
        console.print(f"[red]Fehler beim Export: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def crawl(
    source: str = typer.Option("tranco", "--source", "-s", help="URL-Quelle (tranco)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Anzahl URLs"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Vom letzten Checkpoint fortsetzen"),
):
    """Startet einen Crawl-Durchlauf."""
    settings = get_settings()
    console.print(Panel.fit(
        f"[bold blue]Starte Crawl[/bold blue]",
        subtitle=f"Quelle: {source}, Limit: {limit}",
    ))

    if source == "tranco":
        tranco_path = Path(settings.crawling.tranco_file)
        if not tranco_path.exists():
            console.print(f"[red]Tranco-Liste nicht gefunden: {tranco_path}[/red]")
            console.print("[dim]Lade die Liste von https://tranco-list.eu herunter[/dim]")
            raise typer.Exit(1)

        # URLs aus Tranco laden
        console.print(f"Lade URLs aus {tranco_path}...")

        urls = []
        with open(tranco_path) as f:
            for i, line in enumerate(f):
                if i >= limit:
                    break
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    domain = parts[1]
                    urls.append(f"https://{domain}")

        console.print(f"[green]✓[/green] {len(urls)} URLs geladen")

        # TODO: URLs in Queue einfügen und Worker starten
        console.print("[yellow]Crawl-Worker noch nicht implementiert. URLs vorbereitet.[/yellow]")

        for url in urls[:5]:
            console.print(f"  • {url}")
        if len(urls) > 5:
            console.print(f"  ... und {len(urls) - 5} weitere")


def main():
    """Entry Point für das CLI.

    Wenn ohne Argumente aufgerufen: Interaktive Shell starten.
    Mit Argumenten: Typer CLI verwenden.
    """
    import sys

    # Wenn keine Argumente oder nur --help, interaktive Shell starten
    if len(sys.argv) == 1:
        from .interactive import interactive_shell
        interactive_shell()
    else:
        app()


if __name__ == "__main__":
    main()
