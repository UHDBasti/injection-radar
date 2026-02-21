"""
Checkpoint-Manager für große Crawl-Operationen.

Speichert Fortschritt in der Datenbank, damit unterbrochene Batch-Scans
fortgesetzt werden können.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from .database import CrawlCheckpointDB
from .models import CrawlCheckpoint


class CheckpointManager:
    """Verwaltet Crawl-Checkpoints in der Datenbank.

    Ermöglicht das Speichern, Laden und Löschen von Checkpoints
    für große CSV-Batch-Scans, sodass unterbrochene Scans
    fortgesetzt werden können.
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def save_checkpoint(
        self, source: str, index: int, url: str, total: int
    ) -> None:
        """Speichert oder aktualisiert einen Checkpoint.

        Args:
            source: Kennung der Quelle (z.B. CSV-Dateipfad oder Hash)
            index: Index der zuletzt verarbeiteten URL
            url: Die zuletzt verarbeitete URL
            total: Gesamtanzahl der URLs in der Quelle
        """
        async with self.session_factory() as session:
            async with session.begin():
                # Prüfe ob Checkpoint für diese Quelle existiert
                result = await session.execute(
                    select(CrawlCheckpointDB).where(
                        CrawlCheckpointDB.source == source
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    existing.last_processed_index = index
                    existing.last_processed_url = url
                    existing.processed_count = index + 1
                    existing.total_in_source = total
                    existing.last_updated = datetime.utcnow()
                else:
                    checkpoint = CrawlCheckpointDB(
                        source=source,
                        last_processed_index=index,
                        last_processed_url=url,
                        total_in_source=total,
                        processed_count=index + 1,
                        started_at=datetime.utcnow(),
                        last_updated=datetime.utcnow(),
                    )
                    session.add(checkpoint)

    async def load_checkpoint(self, source: str) -> Optional[CrawlCheckpoint]:
        """Lädt einen Checkpoint für die angegebene Quelle.

        Args:
            source: Kennung der Quelle

        Returns:
            CrawlCheckpoint oder None wenn keiner existiert
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(CrawlCheckpointDB).where(
                    CrawlCheckpointDB.source == source
                )
            )
            row = result.scalar_one_or_none()

            if row is None:
                return None

            return CrawlCheckpoint(
                id=row.id,
                source=row.source,
                last_processed_index=row.last_processed_index,
                last_processed_url=row.last_processed_url,
                total_in_source=row.total_in_source,
                processed_count=row.processed_count,
                started_at=row.started_at,
                last_updated=row.last_updated,
                completed_at=row.completed_at,
            )

    async def clear_checkpoint(self, source: str) -> None:
        """Löscht den Checkpoint für die angegebene Quelle.

        Args:
            source: Kennung der Quelle
        """
        async with self.session_factory() as session:
            async with session.begin():
                await session.execute(
                    delete(CrawlCheckpointDB).where(
                        CrawlCheckpointDB.source == source
                    )
                )

    async def mark_completed(self, source: str) -> None:
        """Markiert einen Checkpoint als abgeschlossen.

        Args:
            source: Kennung der Quelle
        """
        async with self.session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(CrawlCheckpointDB).where(
                        CrawlCheckpointDB.source == source
                    )
                )
                existing = result.scalar_one_or_none()
                if existing:
                    existing.completed_at = datetime.utcnow()
                    existing.last_updated = datetime.utcnow()

    async def list_checkpoints(self) -> list[CrawlCheckpoint]:
        """Listet alle offenen (nicht abgeschlossenen) Checkpoints.

        Returns:
            Liste von CrawlCheckpoint-Objekten
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(CrawlCheckpointDB)
                .where(CrawlCheckpointDB.completed_at.is_(None))
                .order_by(CrawlCheckpointDB.last_updated.desc())
            )
            rows = result.scalars().all()

            return [
                CrawlCheckpoint(
                    id=row.id,
                    source=row.source,
                    last_processed_index=row.last_processed_index,
                    last_processed_url=row.last_processed_url,
                    total_in_source=row.total_in_source,
                    processed_count=row.processed_count,
                    started_at=row.started_at,
                    last_updated=row.last_updated,
                    completed_at=row.completed_at,
                )
                for row in rows
            ]
