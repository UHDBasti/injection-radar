"""
Logging-Konfiguration für InjectionRadar.

Speichert alle Logs in ~/.injection-radar/logs/
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

# Log-Verzeichnis (mit Fallback für read-only Container)
def _get_log_dir() -> Path:
    """Ermittelt das Log-Verzeichnis mit Fallback."""
    primary = Path.home() / ".injection-radar" / "logs"
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except (OSError, PermissionError):
        # Fallback für read-only Container: /tmp
        fallback = Path("/tmp/injection-radar-logs")
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except (OSError, PermissionError):
            # Letzter Fallback: kein File-Logging
            return None

LOG_DIR = _get_log_dir()

# Aktuelles Log-File (nach Datum)
CURRENT_LOG = (LOG_DIR / f"injection-radar-{datetime.now().strftime('%Y-%m-%d')}.log") if LOG_DIR else None


def setup_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
    verbose: bool = False,
) -> structlog.BoundLogger:
    """Konfiguriert das Logging-System.

    Args:
        level: Log-Level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optionaler Pfad zur Log-Datei
        verbose: Wenn True, auch auf Console ausgeben

    Returns:
        Konfigurierter Logger
    """
    log_file = log_file or CURRENT_LOG

    # Handler konfigurieren
    handlers = []
    if log_file:
        try:
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        except (OSError, PermissionError):
            pass  # Kein File-Logging möglich
    if verbose:
        handlers.append(logging.StreamHandler(sys.stderr))
    if not handlers:
        handlers.append(logging.NullHandler())

    # Standard Python Logging konfigurieren
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=getattr(logging, level.upper()),
        handlers=handlers,
    )

    # Third-Party Logger auf WARNING setzen (weniger Noise)
    for noisy_logger in [
        "httpx",
        "httpcore",
        "anthropic",
        "openai",
        "urllib3",
        "asyncio",
        "markdown_it",
        "playwright",
    ]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # Structlog konfigurieren
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger("injection-radar")


def get_logger(name: str = "injection-radar") -> structlog.BoundLogger:
    """Gibt einen Logger zurück."""
    return structlog.get_logger(name)


# Einfache Log-Funktionen für schnellen Zugriff
_logger: Optional[structlog.BoundLogger] = None


def _get_logger():
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger


def log_info(message: str, **kwargs):
    """Loggt eine Info-Nachricht."""
    _get_logger().info(message, **kwargs)


def log_warning(message: str, **kwargs):
    """Loggt eine Warnung."""
    _get_logger().warning(message, **kwargs)


def log_error(message: str, **kwargs):
    """Loggt einen Fehler."""
    _get_logger().error(message, **kwargs)


def log_debug(message: str, **kwargs):
    """Loggt eine Debug-Nachricht."""
    _get_logger().debug(message, **kwargs)


def log_scan(url: str, result: dict):
    """Loggt einen Scan-Vorgang."""
    _get_logger().info(
        "scan_completed",
        url=url,
        severity_score=result.get("severity_score"),
        flags_count=result.get("flags_count"),
        classification=result.get("classification"),
        flags=result.get("flags", []),
    )


def log_llm_call(provider: str, model: str, tokens_in: int, tokens_out: int, cost: float):
    """Loggt einen LLM-Aufruf."""
    _get_logger().info(
        "llm_call",
        provider=provider,
        model=model,
        tokens_input=tokens_in,
        tokens_output=tokens_out,
        cost_usd=cost,
    )


def log_error_with_trace(message: str, error: Exception):
    """Loggt einen Fehler mit Stack-Trace."""
    import traceback
    _get_logger().error(
        message,
        error_type=type(error).__name__,
        error_message=str(error),
        traceback=traceback.format_exc(),
    )


def get_recent_logs(lines: int = 100) -> list[str]:
    """Gibt die letzten Log-Zeilen zurück."""
    if not CURRENT_LOG or not CURRENT_LOG.exists():
        return []

    with open(CURRENT_LOG) as f:
        all_lines = f.readlines()
        return all_lines[-lines:]


def get_log_files() -> list[Path]:
    """Gibt alle Log-Dateien zurück."""
    if not LOG_DIR:
        return []
    return sorted(LOG_DIR.glob("*.log"), reverse=True)
