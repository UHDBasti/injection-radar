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

        # Docker Daemon läuft und User hat Zugriff?
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True

            # Prüfe ob es ein Berechtigungsproblem ist
            if "permission denied" in result.stderr.lower() or "connect:" in result.stderr.lower():
                self.docker_permission_error = True
                return False

            return False
        except Exception:
            return False

    def needs_docker_group(self) -> bool:
        """Prüft ob der User zur docker-Gruppe hinzugefügt werden muss."""
        return getattr(self, 'docker_permission_error', False)

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

            # Basis-Services (DB + Redis) reichen für lokalen Scan-Modus
            base_ready = status["db"] and status["redis"]
            return base_ready, status

        except Exception:
            return False, status

    def are_base_services_running(self) -> bool:
        """Prüft ob mindestens DB und Redis laufen."""
        _, status = self.are_containers_running()
        return status["db"] and status["redis"]

    def are_full_services_running(self) -> bool:
        """Prüft ob alle Services (inkl. Orchestrator, Scraper) laufen."""
        _, status = self.are_containers_running()
        return all(status.values())

    def start_containers(self, services: list[str] = None, build: bool = False) -> bool:
        """Startet Docker-Container.

        Args:
            services: Liste der zu startenden Services (default: db, redis)
            build: Wenn True, Images neu bauen
        """
        compose_cmd = self.get_compose_cmd()
        compose_file = DOCKER_DIR / "docker-compose.yml"

        if not compose_file.exists():
            log_error("docker_compose_not_found", path=str(compose_file))
            return False

        # Default: nur Basis-Services (schneller Start)
        if services is None:
            services = ["db", "redis"]

        try:
            # Container starten
            cmd = compose_cmd + ["-f", str(compose_file), "up", "-d"]
            if build:
                cmd.append("--build")
            cmd.extend(services)

            log_info("starting_containers", cmd=" ".join(cmd), services=services)

            # Umgebungsvariablen setzen
            env = os.environ.copy()
            env["DB_PASSWORD"] = env.get("PISHIELD_DB_PASSWORD", "pishield123")

            # API Keys übernehmen
            for key in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"]:
                if key in os.environ:
                    env[key] = os.environ[key]

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

    def start_base_services(self) -> bool:
        """Startet nur DB und Redis (schnell)."""
        return self.start_containers(services=["db", "redis"])

    def start_full_services(self) -> bool:
        """Startet alle Services inkl. Orchestrator und Scraper."""
        return self.start_containers(services=["db", "redis", "orchestrator", "scraper"], build=True)

    def start_all_services(self) -> bool:
        """Startet ALLE Services für Zwei-System-Architektur."""
        # Alle Services gleichzeitig starten (ohne --build für Schnelligkeit)
        return self.start_containers(services=["db", "redis", "orchestrator", "scraper"])

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

    def wait_for_db(self, timeout: int = 30) -> bool:
        """Wartet bis PostgreSQL bereit ist."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                result = subprocess.run(
                    ["docker", "exec", "pishield-db", "pg_isready", "-U", "pishield"],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    log_info("db_ready")
                    return True
            except Exception:
                pass

            time.sleep(1)

        log_error("db_not_ready", timeout=timeout)
        return False

    def wait_for_redis(self, timeout: int = 10) -> bool:
        """Wartet bis Redis bereit ist."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                result = subprocess.run(
                    ["docker", "exec", "pishield-redis", "redis-cli", "ping"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and "PONG" in result.stdout:
                    log_info("redis_ready")
                    return True
            except Exception:
                pass

            time.sleep(1)

        log_error("redis_not_ready", timeout=timeout)
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

    # Lade .env Datei
    manager.setup_environment()

    # Prüfe Docker
    console.print("[dim]Prüfe System...[/dim]")

    if not manager.check_docker():
        if manager.needs_docker_group():
            console.print("[yellow]Docker installiert, aber keine Berechtigung.[/yellow]")
            console.print("[dim]Lösung: Neu anmelden ODER CLI so starten:[/dim]")
            console.print("[cyan]  sg docker -c 'injection-radar'[/cyan]")
            console.print("[dim]Nutze vorerst lokalen Modus...[/dim]")
        else:
            console.print("[yellow]Docker nicht verfügbar - nutze lokalen Modus[/yellow]")
        log_warning("docker_not_available")
        return False, True

    if not manager.check_docker_compose():
        console.print("[yellow]Docker Compose nicht verfügbar - nutze lokalen Modus[/yellow]")
        log_warning("docker_compose_not_available")
        return False, True

    # Prüfe ob ALLE Services laufen (inkl. Orchestrator)
    base_ready, status = manager.are_containers_running()
    all_running = all(status.values())

    if all_running:
        console.print("[green]✓[/green] Alle Services laufen bereits")
        return True, False

    # Zeige was fehlt
    missing = [k for k, v in status.items() if not v]
    if missing:
        console.print(f"[dim]Fehlende Services: {', '.join(missing)}[/dim]")

    # ALLE Services starten
    console.print("[dim]Starte Backend-Services...[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        # Container starten
        task = progress.add_task("Starte alle Services...", total=None)

        if not manager.start_all_services():
            console.print("[yellow]Container-Start fehlgeschlagen - nutze lokalen Modus[/yellow]")
            return False, True

        # Auf DB warten
        progress.update(task, description="Warte auf PostgreSQL...")

        if not manager.wait_for_db(timeout=30):
            console.print("[yellow]Datenbank nicht bereit - nutze lokalen Modus[/yellow]")
            return False, True

        progress.update(task, description="Warte auf Redis...")

        if not manager.wait_for_redis(timeout=10):
            console.print("[yellow]Redis nicht bereit - nutze lokalen Modus[/yellow]")
            return False, True

        # Auf Orchestrator API warten
        progress.update(task, description="Warte auf Orchestrator...")

        if not manager.wait_for_services(timeout=30):
            console.print("[yellow]Orchestrator nicht bereit - nutze lokalen Modus[/yellow]")
            return False, True

    console.print("[green]✓[/green] Alle Services bereit (Zwei-System-Architektur)")
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
