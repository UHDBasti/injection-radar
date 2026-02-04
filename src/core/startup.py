"""
Automatischer Startup-Manager für InjectionRadar.

Startet alle benötigten Services (Docker-Container) automatisch,
wenn der User `injection-radar` eingibt.
"""

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .logging import log_info, log_error, log_warning

console = Console()

# Projekt-Root (wo docker-compose.yml liegt)
PROJECT_ROOT = Path(__file__).parent.parent.parent
DOCKER_DIR = PROJECT_ROOT / "docker"


class StartupManager:
    """Verwaltet den automatischen Start aller Services."""

    def __init__(self):
        self.docker_available = False
        self.containers_started = False
        self.use_local_mode = False

    def check_docker(self) -> bool:
        """Prüft ob Docker installiert und verfügbar ist."""
        # Docker CLI vorhanden?
        if not shutil.which("docker"):
            return False

        # Docker Daemon läuft?
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def check_docker_compose(self) -> bool:
        """Prüft ob docker-compose verfügbar ist."""
        # Versuche docker compose (neuer) und docker-compose (alt)
        for cmd in [["docker", "compose", "version"], ["docker-compose", "version"]]:
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=5)
                if result.returncode == 0:
                    return True
            except Exception:
                continue
        return False

    def get_compose_cmd(self) -> list[str]:
        """Gibt den korrekten docker-compose Befehl zurück."""
        # Versuche docker compose (neuer)
        try:
            result = subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return ["docker", "compose"]
        except Exception:
            pass

        # Fallback auf docker-compose
        return ["docker-compose"]

    def are_containers_running(self) -> Tuple[bool, dict]:
        """Prüft welche Container laufen."""
        status = {
            "db": False,
            "redis": False,
            "orchestrator": False,
            "scraper": False,
        }

        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return False, status

            running = result.stdout.strip().split("\n")

            for name in running:
                if "pishield-db" in name or "injectionradar-db" in name:
                    status["db"] = True
                elif "pishield-redis" in name or "injectionradar-redis" in name:
                    status["redis"] = True
                elif "pishield-orchestrator" in name or "orchestrator" in name:
                    status["orchestrator"] = True
                elif "scraper" in name:
                    status["scraper"] = True

            all_running = all(status.values())
            return all_running, status

        except Exception:
            return False, status

    def start_containers(self, progress_callback=None) -> bool:
        """Startet alle Docker-Container."""
        compose_cmd = self.get_compose_cmd()
        compose_file = DOCKER_DIR / "docker-compose.yml"

        if not compose_file.exists():
            log_error("docker_compose_not_found", path=str(compose_file))
            return False

        try:
            # Container starten
            cmd = compose_cmd + [
                "-f", str(compose_file),
                "up", "-d",
                "--build",  # Bei Bedarf neu bauen
            ]

            log_info("starting_containers", cmd=" ".join(cmd))

            # Umgebungsvariablen setzen
            env = os.environ.copy()
            env["DB_PASSWORD"] = env.get("PISHIELD_DB_PASSWORD", "pishield123")

            result = subprocess.run(
                cmd,
                cwd=str(DOCKER_DIR),
                capture_output=True,
                text=True,
                timeout=300,  # 5 Minuten Timeout für Build
                env=env,
            )

            if result.returncode != 0:
                log_error("container_start_failed", stderr=result.stderr)
                return False

            self.containers_started = True
            return True

        except subprocess.TimeoutExpired:
            log_error("container_start_timeout")
            return False
        except Exception as e:
            log_error("container_start_error", error=str(e))
            return False

    def wait_for_services(self, timeout: int = 60) -> bool:
        """Wartet bis alle Services bereit sind."""
        import httpx

        start_time = time.time()
        api_url = "http://localhost:8000/health"

        while time.time() - start_time < timeout:
            try:
                # Prüfe API Health
                response = httpx.get(api_url, timeout=2)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") in ["healthy", "degraded"]:
                        log_info("services_ready")
                        return True
            except Exception:
                pass

            time.sleep(1)

        log_error("services_not_ready", timeout=timeout)
        return False

    def stop_containers(self) -> bool:
        """Stoppt alle Docker-Container."""
        compose_cmd = self.get_compose_cmd()
        compose_file = DOCKER_DIR / "docker-compose.yml"

        try:
            cmd = compose_cmd + ["-f", str(compose_file), "down"]

            result = subprocess.run(
                cmd,
                cwd=str(DOCKER_DIR),
                capture_output=True,
                text=True,
                timeout=60,
            )

            return result.returncode == 0

        except Exception:
            return False

    def setup_environment(self) -> dict:
        """Richtet die Umgebungsvariablen ein."""
        env = {}

        # API Keys aus .env oder Umgebung
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        if value and value not in ["", '""', "''"]:
                            os.environ[key] = value
                            env[key] = value

        return env


def auto_start_services(console: Console) -> Tuple[bool, bool]:
    """Startet automatisch alle benötigten Services.

    Returns:
        Tuple[bool, bool]: (services_ready, use_local_mode)
    """
    manager = StartupManager()

    # Prüfe Docker
    console.print("[dim]Prüfe System...[/dim]")

    if not manager.check_docker():
        console.print("[yellow]Docker nicht verfügbar - nutze lokalen Modus[/yellow]")
        log_warning("docker_not_available")
        return False, True

    if not manager.check_docker_compose():
        console.print("[yellow]Docker Compose nicht verfügbar - nutze lokalen Modus[/yellow]")
        log_warning("docker_compose_not_available")
        return False, True

    # Prüfe ob Container bereits laufen
    all_running, status = manager.are_containers_running()

    if all_running:
        console.print("[green]✓[/green] Services laufen bereits")
        return True, False

    # Einige Container fehlen - starte alles
    console.print("[dim]Starte Backend-Services...[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        # Container starten
        task = progress.add_task("Starte Container...", total=None)

        if not manager.start_containers():
            console.print("[yellow]Container-Start fehlgeschlagen - nutze lokalen Modus[/yellow]")
            return False, True

        # Auf Services warten
        progress.update(task, description="Warte auf Services...")

        if not manager.wait_for_services(timeout=90):
            console.print("[yellow]Services nicht bereit - nutze lokalen Modus[/yellow]")
            return False, True

    console.print("[green]✓[/green] Backend-Services bereit")
    return True, False


def ensure_local_requirements() -> bool:
    """Stellt sicher dass lokaler Modus funktioniert."""
    # SQLite Datenbank-Verzeichnis erstellen
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(exist_ok=True)

    return True


def get_startup_mode(config: dict) -> str:
    """Bestimmt den Startup-Modus basierend auf Konfiguration."""
    # Explizit lokaler Modus?
    if config.get("use_local_mode"):
        return "local"

    # Docker verfügbar?
    manager = StartupManager()
    if manager.check_docker() and manager.check_docker_compose():
        return "docker"

    return "local"
