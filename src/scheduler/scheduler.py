"""
Scheduled re-scanning for InjectionRadar.

Periodically checks the database for URLs that are due for a re-scan
based on their classification and the configured rescan intervals.
Submits due URLs to the Redis job queue for processing by scraper workers.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import Settings
from ..core.database import URLDB
from ..core.models import Classification
from ..core.queue import JobQueue
from ..core.logging import log_info, log_error, log_warning

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False


class ScanScheduler:
    """Manages periodic re-scanning of URLs based on their classification.

    URLs classified as dangerous are re-scanned more frequently than
    suspicious ones, and suspicious more frequently than safe ones.
    The intervals are configured in CrawlingConfig.
    """

    def __init__(
        self,
        settings: Settings,
        session_factory,
        job_queue: JobQueue,
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.job_queue = job_queue
        self._scheduler: Optional["AsyncIOScheduler"] = None
        self._last_run: Optional[datetime] = None
        self._urls_rescanned: int = 0
        self._total_rescans: int = 0

    async def start(self) -> None:
        """Start the scheduler with the configured check interval."""
        if not HAS_APSCHEDULER:
            log_warning("scheduler_skipped", reason="apscheduler not installed")
            return

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.check_and_rescan,
            "interval",
            minutes=self.settings.scheduler.check_interval_minutes,
            id="rescan_check",
            name="Check and rescan due URLs",
        )
        self._scheduler.start()
        log_info(
            "scheduler_started",
            interval_minutes=self.settings.scheduler.check_interval_minutes,
            max_per_run=self.settings.scheduler.max_rescans_per_run,
        )

    async def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            log_info("scheduler_stopped")

    async def check_and_rescan(self) -> int:
        """Find URLs due for re-scan and submit them to the job queue.

        Returns:
            Number of URLs submitted for re-scanning.
        """
        now = datetime.utcnow()
        max_rescans = self.settings.scheduler.max_rescans_per_run
        submitted = 0

        try:
            async with self.session_factory() as session:
                # Build interval mapping from config
                intervals = {
                    Classification.DANGEROUS: timedelta(
                        days=self.settings.crawling.rescan_interval_dangerous
                    ),
                    Classification.SUSPICIOUS: timedelta(
                        days=self.settings.crawling.rescan_interval_suspicious
                    ),
                    Classification.SAFE: timedelta(
                        days=self.settings.crawling.rescan_interval_safe
                    ),
                }

                for classification, interval in intervals.items():
                    if submitted >= max_rescans:
                        break

                    cutoff = now - interval
                    remaining = max_rescans - submitted

                    # Find URLs that were last scanned before the cutoff
                    result = await session.execute(
                        select(URLDB)
                        .where(URLDB.current_status == classification)
                        .where(URLDB.last_scanned < cutoff)
                        .order_by(URLDB.last_scanned.asc())
                        .limit(remaining)
                    )
                    due_urls = result.scalars().all()

                    for url_db in due_urls:
                        try:
                            await self.job_queue.enqueue_scan(
                                str(url_db.url), "summarize"
                            )
                            submitted += 1
                            log_info(
                                "rescan_queued",
                                url=str(url_db.url),
                                classification=classification.value,
                                last_scanned=url_db.last_scanned.isoformat()
                                if url_db.last_scanned
                                else "never",
                            )
                        except Exception as e:
                            log_error(
                                "rescan_enqueue_failed",
                                url=str(url_db.url),
                                error=str(e),
                            )

            self._last_run = now
            self._urls_rescanned = submitted
            self._total_rescans += submitted

            log_info(
                "rescan_check_completed",
                urls_submitted=submitted,
                total_rescans=self._total_rescans,
            )

        except Exception as e:
            log_error("rescan_check_failed", error=str(e))

        return submitted

    def get_status(self) -> dict:
        """Return current scheduler state for the status endpoint."""
        running = (
            self._scheduler is not None
            and self._scheduler.running
            if HAS_APSCHEDULER
            else False
        )

        next_run = None
        if running and self._scheduler:
            job = self._scheduler.get_job("rescan_check")
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()

        return {
            "enabled": self.settings.scheduler.enabled,
            "running": running,
            "apscheduler_installed": HAS_APSCHEDULER,
            "check_interval_minutes": self.settings.scheduler.check_interval_minutes,
            "max_rescans_per_run": self.settings.scheduler.max_rescans_per_run,
            "next_run": next_run,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_run_rescanned": self._urls_rescanned,
            "total_rescans": self._total_rescans,
            "rescan_intervals": {
                "safe_days": self.settings.crawling.rescan_interval_safe,
                "suspicious_days": self.settings.crawling.rescan_interval_suspicious,
                "dangerous_days": self.settings.crawling.rescan_interval_dangerous,
            },
        }
