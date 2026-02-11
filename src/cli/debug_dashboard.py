"""
Debug Dashboard für InjectionRadar.

Zeigt in Echtzeit was die Worker machen:
- Job Status (queued → scraping → saved → analyzing → done/failed)
- Docker Scraper Logs (live tailing)
- System Health (API, Queue, Workers)

Aktivierung:
- scan <url> --debug
- debug on / debug off (globaler Toggle)
"""

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import httpx
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..core.startup import StartupManager, DOCKER_DIR


class JobState(str, Enum):
    """State Machine für einen Scan-Job."""
    QUEUED = "queued"
    SCRAPING = "scraping"
    SAVED = "saved"
    ANALYZING = "analyzing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class StepEntry:
    """Ein Schritt im Job-Ablauf."""
    label: str
    state: str  # "ok", "running", "failed"
    detail: str = ""
    elapsed: float = 0.0


@dataclass
class JobTracker:
    """Trackt den Fortschritt eines einzelnen Jobs."""
    job_id: str
    url: str
    state: JobState = JobState.QUEUED
    steps: list[StepEntry] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    result: Optional[dict] = None
    error: Optional[str] = None

    def __post_init__(self):
        self.steps.append(StepEntry(
            label="Job in Queue",
            state="ok",
            elapsed=0.0,
        ))

    def add_step(self, label: str, state: str = "ok", detail: str = ""):
        elapsed = time.time() - self.start_time
        self.steps.append(StepEntry(
            label=label,
            state=state,
            detail=detail,
            elapsed=elapsed,
        ))

    def update_running_step(self, label: str, detail: str = ""):
        """Setzt den aktuellen laufenden Schritt."""
        # Vorigen running-Step auf ok setzen
        for step in self.steps:
            if step.state == "running":
                step.state = "ok"
        self.add_step(label, state="running", detail=detail)

    def finish(self, classification: str = "", severity: float = 0.0):
        """Markiert den Job als fertig."""
        for step in self.steps:
            if step.state == "running":
                step.state = "ok"
        self.state = JobState.DONE
        self.add_step(
            f"Fertig: {classification} (severity: {severity:.1f})",
            state="ok",
        )

    def fail(self, error: str):
        """Markiert den Job als fehlgeschlagen."""
        for step in self.steps:
            if step.state == "running":
                step.state = "failed"
        self.state = JobState.FAILED
        self.error = error
        self.add_step(f"Fehler: {error[:60]}", state="failed")


