"""
Redis-basierte Job Queue für die Zwei-System-Architektur.

Ermöglicht sichere Kommunikation zwischen Orchestrator und Scraper-Subsystem:
- Orchestrator sendet Jobs in die Queue
- Scraper holt Jobs und verarbeitet sie
- Ergebnisse werden via Redis zurückgegeben (nur ScanResult, keine Rohdaten!)
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, asdict

import redis.asyncio as redis
from pydantic import BaseModel

from .logging import log_info, log_error, log_debug


# ============================================================================
# Job Models
# ============================================================================

class ScanJob(BaseModel):
    """Ein Scan-Job für die Queue."""
    job_id: str
    url: str
    task_name: str = "summarize"
    priority: int = 5  # 1-10, höher = wichtiger
    lang: str = "de"
    created_at: str = ""

    def __init__(self, **data):
        if not data.get("job_id"):
            data["job_id"] = str(uuid.uuid4())
        if not data.get("created_at"):
            data["created_at"] = datetime.now(timezone.utc).isoformat()
        super().__init__(**data)


class JobResult(BaseModel):
    """Ergebnis eines Scan-Jobs (nur strukturierte Daten!)."""
    job_id: str
    url: str
    status: str  # "completed", "failed", "timeout"

    # Nur strukturierte Daten - KEINE Rohdaten!
    severity_score: float = 0.0
    flags_count: int = 0
    classification: str = "pending"
    flags: list[dict] = []
    llm_summary: Optional[str] = None  # LLM output text (for display to users)

    # Metadaten
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_estimated: float = 0.0

    # Timing
    processing_time_ms: int = 0
    completed_at: str = ""

    # Fehler (falls status="failed")
    error_message: Optional[str] = None


# ============================================================================
# Queue Configuration
# ============================================================================

@dataclass
class QueueConfig:
    """Konfiguration für die Redis Queue."""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None

    # Queue Names
    jobs_queue: str = "injection_radar:jobs"
    results_prefix: str = "injection_radar:result:"

    # Timeouts
    job_timeout_seconds: int = 120  # Max Zeit für einen Job
    result_ttl_seconds: int = 3600  # Ergebnisse 1h aufbewahren

    @property
    def redis_url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


# ============================================================================
# Job Queue
# ============================================================================

class JobQueue:
    """Redis-basierte Job Queue für Scraper-Orchestrator Kommunikation."""

    def __init__(self, config: Optional[QueueConfig] = None):
        self.config = config or QueueConfig()
        self._redis: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Verbindet mit Redis."""
        if self._redis is None:
            self._redis = redis.from_url(
                self.config.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await self._redis.ping()
            log_info("redis_connected", host=self.config.host, port=self.config.port)

    async def disconnect(self) -> None:
        """Trennt die Redis-Verbindung."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            log_debug("redis_disconnected")

    async def _ensure_connected(self) -> redis.Redis:
        """Stellt sicher dass eine Verbindung besteht."""
        if self._redis is None:
            await self.connect()
        return self._redis

    # -------------------------------------------------------------------------
    # Orchestrator-Seite: Jobs einstellen und Ergebnisse abholen
    # -------------------------------------------------------------------------

    async def enqueue_scan(self, url: str, task_name: str = "summarize", priority: int = 5, lang: str = "de") -> ScanJob:
        """Fügt einen Scan-Job in die Queue ein.

        Args:
            url: Die zu scannende URL
            task_name: Art des Tests (summarize, extract, etc.)
            priority: Priorität 1-10 (höher = wichtiger)
            lang: Sprache für LLM-Prompts ("de" oder "en")

        Returns:
            ScanJob mit generierter job_id
        """
        r = await self._ensure_connected()

        job = ScanJob(url=url, task_name=task_name, priority=priority, lang=lang)
        job_json = job.model_dump_json()

        # In Queue einfügen (LPUSH für FIFO mit BRPOP)
        await r.lpush(self.config.jobs_queue, job_json)

        log_info("job_enqueued", job_id=job.job_id, url=url, task=task_name)
        return job

    async def get_result(
        self,
        job_id: str,
        timeout_seconds: Optional[int] = None
    ) -> Optional[JobResult]:
        """Wartet auf das Ergebnis eines Jobs.

        Args:
            job_id: Die Job-ID
            timeout_seconds: Max Wartezeit (None = config default)

        Returns:
            JobResult oder None bei Timeout
        """
        r = await self._ensure_connected()
        timeout = timeout_seconds or self.config.job_timeout_seconds

        result_key = f"{self.config.results_prefix}{job_id}"

        # Polling mit Timeout (BLPOP wäre besser, aber wir brauchen GET)
        import asyncio
        start_time = asyncio.get_event_loop().time()

        while True:
            result_json = await r.get(result_key)

            if result_json:
                log_debug("job_result_received", job_id=job_id)
                return JobResult.model_validate_json(result_json)

            # Timeout check
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                log_error("job_timeout", job_id=job_id, timeout=timeout)
                return None

            # Short sleep before next poll
            await asyncio.sleep(0.5)

    async def get_result_nowait(self, job_id: str) -> Optional[JobResult]:
        """Holt Ergebnis ohne zu warten (für Polling-API)."""
        r = await self._ensure_connected()
        result_key = f"{self.config.results_prefix}{job_id}"

        result_json = await r.get(result_key)
        if result_json:
            return JobResult.model_validate_json(result_json)
        return None

    # -------------------------------------------------------------------------
    # Scraper-Seite: Jobs abholen und Ergebnisse zurücksenden
    # -------------------------------------------------------------------------

    async def dequeue_scan(self, timeout_seconds: int = 0) -> Optional[ScanJob]:
        """Holt den nächsten Job aus der Queue (blocking).

        Args:
            timeout_seconds: 0 = unendlich warten

        Returns:
            ScanJob oder None bei Timeout
        """
        r = await self._ensure_connected()

        # BRPOP wartet bis ein Element verfügbar ist
        result = await r.brpop(self.config.jobs_queue, timeout=timeout_seconds)

        if result is None:
            return None

        _, job_json = result
        job = ScanJob.model_validate_json(job_json)

        log_info("job_dequeued", job_id=job.job_id, url=job.url)
        return job

    async def set_result(self, result: JobResult) -> None:
        """Speichert das Ergebnis eines Jobs.

        WICHTIG: Enthält NUR strukturierte Daten, keine Rohdaten!

        Args:
            result: Das JobResult mit strukturierten Daten
        """
        r = await self._ensure_connected()

        result_key = f"{self.config.results_prefix}{result.job_id}"
        result_json = result.model_dump_json()

        # Speichern mit TTL
        await r.setex(result_key, self.config.result_ttl_seconds, result_json)

        log_info(
            "job_result_stored",
            job_id=result.job_id,
            status=result.status,
            severity=result.severity_score,
        )

    # -------------------------------------------------------------------------
    # Utility
    # -------------------------------------------------------------------------

    async def get_queue_length(self) -> int:
        """Gibt die aktuelle Queue-Länge zurück."""
        r = await self._ensure_connected()
        return await r.llen(self.config.jobs_queue)

    async def clear_queue(self) -> int:
        """Leert die Queue (nur für Tests!)."""
        r = await self._ensure_connected()
        length = await r.llen(self.config.jobs_queue)
        await r.delete(self.config.jobs_queue)
        log_info("queue_cleared", removed_jobs=length)
        return length


# ============================================================================
# Convenience Functions
# ============================================================================

_default_queue: Optional[JobQueue] = None


def get_queue(config: Optional[QueueConfig] = None) -> JobQueue:
    """Gibt die Standard-Queue zurück (Singleton)."""
    global _default_queue
    if _default_queue is None:
        _default_queue = JobQueue(config)
    return _default_queue


async def enqueue_scan(url: str, task_name: str = "summarize", lang: str = "de") -> ScanJob:
    """Shortcut zum Einstellen eines Jobs."""
    queue = get_queue()
    return await queue.enqueue_scan(url, task_name, lang=lang)


async def wait_for_result(job_id: str, timeout: int = 120) -> Optional[JobResult]:
    """Shortcut zum Warten auf ein Ergebnis."""
    queue = get_queue()
    return await queue.get_result(job_id, timeout)
