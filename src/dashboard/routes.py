"""Dashboard routes for InjectionRadar web UI."""

import os
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from starlette.responses import Response

from ..core.models import Classification
from ..core.validators import validate_scan_url
from ..core.database import (
    get_async_session_factory,
    DomainDB,
    URLDB,
    AnalysisResultDB,
)

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])

PAGE_SIZE = 25


def _get_csrf_token(request: Request, response: Response = None) -> str:
    """Get or create CSRF token from cookie."""
    token = request.cookies.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        if response:
            response.set_cookie(
                "csrf_token", token, httponly=True, samesite="strict"
            )
    return token


def _verify_csrf(request: Request, form_token: str) -> bool:
    """Verify CSRF token from form matches cookie."""
    cookie_token = request.cookies.get("csrf_token")
    return bool(cookie_token and cookie_token == form_token)


def _get_session_factory():
    """Get the SessionFactory from the api module's global state."""
    from ..api.main import SessionFactory
    return SessionFactory


def _get_job_queue():
    """Get the job_queue from the api module's global state."""
    from ..api.main import job_queue
    return job_queue


def _format_datetime(dt: Optional[datetime]) -> str:
    """Format a datetime for display."""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M")


@dashboard_router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Dashboard home page with stats and recent scans."""
    session_factory = _get_session_factory()

    stats = {
        "total_urls": 0,
        "total_domains": 0,
        "dangerous_count": 0,
        "suspicious_count": 0,
        "safe_count": 0,
        "queue_length": 0,
        "last_scan": None,
    }
    recent_scans = []
    health = {"status": "healthy", "redis_connected": False}

    try:
        async with session_factory() as session:
            # Count URLs by status
            result = await session.execute(
                select(URLDB.current_status, func.count(URLDB.id))
                .group_by(URLDB.current_status)
            )
            status_counts = dict(result.fetchall())

            stats["total_urls"] = sum(status_counts.values())
            stats["dangerous_count"] = status_counts.get(Classification.DANGEROUS, 0)
            stats["suspicious_count"] = status_counts.get(Classification.SUSPICIOUS, 0)
            stats["safe_count"] = status_counts.get(Classification.SAFE, 0)

            # Domain count
            domain_count = await session.scalar(select(func.count(DomainDB.id)))
            stats["total_domains"] = domain_count or 0

            # Last scan
            last_scan = await session.scalar(select(func.max(URLDB.last_scanned)))
            stats["last_scan"] = _format_datetime(last_scan)

            # Recent scans with analysis
            result = await session.execute(
                select(URLDB, AnalysisResultDB)
                .outerjoin(AnalysisResultDB, URLDB.id == AnalysisResultDB.url_id)
                .order_by(URLDB.last_scanned.desc())
                .limit(10)
            )
            rows = result.fetchall()
            for url_db, analysis in rows:
                recent_scans.append({
                    "url": str(url_db.url),
                    "status": url_db.current_status.value,
                    "severity": analysis.severity_score if analysis else None,
                    "confidence": url_db.current_confidence,
                    "last_scanned": _format_datetime(url_db.last_scanned),
                })
    except Exception:
        health["status"] = "degraded"

    # Queue length
    jq = _get_job_queue()
    if jq:
        try:
            stats["queue_length"] = await jq.get_queue_length()
            health["redis_connected"] = True
        except Exception:
            pass

    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": stats,
        "recent_scans": recent_scans,
        "health": health,
    })


@dashboard_router.get("/scan", response_class=HTMLResponse)
async def scan_page(request: Request):
    """Scan form page."""
    response = templates.TemplateResponse("scan.html", {
        "request": request,
        "result": None,
        "csrf_token": "",
        "error_message": None,
    })
    token = _get_csrf_token(request, response)
    # Re-render with the actual token in context
    response = templates.TemplateResponse("scan.html", {
        "request": request,
        "result": None,
        "csrf_token": token,
        "error_message": None,
    })
    # Ensure the cookie is set if it was newly generated
    if not request.cookies.get("csrf_token"):
        response.set_cookie(
            "csrf_token", token, httponly=True, samesite="strict"
        )
    return response


@dashboard_router.post("/scan", response_class=HTMLResponse)
async def scan_submit(
    request: Request,
    url: str = Form(...),
    csrf_token: str = Form(""),
):
    """Trigger a scan and return result partial via HTMX."""
    # CSRF verification
    if not _verify_csrf(request, csrf_token):
        return HTMLResponse(
            content="<p><strong>Error 403:</strong> CSRF token validation failed. "
            "Please reload the page and try again.</p>",
            status_code=403,
        )

    # Server-side URL validation (scheme + SSRF check)
    try:
        validate_scan_url(url)
    except ValueError as e:
        return templates.TemplateResponse("partials/scan_result.html", {
            "request": request,
            "result": {
                "url": url,
                "status": "failed",
                "classification": None,
                "confidence": None,
                "severity_score": None,
                "flags_count": None,
                "flags": None,
                "llm_provider": None,
                "llm_model": None,
                "tokens_input": 0,
                "tokens_output": 0,
                "processing_time_ms": None,
                "error_message": f"Invalid URL: {e}",
            },
        })

    from ..api.main import job_queue, SessionFactory, _calculate_confidence, _save_scan_results
    from ..core.config import get_settings

    settings = get_settings()
    result_data = {
        "url": url,
        "status": "failed",
        "classification": None,
        "confidence": None,
        "severity_score": None,
        "flags_count": None,
        "flags": None,
        "llm_provider": None,
        "llm_model": None,
        "tokens_input": 0,
        "tokens_output": 0,
        "processing_time_ms": None,
        "error_message": None,
    }

    if not job_queue:
        result_data["error_message"] = "Queue not available"
        return templates.TemplateResponse("partials/scan_result.html", {
            "request": request,
            "result": result_data,
        })

    try:
        job = await job_queue.enqueue_scan(url, "summarize")
        result = await job_queue.get_result(
            job.job_id,
            timeout_seconds=settings.redis.job_timeout_seconds,
        )

        if result is None:
            result_data["status"] = "timeout"
        elif result.status == "failed":
            result_data["status"] = "failed"
            result_data["error_message"] = result.error_message
        else:
            confidence = _calculate_confidence(result.severity_score, result.classification)
            await _save_scan_results(url, result, confidence)

            result_data.update({
                "status": "completed",
                "classification": result.classification,
                "confidence": confidence,
                "severity_score": result.severity_score,
                "flags_count": result.flags_count,
                "flags": result.flags,
                "llm_provider": result.llm_provider,
                "llm_model": result.llm_model,
                "tokens_input": result.tokens_input,
                "tokens_output": result.tokens_output,
                "processing_time_ms": result.processing_time_ms,
            })
    except Exception as e:
        result_data["error_message"] = str(e)

    return templates.TemplateResponse("partials/scan_result.html", {
        "request": request,
        "result": result_data,
    })


@dashboard_router.get("/history", response_class=HTMLResponse)
async def history_page(
    request: Request,
    page: int = Query(1, ge=1),
):
    """Paginated scan history."""
    session_factory = _get_session_factory()
    offset = (page - 1) * PAGE_SIZE
    urls = []
    has_next = False

    try:
        async with session_factory() as session:
            result = await session.execute(
                select(URLDB)
                .order_by(URLDB.last_scanned.desc())
                .offset(offset)
                .limit(PAGE_SIZE + 1)
            )
            rows = result.scalars().all()

            if len(rows) > PAGE_SIZE:
                has_next = True
                rows = rows[:PAGE_SIZE]

            for u in rows:
                urls.append({
                    "url": str(u.url),
                    "status": u.current_status.value,
                    "confidence": u.current_confidence,
                    "scan_count": u.scan_count,
                    "last_scanned": _format_datetime(u.last_scanned),
                })
    except Exception:
        pass

    return templates.TemplateResponse("history.html", {
        "request": request,
        "urls": urls,
        "page": page,
        "has_next": has_next,
    })


@dashboard_router.get("/domains", response_class=HTMLResponse)
async def domains_page(request: Request):
    """Domain risk overview."""
    session_factory = _get_session_factory()
    domains = []

    try:
        async with session_factory() as session:
            result = await session.execute(
                select(DomainDB)
                .order_by(DomainDB.risk_score.desc())
                .limit(100)
            )
            rows = result.scalars().all()

            for d in rows:
                domains.append({
                    "domain": d.domain,
                    "risk_score": d.risk_score,
                    "dangerous_count": d.dangerous_urls_count,
                    "suspicious_count": d.suspicious_urls_count,
                    "total_scanned": d.total_urls_scanned,
                    "first_seen": _format_datetime(d.first_seen),
                })
    except Exception:
        pass

    return templates.TemplateResponse("domains.html", {
        "request": request,
        "domains": domains,
    })
