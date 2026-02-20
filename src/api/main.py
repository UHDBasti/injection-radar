"""
REST API für InjectionRadar (Orchestrator).

FastAPI Server für externe Abfragen und Scan-Anfragen.

WICHTIG: Der Orchestrator sieht NIEMALS Rohdaten (raw_html, extracted_text)!
Er kommuniziert nur via Redis Queue mit dem Scraper-Subsystem und empfängt
ausschließlich strukturierte JobResults.
"""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select, func
from starlette.middleware.base import BaseHTTPMiddleware

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
from ..core.queue import JobQueue, QueueConfig, ScanJob, JobResult
from ..core.logging import log_info, log_error, log_warning


# Global state
settings = get_settings()
engine = None
SessionFactory = None
job_queue: Optional[JobQueue] = None
rate_limit_redis: Optional[aioredis.Redis] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle Management für FastAPI."""
    global engine, SessionFactory, job_queue, rate_limit_redis

    # Startup
    log_info("orchestrator_starting")

    engine = get_async_engine(settings.database.url)
    SessionFactory = get_async_session_factory(engine)

    # Datenbank initialisieren
    await init_db(engine)

    # Redis Queue verbinden
    queue_config = QueueConfig(
        host=settings.redis.host,
        port=settings.redis.port,
        db=settings.redis.db,
        password=settings.redis.password,
        job_timeout_seconds=settings.redis.job_timeout_seconds,
        result_ttl_seconds=settings.redis.result_ttl_seconds,
    )
    job_queue = JobQueue(queue_config)
    await job_queue.connect()

    # Redis for rate limiting
    try:
        rate_limit_redis = aioredis.Redis(
            host=settings.redis.host,
            port=settings.redis.port,
            db=settings.redis.db,
            password=settings.redis.password,
            decode_responses=True,
        )
        await rate_limit_redis.ping()
        log_info("rate_limiter_connected")
    except Exception as e:
        log_warning("rate_limiter_unavailable", error=str(e))
        rate_limit_redis = None

    log_info("orchestrator_started", redis=f"{settings.redis.host}:{settings.redis.port}")

    yield

    # Shutdown
    log_info("orchestrator_stopping")
    if rate_limit_redis:
        await rate_limit_redis.aclose()
    if job_queue:
        await job_queue.disconnect()


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


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that assigns a unique request_id to each request.

    Adds the ID to structlog context so all log messages within the request
    include it, and returns it in the X-Request-ID response header.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        structlog.contextvars.clear_contextvars()
        return response


# Rate limit tiers: path prefix -> requests per minute
_RATE_LIMITS: dict[str, int] = {
    "/scan/async": 120,   # Lightweight queue operation, needs high limit for batch
    "/scan": 30,          # Synchronous scan, heavier but still needs batch support
}
_DEFAULT_RATE_LIMIT = 60  # read-only endpoints


def _get_rate_limit(path: str) -> int:
    """Return the per-minute rate limit for a request path.

    Status polling endpoints (/scan/{id}/status) use the default
    (higher) limit so that polling doesn't get throttled.
    """
    # Status polling should not be rate-limited as strictly as scan submission
    if "/status" in path:
        return _DEFAULT_RATE_LIMIT
    for prefix, limit in _RATE_LIMITS.items():
        if path.rstrip("/") == prefix or path.startswith(prefix + "/"):
            return limit
    return _DEFAULT_RATE_LIMIT


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind a reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Redis sliding-window rate limiter.

    Uses sorted sets keyed by (client_ip, endpoint_tier) with timestamps as
    scores.  Falls through gracefully when Redis is unavailable.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if rate_limit_redis is None:
            return await call_next(request)

        client_ip = _get_client_ip(request)
        limit = _get_rate_limit(request.url.path)
        window = 60  # seconds
        now = time.time()
        key = f"rl:{client_ip}:{limit}"

        try:
            pipe = rate_limit_redis.pipeline()
            # Remove entries older than the window
            pipe.zremrangebyscore(key, 0, now - window)
            # Count remaining entries
            pipe.zcard(key)
            # Add current request
            pipe.zadd(key, {f"{now}:{uuid.uuid4().hex[:8]}": now})
            # Expire the whole key after the window to avoid leaks
            pipe.expire(key, window + 1)
            results = await pipe.execute()
            current_count = results[1]
        except Exception:
            # Redis error - don't block the request
            return await call_next(request)

        if current_count >= limit:
            log_warning(
                "rate_limit_exceeded",
                client_ip=client_ip,
                path=request.url.path,
                limit=limit,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current_count - 1))
        return response


app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware)


# ============================================================================
# Request/Response Models
# ============================================================================

class ScanRequest(BaseModel):
    """Request für einen URL-Scan."""
    url: HttpUrl
    task: str = "summarize"


class ScanResponse(BaseModel):
    """Response eines Scans (NUR strukturierte Daten!)."""
    job_id: str
    url: str
    status: str  # "completed", "failed", "pending"
    classification: Optional[str] = None
    confidence: Optional[float] = None
    severity_score: Optional[float] = None
    flags_count: Optional[int] = None
    flags: Optional[list[dict]] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_estimated: float = 0.0
    processing_time_ms: Optional[int] = None
    scanned_at: Optional[datetime] = None
    error_message: Optional[str] = None


class AsyncScanResponse(BaseModel):
    """Response für asynchronen Scan (nur Job-ID)."""
    job_id: str
    url: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    """Status eines laufenden Jobs."""
    job_id: str
    status: str
    result: Optional[ScanResponse] = None


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
    queue_length: int
    last_scan: Optional[datetime]


# ============================================================================
# Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Health Check Endpoint."""
    queue_ok = job_queue is not None
    try:
        if job_queue:
            await job_queue.get_queue_length()
    except Exception:
        queue_ok = False

    return {
        "status": "healthy" if queue_ok else "degraded",
        "redis_connected": queue_ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


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

        # Letzter Scan (aus urls statt analysis_results, da letztere
        # erst mit BUG-1-Fix befuellt werden)
        last_analysis = await session.scalar(
            select(func.max(URLDB.last_scanned))
        )

        # Queue-Länge
        queue_length = 0
        if job_queue:
            try:
                queue_length = await job_queue.get_queue_length()
            except Exception:
                pass

        total = sum(status_counts.values())

        return StatusResponse(
            status="operational",
            total_urls=total,
            total_domains=domain_count or 0,
            dangerous_count=status_counts.get(Classification.DANGEROUS, 0),
            suspicious_count=status_counts.get(Classification.SUSPICIOUS, 0),
            pending_count=status_counts.get(Classification.PENDING, 0),
            queue_length=queue_length,
            last_scan=last_analysis,
        )


@app.post("/scan", response_model=ScanResponse)
async def scan_url(request: ScanRequest, background_tasks: BackgroundTasks):
    """Scannt eine URL auf Prompt Injection (synchron, wartet auf Ergebnis).

    Der Orchestrator:
    1. Sendet Job an Redis Queue
    2. Wartet auf Ergebnis vom Scraper-Subsystem
    3. Empfängt NUR strukturiertes JobResult (keine Rohdaten!)
    4. Speichert Analyse in Datenbank
    """
    if not job_queue:
        raise HTTPException(status_code=503, detail="Queue not available")

    url_str = str(request.url)
    log_info("scan_requested", url=url_str, task=request.task)

    try:
        # Job in Queue einstellen
        job = await job_queue.enqueue_scan(url_str, request.task)

        # Auf Ergebnis warten (blocking mit Timeout)
        result = await job_queue.get_result(
            job.job_id,
            timeout_seconds=settings.redis.job_timeout_seconds,
        )

        if result is None:
            log_warning("scan_timeout", job_id=job.job_id, url=url_str)
            return ScanResponse(
                job_id=job.job_id,
                url=url_str,
                status="timeout",
                error_message="Scan timed out. The scraper might be overloaded.",
            )

        if result.status == "failed":
            log_error("scan_failed", job_id=job.job_id, error=result.error_message)
            return ScanResponse(
                job_id=job.job_id,
                url=url_str,
                status="failed",
                error_message=result.error_message,
            )

        # Erfolgreiche Antwort
        # WICHTIG: Hier sehen wir NUR strukturierte Daten, keine Rohdaten!
        log_info(
            "scan_completed",
            job_id=job.job_id,
            url=url_str,
            classification=result.classification,
            severity=result.severity_score,
        )

        # Confidence berechnen basierend auf Severity
        confidence = _calculate_confidence(result.severity_score, result.classification)

        # In DB speichern (direkt, nicht als Background Task weil es Probleme gab)
        await _save_scan_results(url_str, result, confidence)

        return ScanResponse(
            job_id=job.job_id,
            url=url_str,
            status="completed",
            classification=result.classification,
            confidence=confidence,
            severity_score=result.severity_score,
            flags_count=result.flags_count,
            flags=result.flags,
            llm_provider=result.llm_provider,
            llm_model=result.llm_model,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
            cost_estimated=result.cost_estimated,
            processing_time_ms=result.processing_time_ms,
            scanned_at=datetime.now(timezone.utc),
        )

    except Exception as e:
        log_error("scan_error", url=url_str, error=str(e))
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")


@app.post("/scan/async", response_model=AsyncScanResponse)
async def scan_url_async(request: ScanRequest):
    """Startet einen asynchronen Scan (gibt sofort Job-ID zurück).

    Nutze GET /scan/{job_id}/status um den Status abzufragen.
    """
    if not job_queue:
        raise HTTPException(status_code=503, detail="Queue not available")

    url_str = str(request.url)

    try:
        job = await job_queue.enqueue_scan(url_str, request.task)

        log_info("async_scan_queued", job_id=job.job_id, url=url_str)

        return AsyncScanResponse(
            job_id=job.job_id,
            url=url_str,
            status="queued",
            message="Scan queued. Poll /scan/{job_id}/status for results.",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue scan: {str(e)}")


# Track which job_ids have already been persisted to DB (avoid duplicates on poll)
_persisted_jobs: set[str] = set()


@app.get("/scan/{job_id}/status", response_model=JobStatusResponse)
async def get_scan_status(job_id: str):
    """Prüft den Status eines laufenden Scans."""
    if not job_queue:
        raise HTTPException(status_code=503, detail="Queue not available")

    result = await job_queue.get_result_nowait(job_id)

    if result is None:
        return JobStatusResponse(
            job_id=job_id,
            status="pending",
            result=None,
        )

    confidence = _calculate_confidence(result.severity_score, result.classification)

    # Persist results when completed - only once per job_id
    if result.status == "completed" and job_id not in _persisted_jobs:
        _persisted_jobs.add(job_id)
        await _save_scan_results(result.url, result, confidence)
        # Limit set size to prevent memory leak
        if len(_persisted_jobs) > 10000:
            # Remove oldest entries (set is unordered, just trim)
            excess = len(_persisted_jobs) - 5000
            for _ in range(excess):
                _persisted_jobs.pop()

    return JobStatusResponse(
        job_id=job_id,
        status=result.status,
        result=ScanResponse(
            job_id=job_id,
            url=result.url,
            status=result.status,
            classification=result.classification,
            confidence=confidence,
            severity_score=result.severity_score,
            flags_count=result.flags_count,
            flags=result.flags,
            llm_provider=result.llm_provider,
            llm_model=result.llm_model,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
            cost_estimated=result.cost_estimated,
            processing_time_ms=result.processing_time_ms,
            scanned_at=datetime.utcnow(),
            error_message=result.error_message,
        ),
    )


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


@app.get("/queue/stats")
async def get_queue_stats():
    """Gibt Queue-Statistiken zurück."""
    if not job_queue:
        raise HTTPException(status_code=503, detail="Queue not available")

    try:
        length = await job_queue.get_queue_length()
        return {
            "queue_length": length,
            "redis_host": settings.redis.host,
            "redis_port": settings.redis.port,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Queue error: {str(e)}")


@app.get("/history")
async def get_history(
    limit: int = Query(20, ge=1, le=100, description="Anzahl der Einträge"),
):
    """Gibt die letzten Scan-Ergebnisse zurück (für MCP Server)."""
    from ..core.database import ScrapedContentDB
    from sqlalchemy.orm import selectinload

    async with SessionFactory() as session:
        result = await session.execute(
            select(ScrapedContentDB)
            .options(selectinload(ScrapedContentDB.url))
            .order_by(ScrapedContentDB.scraped_at.desc())
            .limit(limit)
        )
        items = result.scalars().all()

        return {
            "history": [
                {
                    "url": item.url.url if item.url else "unknown",
                    "status": item.url.current_status.value if item.url else "unknown",
                    "http_status": item.http_status,
                    "word_count": item.word_count,
                    "scanned_at": item.scraped_at.isoformat(),
                }
                for item in items
            ],
            "total": len(items),
        }


@app.get("/url/status")
async def check_url_status(
    url: str = Query(..., description="Die zu prüfende URL"),
):
    """Prüft ob eine URL bereits gescannt wurde (für MCP Server)."""
    async with SessionFactory() as session:
        url_db = await session.scalar(
            select(URLDB).where(URLDB.url == url)
        )

        if not url_db:
            raise HTTPException(status_code=404, detail="URL not found in database")

        # Letzte Analyse holen
        analysis = await session.scalar(
            select(AnalysisResultDB)
            .where(AnalysisResultDB.url_id == url_db.id)
            .order_by(AnalysisResultDB.analyzed_at.desc())
        )

        return {
            "url": url,
            "status": url_db.current_status.value,
            "confidence": url_db.current_confidence,
            "scan_count": url_db.scan_count,
            "first_scanned": url_db.first_scanned.isoformat() if url_db.first_scanned else None,
            "last_scanned": url_db.last_scanned.isoformat() if url_db.last_scanned else None,
            "severity_score": analysis.severity_score if analysis else None,
            "flags_count": len(analysis.flags_triggered) if analysis else 0,
        }


@app.get("/domains/dangerous")
async def get_dangerous_domains(
    limit: int = Query(20, ge=1, le=100, description="Anzahl der Einträge"),
):
    """Listet Domains mit gefährlichen URLs (für MCP Server)."""
    async with SessionFactory() as session:
        result = await session.execute(
            select(DomainDB)
            .where(DomainDB.dangerous_urls_count > 0)
            .order_by(DomainDB.risk_score.desc())
            .limit(limit)
        )
        domains = result.scalars().all()

        return {
            "dangerous_domains": [
                {
                    "domain": d.domain,
                    "dangerous_count": d.dangerous_urls_count,
                    "suspicious_count": d.suspicious_urls_count,
                    "total_scanned": d.total_urls_scanned,
                    "risk_score": d.risk_score,
                    "first_seen": d.first_seen.isoformat(),
                }
                for d in domains
            ],
            "total": len(domains),
        }


# ============================================================================
# Helper Functions
# ============================================================================

def _calculate_confidence(severity_score: float, classification: str) -> float:
    """Berechnet die Confidence basierend auf Severity und Classification."""
    if classification == "dangerous":
        return min(0.9, severity_score / 10)
    elif classification == "suspicious":
        if severity_score >= 3.0:
            return 0.7
        return 0.5
    else:  # safe
        return 0.8


def _extract_domain(url_str: str) -> str:
    """Extracts the domain from a URL string."""
    from urllib.parse import urlparse
    return urlparse(url_str).netloc.lower()


async def _save_scan_results(url_str: str, result: JobResult, confidence: float):
    """Speichert Scan-Ergebnisse in der Datenbank.

    Creates/updates the URL record, inserts a ScanResultDB and
    AnalysisResultDB entry, and updates domain aggregate statistics.
    """
    try:
        classification_map = {
            "safe": Classification.SAFE,
            "suspicious": Classification.SUSPICIOUS,
            "dangerous": Classification.DANGEROUS,
            "error": Classification.ERROR,
        }
        classification = classification_map.get(result.classification, Classification.PENDING)

        async with SessionFactory() as session:
            # ----------------------------------------------------------
            # 1. Domain erstellen/finden
            # ----------------------------------------------------------
            domain_name = _extract_domain(url_str)
            domain_db = None
            if domain_name:
                domain_db = await session.scalar(
                    select(DomainDB).where(DomainDB.domain == domain_name)
                )
                if not domain_db:
                    domain_db = DomainDB(
                        domain=domain_name,
                        first_seen=datetime.utcnow(),
                    )
                    session.add(domain_db)
                    await session.flush()

            # ----------------------------------------------------------
            # 2. URL speichern/aktualisieren
            # ----------------------------------------------------------
            url_db = await session.scalar(
                select(URLDB).where(URLDB.url == url_str)
            )

            if not url_db:
                url_db = URLDB(
                    url=url_str,
                    domain_id=domain_db.id if domain_db else None,
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
                if domain_db and not url_db.domain_id:
                    url_db.domain_id = domain_db.id

            await session.flush()

            # ----------------------------------------------------------
            # 3. ScanResultDB erstellen
            # ----------------------------------------------------------
            scan_result_db = ScanResultDB(
                url_id=url_db.id,
                task_name="summarize",
                llm_provider=result.llm_provider or "unknown",
                llm_model=result.llm_model or "unknown",
                output_length=result.tokens_output,
                output_word_count=0,
                output_format_detected="text",
                tool_calls_attempted=any(
                    f.get("type") == "tool_call" for f in result.flags
                ),
                tool_calls_count=sum(
                    1 for f in result.flags if f.get("type") == "tool_call"
                ),
                flags_detected=result.flags,
                format_match_score=0.0,
                expected_vs_actual_length_ratio=1.0,
                scanned_at=datetime.utcnow(),
            )
            session.add(scan_result_db)
            await session.flush()

            # ----------------------------------------------------------
            # 4. AnalysisResultDB erstellen
            # ----------------------------------------------------------
            analysis_db = AnalysisResultDB(
                url_id=url_db.id,
                scan_result_id=scan_result_db.id,
                classification=classification,
                confidence=confidence,
                severity_score=result.severity_score,
                flags_triggered=result.flags,
                reasoning=f"Automated scan: {result.flags_count} flags, severity {result.severity_score:.1f}",
                analyzed_at=datetime.utcnow(),
            )
            session.add(analysis_db)

            # ----------------------------------------------------------
            # 5. Domain-Statistiken aktualisieren
            # ----------------------------------------------------------
            if domain_db:
                domain_db.total_urls_scanned += 1
                if classification == Classification.DANGEROUS:
                    domain_db.dangerous_urls_count += 1
                elif classification == Classification.SUSPICIOUS:
                    domain_db.suspicious_urls_count += 1
                # Risiko-Score: gewichteter Anteil gefaehrlicher URLs
                total = domain_db.total_urls_scanned or 1
                domain_db.risk_score = (
                    (domain_db.dangerous_urls_count * 10
                     + domain_db.suspicious_urls_count * 3)
                    / total
                )

            await session.commit()
            log_info(
                "scan_results_saved",
                url=url_str,
                classification=result.classification,
                scan_result_id=scan_result_db.id,
                analysis_id=analysis_db.id,
            )

    except Exception as e:
        log_error("save_results_failed", url=url_str, error=str(e))


# ============================================================================
# Entry point
# ============================================================================

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
