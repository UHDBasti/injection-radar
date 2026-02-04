"""
REST API für InjectionRadar.

FastAPI Server für externe Abfragen und Scan-Anfragen.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select, func

from ..core.config import get_settings
from ..core.models import Classification, RedFlag
from ..core.database import (
    get_async_engine,
    get_async_session_factory,
    init_db,
    DomainDB,
    URLDB,
    ScanResultDB,
    AnalysisResultDB,
)
from ..scraper.worker import ScraperWorker
from ..analysis.detector import RedFlagDetector


# Global state
settings = get_settings()
engine = None
SessionFactory = None
worker: Optional[ScraperWorker] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle Management für FastAPI."""
    global engine, SessionFactory, worker

    # Startup
    engine = get_async_engine(settings.database.url)
    SessionFactory = get_async_session_factory(engine)

    # Datenbank initialisieren
    await init_db(engine)

    # Worker starten (optional, für On-Demand Scans)
    worker = ScraperWorker()
    await worker.start()

    yield

    # Shutdown
    if worker:
        await worker.stop()


app = FastAPI(
    title="InjectionRadar API",
    description="API zur Erkennung von Prompt Injection in Web-Inhalten",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In Produktion einschränken!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response Models

class ScanRequest(BaseModel):
    """Request für einen URL-Scan."""
    url: HttpUrl
    task: str = "summarize"


class ScanResponse(BaseModel):
    """Response eines Scans."""
    url: str
    classification: Classification
    confidence: float
    severity_score: float
    flags_count: int
    flags: list[dict]
    scanned_at: datetime


class DomainStats(BaseModel):
    """Statistiken für eine Domain."""
    domain: str
    total_urls_scanned: int
    dangerous_count: int
    suspicious_count: int
    safe_count: int
    risk_score: float


class StatusResponse(BaseModel):
    """System-Status Response."""
    status: str
    total_urls: int
    total_domains: int
    dangerous_count: int
    suspicious_count: int
    pending_count: int
    last_scan: Optional[datetime]


# Endpoints

@app.get("/health")
async def health_check():
    """Health Check Endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/status", response_model=StatusResponse)
async def get_status():
    """Gibt den aktuellen System-Status zurück."""
    async with SessionFactory() as session:
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

        # Letzter Scan
        last_analysis = await session.scalar(
            select(func.max(AnalysisResultDB.analyzed_at))
        )

        total = sum(status_counts.values())

        return StatusResponse(
            status="operational",
            total_urls=total,
            total_domains=domain_count or 0,
            dangerous_count=status_counts.get(Classification.DANGEROUS, 0),
            suspicious_count=status_counts.get(Classification.SUSPICIOUS, 0),
            pending_count=status_counts.get(Classification.PENDING, 0),
            last_scan=last_analysis,
        )


@app.post("/scan", response_model=ScanResponse)
async def scan_url(request: ScanRequest, background_tasks: BackgroundTasks):
    """Scannt eine URL auf Prompt Injection.

    Führt einen vollständigen Scan durch:
    1. Scraped die Website
    2. Testet mit LLM
    3. Analysiert auf Red Flags
    4. Speichert Ergebnisse
    """
    if not worker:
        raise HTTPException(status_code=503, detail="Scanner not available")

    url_str = str(request.url)

    try:
        # Scrapen
        content = await worker.scrape_url(url_str)

        # LLM Test
        scan_result = await worker.run_llm_test(content, request.task)

        # Klassifizierung berechnen
        detector = RedFlagDetector()
        severity_score = detector.calculate_severity_score(scan_result.flags_detected)

        # Klassifizierung basierend auf Schweregrad
        if severity_score >= 6.0:
            classification = Classification.DANGEROUS
            confidence = min(0.9, severity_score / 10)
        elif severity_score >= 3.0:
            classification = Classification.SUSPICIOUS
            confidence = 0.7
        elif severity_score > 0:
            classification = Classification.SUSPICIOUS
            confidence = 0.5
        else:
            classification = Classification.SAFE
            confidence = 0.8

        # In DB speichern (Background Task)
        async def save_results():
            async with SessionFactory() as session:
                # URL speichern/aktualisieren
                url_db = await session.scalar(
                    select(URLDB).where(URLDB.url == url_str)
                )

                if not url_db:
                    url_db = URLDB(
                        url=url_str,
                        current_status=classification,
                        current_confidence=confidence,
                        first_scanned=datetime.utcnow(),
                        last_scanned=datetime.utcnow(),
                        scan_count=1,
                    )
                    session.add(url_db)
                else:
                    url_db.current_status = classification
                    url_db.current_confidence = confidence
                    url_db.last_scanned = datetime.utcnow()
                    url_db.scan_count += 1

                await session.commit()

        background_tasks.add_task(save_results)

        return ScanResponse(
            url=url_str,
            classification=classification,
            confidence=confidence,
            severity_score=severity_score,
            flags_count=len(scan_result.flags_detected),
            flags=[
                {
                    "type": f.type.value,
                    "severity": f.severity.value,
                    "description": f.description,
                }
                for f in scan_result.flags_detected
            ],
            scanned_at=datetime.utcnow(),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")


@app.get("/results/{url_id}")
async def get_results(url_id: int):
    """Gibt die Scan-Ergebnisse für eine URL-ID zurück."""
    async with SessionFactory() as session:
        url_db = await session.get(URLDB, url_id)
        if not url_db:
            raise HTTPException(status_code=404, detail="URL not found")

        # Letzte Analyse holen
        result = await session.execute(
            select(AnalysisResultDB)
            .where(AnalysisResultDB.url_id == url_id)
            .order_by(AnalysisResultDB.analyzed_at.desc())
            .limit(1)
        )
        analysis = result.scalar_one_or_none()

        return {
            "url_id": url_id,
            "url": str(url_db.url),
            "current_status": url_db.current_status.value,
            "confidence": url_db.current_confidence,
            "scan_count": url_db.scan_count,
            "last_scanned": url_db.last_scanned,
            "analysis": {
                "classification": analysis.classification.value,
                "severity_score": analysis.severity_score,
                "reasoning": analysis.reasoning,
                "flags_triggered": analysis.flags_triggered,
            } if analysis else None,
        }


@app.get("/domains/{domain}/stats", response_model=DomainStats)
async def get_domain_stats(domain: str):
    """Gibt Statistiken für eine Domain zurück."""
    async with SessionFactory() as session:
        domain_db = await session.scalar(
            select(DomainDB).where(DomainDB.domain == domain)
        )

        if not domain_db:
            raise HTTPException(status_code=404, detail="Domain not found")

        # Zusätzliche Stats berechnen
        safe_count = await session.scalar(
            select(func.count(URLDB.id))
            .where(URLDB.domain_id == domain_db.id)
            .where(URLDB.current_status == Classification.SAFE)
        )

        return DomainStats(
            domain=domain_db.domain,
            total_urls_scanned=domain_db.total_urls_scanned,
            dangerous_count=domain_db.dangerous_urls_count,
            suspicious_count=domain_db.suspicious_urls_count,
            safe_count=safe_count or 0,
            risk_score=domain_db.risk_score,
        )


@app.get("/urls")
async def list_urls(
    status: Optional[Classification] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Listet URLs mit optionalem Status-Filter."""
    async with SessionFactory() as session:
        query = select(URLDB).offset(offset).limit(limit)

        if status:
            query = query.where(URLDB.current_status == status)

        query = query.order_by(URLDB.last_scanned.desc())

        result = await session.execute(query)
        urls = result.scalars().all()

        return {
            "urls": [
                {
                    "id": u.id,
                    "url": str(u.url),
                    "status": u.current_status.value,
                    "confidence": u.current_confidence,
                    "scan_count": u.scan_count,
                    "last_scanned": u.last_scanned,
                }
                for u in urls
            ],
            "offset": offset,
            "limit": limit,
            "total": len(urls),
        }


@app.get("/dangerous")
async def list_dangerous(
    limit: int = Query(50, ge=1, le=500),
):
    """Listet die gefährlichsten URLs."""
    async with SessionFactory() as session:
        result = await session.execute(
            select(AnalysisResultDB, URLDB)
            .join(URLDB, AnalysisResultDB.url_id == URLDB.id)
            .where(AnalysisResultDB.classification == Classification.DANGEROUS)
            .order_by(AnalysisResultDB.severity_score.desc())
            .limit(limit)
        )
        rows = result.fetchall()

        return {
            "dangerous_urls": [
                {
                    "url": str(url.url),
                    "severity_score": analysis.severity_score,
                    "confidence": analysis.confidence,
                    "flags_count": len(analysis.flags_triggered),
                    "reasoning": analysis.reasoning,
                    "analyzed_at": analysis.analyzed_at,
                }
                for analysis, url in rows
            ],
            "total": len(rows),
        }


# Entry point für uvicorn
def create_app() -> FastAPI:
    """Factory Function für die FastAPI App."""
    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=True,
    )