class DebugDashboard:
    """Live Debug Dashboard für die CLI."""

    def __init__(self, config: dict, console: Console):
        self.config = config
        self.console = console
        self.api_url = config.get("orchestrator_url", "http://localhost:8000")
        self.jobs: dict[str, JobTracker] = {}
        self.log_lines: list[str] = []
        self.max_log_lines = 15
        self.system_status = {"status": "unknown", "queue": 0, "workers": "?"}
        self._running = False
        self._log_process: Optional[subprocess.Popen] = None

    async def run(self, urls: list[str]):
        """Hauptmethode: Jobs submitten, Dashboard anzeigen bis alle fertig."""
        self._running = True

        # Jobs async submitten
        job_ids = await self._submit_jobs(urls)

        if not job_ids:
            self.console.print("[red]Keine Jobs konnten gestartet werden.[/red]")
            return

        # Live Dashboard starten
        with Live(
            self._render(),
            console=self.console,
            refresh_per_second=2,
            screen=False,
        ) as live:
            # Parallele Tasks: Polling + Log Tailing + System Status
            tasks = [
                asyncio.create_task(self._poll_jobs(live)),
                asyncio.create_task(self._tail_docker_logs(live)),
                asyncio.create_task(self._poll_system(live)),
            ]

            try:
                # Warte bis alle Jobs fertig sind
                while self._running:
                    all_done = all(
                        j.state in (JobState.DONE, JobState.FAILED)
                        for j in self.jobs.values()
                    )
                    if all_done:
                        # Noch kurz anzeigen
                        live.update(self._render())
                        await asyncio.sleep(1)
                        break
                    await asyncio.sleep(0.3)

            except asyncio.CancelledError:
                pass
            finally:
                self._running = False
                for task in tasks:
                    task.cancel()
                # Auf Tasks warten (Fehler ignorieren)
                await asyncio.gather(*tasks, return_exceptions=True)
                self._stop_log_tailing()

        # Endergebnis anzeigen
        self._show_final_results()

    async def _submit_jobs(self, urls: list[str]) -> list[str]:
        """Sendet Jobs via /scan/async und gibt Job-IDs zurueck."""
        job_ids = []

        async with httpx.AsyncClient(timeout=10) as client:
            for url in urls:
                try:
                    response = await client.post(
                        f"{self.api_url}/scan/async",
                        json={"url": url, "task": "summarize"},
                    )
                    if response.status_code == 200:
                        data = response.json()
                        job_id = data["job_id"]
                        job_ids.append(job_id)

                        tracker = JobTracker(job_id=job_id, url=url)
                        self.jobs[job_id] = tracker

                        self._add_log(f"Job {job_id[:8]} gestartet: {url}")
                    else:
                        self._add_log(f"[red]Fehler beim Starten: {url} ({response.status_code})[/red]")
                except Exception as e:
                    self._add_log(f"[red]Verbindungsfehler: {url} - {e}[/red]")

        return job_ids

    async def _poll_jobs(self, live: Live):
        """Pollt Job-Status alle 1 Sekunde."""
        while self._running:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    for job_id, tracker in self.jobs.items():
                        if tracker.state in (JobState.DONE, JobState.FAILED):
                            continue

                        try:
                            response = await client.get(
                                f"{self.api_url}/scan/{job_id}/status"
                            )
                            if response.status_code == 200:
                                data = response.json()
                                self._update_tracker_from_status(tracker, data)
                        except Exception:
                            pass

                live.update(self._render())
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1)

    def _update_tracker_from_status(self, tracker: JobTracker, data: dict):
        """Aktualisiert einen JobTracker basierend auf API-Status."""
        status = data.get("status", "pending")
        result = data.get("result")

        if status == "pending":
            # Job laeuft noch - schaue ob wir aus Logs schon mehr wissen
            if tracker.state == JobState.QUEUED:
                # Nichts zu tun, warten
                pass
        elif status in ("completed", "failed"):
            if result:
                tracker.result = result
                classification = result.get("classification", "unknown")
                severity = result.get("severity_score", 0) or 0

                if status == "completed":
                    tracker.finish(classification, severity)
                    self._add_log(
                        f"Job {tracker.job_id[:8]} fertig: "
                        f"{classification} (severity: {severity:.1f})"
                    )
                else:
                    error = result.get("error_message", "Unknown error")
                    tracker.fail(error)
                    self._add_log(f"[red]Job {tracker.job_id[:8]} fehlgeschlagen: {error}[/red]")
            elif status == "failed":
                tracker.fail("Job failed without result")

    async def _tail_docker_logs(self, live: Live):
        """Tailt Docker Scraper Logs im Hintergrund."""
        try:
            manager = StartupManager()
            compose_cmd = manager.get_compose_cmd()
            compose_file = DOCKER_DIR / "docker-compose.yml"

            cmd = compose_cmd + [
                "-f", str(compose_file),
                "logs", "-f", "--tail=0", "--no-log-prefix",
                "scraper",
            ]

            self._log_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(DOCKER_DIR),
            )

            loop = asyncio.get_event_loop()

            while self._running and self._log_process.poll() is None:
                try:
                    # Non-blocking readline via executor
                    line = await asyncio.wait_for(
                        loop.run_in_executor(None, self._log_process.stdout.readline),
                        timeout=1.0,
                    )
                    if line:
                        line = line.strip()
                        if line:
                            self._parse_log_line(line)
                            live.update(self._render())
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._add_log(f"[dim]Log-Tailing nicht verfuegbar: {e}[/dim]")

    def _stop_log_tailing(self):
        """Stoppt den Log-Tailing Prozess."""
        if self._log_process and self._log_process.poll() is None:
            try:
                self._log_process.terminate()
                self._log_process.wait(timeout=3)
            except Exception:
                try:
                    self._log_process.kill()
                except Exception:
                    pass

    def _parse_log_line(self, line: str):
        """Parst eine Log-Zeile und aktualisiert Job-Tracker."""
        # Versuche JSON zu parsen (structlog)
        try:
            entry = json.loads(line)
            event = entry.get("event", "")
            job_id = entry.get("job_id", "")

            # Finde passenden Tracker
            tracker = self.jobs.get(job_id)

            if event == "job_processing" and tracker:
                tracker.state = JobState.SCRAPING
                tracker.update_running_step("Scrape laeuft...")
                self._add_log(f"Scraper verarbeitet {tracker.url}")

            elif event == "website_scraped" and tracker:
                word_count = entry.get("word_count", 0)
                tracker.add_step(f"Website gescraped ({word_count:,} Woerter)")
                self._add_log(f"Gescraped: {word_count:,} Woerter von {tracker.url}")

            elif event == "scraped_content_saved" and tracker:
                tracker.state = JobState.SAVED
                tracker.add_step("In DB gespeichert")

            elif event == "llm_test_completed" and tracker:
                flags = entry.get("flags_count", 0)
                tracker.state = JobState.ANALYZING
                tracker.add_step(f"LLM-Analyse abgeschlossen ({flags} Flags)")
                self._add_log(f"LLM fertig: {flags} Flags fuer {tracker.url}")

            elif event == "job_completed" and tracker:
                severity = entry.get("severity", 0)
                classification = entry.get("classification", "unknown")
                tracker.finish(classification, severity)
                self._add_log(f"Job fertig: {classification} ({severity:.1f})")

            elif event == "job_failed" and tracker:
                error = entry.get("error_message", "unknown")
                tracker.fail(error)
                self._add_log(f"[red]Job fehlgeschlagen: {error}[/red]")

            else:
                # Allgemeine Log-Zeile
                timestamp = entry.get("timestamp", "")[:19]
                self._add_log(f"[dim]{timestamp} {event}[/dim]")

        except json.JSONDecodeError:
            # Kein JSON - zeige Zeile direkt
            if line and not line.startswith("Attaching"):
                self._add_log(f"[dim]{line[:120]}[/dim]")

    async def _poll_system(self, live: Live):
        """Pollt System-Status (Health, Queue)."""
        while self._running:
            try:
                async with httpx.AsyncClient(timeout=3) as client:
                    # Health Check
                    try:
                        resp = await client.get(f"{self.api_url}/health")
                        if resp.status_code == 200:
                            data = resp.json()
                            self.system_status["status"] = data.get("status", "unknown")
                    except Exception:
                        self.system_status["status"] = "offline"

                    # Queue Stats
                    try:
                        resp = await client.get(f"{self.api_url}/queue/stats")
                        if resp.status_code == 200:
                            data = resp.json()
                            self.system_status["queue"] = data.get("queue_length", 0)
                    except Exception:
                        pass

                live.update(self._render())
                await asyncio.sleep(3)

            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(3)

    def _add_log(self, message: str):
        """Fuegt eine Log-Zeile hinzu."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_lines.append(f"{timestamp} {message}")
        # Begrenzen
        if len(self.log_lines) > self.max_log_lines:
            self.log_lines = self.log_lines[-self.max_log_lines:]

    def _render(self) -> Panel:
        """Rendert das komplette Dashboard."""
        # Header
        elapsed = 0
        if self.jobs:
            earliest = min(j.start_time for j in self.jobs.values())
            elapsed = time.time() - earliest

        total = len(self.jobs)
        done = sum(1 for j in self.jobs.values() if j.state == JobState.DONE)
        failed = sum(1 for j in self.jobs.values() if j.state == JobState.FAILED)
        running = total - done - failed

        # System Bar
        status_color = {
            "healthy": "green",
            "degraded": "yellow",
            "offline": "red",
        }.get(self.system_status["status"], "dim")

        header = Text()
        header.append("System: ", style="bold")
        header.append(
            self.system_status["status"],
            style=status_color,
        )
        header.append(f" | Queue: {self.system_status['queue']}")
        header.append(f" | Jobs: {done}/{total} fertig")
        if failed:
            header.append(f" | {failed} fehlgeschlagen", style="red")
        header.append(f" | Elapsed: {elapsed:.0f}s", style="dim")

        # Jobs Section
        jobs_table = Table(
            show_header=False,
            box=None,
            padding=(0, 1),
            expand=True,
        )
        jobs_table.add_column("Content", ratio=1)

        for tracker in self.jobs.values():
            # URL Header
            short_id = tracker.job_id[:8]
            url_display = tracker.url
            if len(url_display) > 50:
                url_display = url_display[:47] + "..."

            state_icon = {
                JobState.QUEUED: "[dim]...[/dim]",
                JobState.SCRAPING: "[yellow]>>>[/yellow]",
                JobState.SAVED: "[blue]>>>[/blue]",
                JobState.ANALYZING: "[cyan]>>>[/cyan]",
                JobState.DONE: "[green]OK[/green]",
                JobState.FAILED: "[red]XX[/red]",
            }.get(tracker.state, "?")

            jobs_table.add_row(
                f"\n  {state_icon} [bold]{url_display}[/bold]  [dim][{short_id}][/dim]"
            )

            # Steps
            for step in tracker.steps:
                icon = {
                    "ok": "[green][OK][/green]",
                    "running": "[yellow][..][/yellow]",
                    "failed": "[red][XX][/red]",
                }.get(step.state, "[dim][??][/dim]")

                elapsed_str = f"+{step.elapsed:.1f}s" if step.elapsed > 0 else ""
                detail = f" ({step.detail})" if step.detail else ""

                jobs_table.add_row(
                    f"      {icon} {step.label}{detail}  [dim]{elapsed_str}[/dim]"
                )

        # Logs Section
        logs_text = Text()
        if self.log_lines:
            for line in self.log_lines[-10:]:
                logs_text.append(line + "\n")
        else:
            logs_text.append("Warte auf Logs...\n", style="dim")

        # Combine
        content = Text()
        content.append("\n")

        # Build final panel content as string for Rich markup
        parts = []
        parts.append(str(header))

        # Separator
        parts.append("\n" + "-" * 60 + "\n")

        # Wir nutzen ein Table fuer die Darstellung
        combined_table = Table(
            show_header=False,
            box=None,
            expand=True,
            padding=0,
        )
        combined_table.add_column("Main", ratio=1)

        # System bar row
        combined_table.add_row(header)
        combined_table.add_row("")

        # Jobs
        combined_table.add_row(jobs_table)
        combined_table.add_row("")

        # Logs header
        combined_table.add_row(Text("Scraper-Logs (live)", style="bold dim"))
        combined_table.add_row(logs_text)

        title = f"DEBUG DASHBOARD  |  {running} aktiv  {done} fertig  {failed} fehler"
        return Panel(
            combined_table,
            title=f"[bold cyan]{title}[/bold cyan]",
            subtitle=f"[dim]Elapsed: {elapsed:.0f}s[/dim]",
            border_style="cyan",
            expand=True,
        )

    def _show_final_results(self):
        """Zeigt die finalen Ergebnisse nach dem Dashboard."""
        self.console.print()

        # Ergebnis-Tabelle
        table = Table(show_header=True, header_style="bold", title="Scan-Ergebnisse")
        table.add_column("URL", max_width=40)
        table.add_column("Status", width=12)
        table.add_column("Severity", justify="right", width=8)
        table.add_column("Flags", justify="right", width=6)
        table.add_column("Zeit", justify="right", width=8)

        status_colors = {
            "safe": "green",
            "suspicious": "yellow",
            "dangerous": "red",
        }

        for tracker in self.jobs.values():
            url = tracker.url
            if len(url) > 38:
                url = url[:35] + "..."

            elapsed = time.time() - tracker.start_time

            if tracker.state == JobState.DONE and tracker.result:
                result = tracker.result
                classification = result.get("classification", "unknown")
                color = status_colors.get(classification, "white")
                severity = result.get("severity_score", 0) or 0
                flags_list = result.get("flags") or []

                table.add_row(
                    url,
                    f"[{color}]{classification}[/{color}]",
                    f"{severity:.1f}",
                    str(len(flags_list)),
                    f"{elapsed:.1f}s",
                )
            elif tracker.state == JobState.FAILED:
                error = (tracker.error or "Unknown")[:30]
                table.add_row(
                    url,
                    "[red]failed[/red]",
                    "-",
                    "-",
                    f"{elapsed:.1f}s",
                )
            else:
                table.add_row(
                    url,
                    "[dim]timeout[/dim]",
                    "-",
                    "-",
                    f"{elapsed:.1f}s",
                )

        self.console.print(table)

        # Zusammenfassung
        total = len(self.jobs)
        done = sum(1 for j in self.jobs.values() if j.state == JobState.DONE)
        failed = sum(1 for j in self.jobs.values() if j.state == JobState.FAILED)

        self.console.print(f"\n[bold]{done}/{total} erfolgreich[/bold]", end="")
        if failed:
            self.console.print(f", [red]{failed} fehlgeschlagen[/red]")
        else:
            self.console.print()

        # Gefaehrliche URLs hervorheben
        dangerous = [
            t for t in self.jobs.values()
            if t.result and t.result.get("classification") == "dangerous"
        ]
        if dangerous:
            self.console.print(f"\n[bold red]Gefaehrliche URLs:[/bold red]")
            for t in dangerous:
                self.console.print(f"  [red]>[/red] {t.url}")

        self.console.print()
