"""
Scraper-Worker für InjectionRadar.

Läuft in isolierten Docker-Containern und scraped Websites mit Playwright.
Speichert Rohdaten direkt in die Datenbank und gibt nur strukturierte
ScanResults an das Hauptsystem zurück.

WICHTIG: Dieser Worker sieht die Rohdaten - das Hauptsystem (Orchestrator) nicht!
Der Orchestrator erhält NUR das strukturierte JobResult über Redis.
"""

import asyncio
import hashlib
import re
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, Browser
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.models import ScrapedContent, ScanResult, RedFlag, RedFlagType, Severity
from ..core.database import (
    ScrapedContentDB,
    URLDB,
    DomainDB,
    get_async_engine,
    get_async_session_factory,
)
from sqlalchemy import select
from ..core.queue import JobQueue, QueueConfig, ScanJob, JobResult
from ..core.logging import log_info, log_error, log_warning, log_debug, log_error_with_trace, setup_logging
from ..llm import AnthropicClient, OpenAIClient, LLMResult, DUMMY_TOOLS
from ..llm.anthropic import (
    SUMMARIZE_SYSTEM_PROMPT,
    SUMMARIZE_USER_PROMPT_TEMPLATE,
)
from ..analysis.detector import RedFlagDetector
from .stealth import get_random_user_agent, apply_stealth, is_bot_protection_page


# Graceful shutdown flag
_shutdown_requested = False


async def get_or_create_url(session: AsyncSession, url: str) -> int:
    """Holt oder erstellt einen URL-Eintrag in der Datenbank.

    Returns:
        Die ID der URL in der Datenbank.
    """
    # Zuerst versuchen, existierende URL zu finden
    result = await session.execute(
        select(URLDB).where(URLDB.url == url)
    )
    existing_url = result.scalar_one_or_none()

    if existing_url:
        return existing_url.id

    # Domain extrahieren
    parsed = urlparse(url)
    domain_name = parsed.netloc

    # Domain holen oder erstellen
    domain_result = await session.execute(
        select(DomainDB).where(DomainDB.domain == domain_name)
    )
    domain = domain_result.scalar_one_or_none()

    if not domain:
        domain = DomainDB(domain=domain_name)
        session.add(domain)
        await session.flush()  # Um domain.id zu bekommen

    # URL erstellen
    url_record = URLDB(
        url=url,
        domain_id=domain.id,
    )
    session.add(url_record)
    await session.flush()  # Um url_record.id zu bekommen

    return url_record.id


class ScraperWorker:
    """Worker zum Scrapen und Analysieren von Websites."""

    def __init__(self):
        self.settings = get_settings()
        self.browser: Optional[Browser] = None
        self.detector = RedFlagDetector()

    async def start(self):
        """Startet den Worker und initialisiert den Browser."""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

    async def stop(self):
        """Stoppt den Worker und schließt den Browser."""
        if self.browser:
            await self.browser.close()

    async def scrape_url(self, url: str) -> ScrapedContent:
        """Scraped eine URL und extrahiert den Content.

        Args:
            url: Die zu scrapende URL.

        Returns:
            ScrapedContent mit allen extrahierten Daten.
        """
        if not self.browser:
            raise RuntimeError("Worker not started. Call start() first.")

        start_time = datetime.now(timezone.utc)
        ua = get_random_user_agent()
        context = await self.browser.new_context(
            user_agent=ua,
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()
        await apply_stealth(page)

        try:
            # Seite laden
            response = await page.goto(
                url,
                timeout=self.settings.scraping.timeout * 1000,
                wait_until="networkidle",
            )

            if not response:
                raise ValueError(f"No response from {url}")

            # Warten auf JavaScript-Rendering
            if self.settings.scraping.render_javascript:
                await page.wait_for_timeout(2000)

            # HTML und Text extrahieren
            raw_html = await page.content()

            # Text mit readability-ähnlicher Extraktion
            extracted_text = await self._extract_text(page, raw_html)

            # Metadaten extrahieren
            meta_tags = await self._extract_meta_tags(page)
            scripts_content = await self._extract_scripts(page)
            external_links = await self._extract_external_links(page, url)

            # Server-IP ermitteln
            server_ip = await self._resolve_ip(url)

            # Hash berechnen
            content_hash = hashlib.sha256(raw_html.encode()).hexdigest()

            # Response-Zeit berechnen
            response_time_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            return ScrapedContent(
                url_id=0,  # Wird später gesetzt
                scraped_at=datetime.utcnow(),  # Naive datetime für DB
                server_ip=server_ip,
                http_status=response.status,
                response_time_ms=response_time_ms,
                ssl_valid=url.startswith("https://"),
                raw_html=raw_html,
                extracted_text=extracted_text,
                text_length=len(extracted_text),
                word_count=len(extracted_text.split()),
                meta_tags=meta_tags,
                scripts_content=scripts_content[:10],  # Max 10 Scripts
                external_links=external_links[:100],  # Max 100 Links
                content_hash=content_hash,
            )

        finally:
            await context.close()

    async def _extract_text(self, page: Page, html: str) -> str:
        """Extrahiert lesbaren Text aus der Seite."""
        # Primaer: readability-lxml fuer bessere Content-Extraktion
        try:
            from readability import Document
            doc = Document(html)
            readable_html = doc.summary()
            soup = BeautifulSoup(readable_html, "lxml")
            text = soup.get_text(separator=" ", strip=True)
            if len(text.split()) > 20:  # Nur nutzen wenn genug Content extrahiert wurde
                text = re.sub(r"\s+", " ", text)
                max_length = self.settings.scraping.max_page_size
                if len(text) > max_length:
                    text = text[:max_length]
                return text
        except Exception:
            pass

        # Fallback: BeautifulSoup (wie bisher)
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        max_length = self.settings.scraping.max_page_size
        if len(text) > max_length:
            text = text[:max_length]
        return text

    async def _extract_meta_tags(self, page: Page) -> dict:
        """Extrahiert Meta-Tags von der Seite."""
        meta_tags = {}

        try:
            metas = await page.query_selector_all("meta")
            for meta in metas:
                name = await meta.get_attribute("name") or await meta.get_attribute("property")
                content = await meta.get_attribute("content")
                if name and content:
                    meta_tags[name] = content[:500]  # Max 500 chars pro Tag
        except Exception:
            pass

        return meta_tags

    async def _extract_scripts(self, page: Page) -> list[str]:
        """Extrahiert Inline-Script-Inhalte."""
        scripts = []

        try:
            script_elements = await page.query_selector_all("script:not([src])")
            for script in script_elements:
                content = await script.inner_text()
                if content and len(content) > 50:  # Nur nicht-triviale Scripts
                    scripts.append(content[:2000])  # Max 2000 chars pro Script
        except Exception:
            pass

        return scripts

    async def _extract_external_links(self, page: Page, base_url: str) -> list[str]:
        """Extrahiert externe Links."""
        links = []
        base_domain = urlparse(base_url).netloc

        try:
            anchors = await page.query_selector_all("a[href]")
            for anchor in anchors:
                href = await anchor.get_attribute("href")
                if href:
                    full_url = urljoin(base_url, href)
                    parsed = urlparse(full_url)
                    if parsed.netloc and parsed.netloc != base_domain:
                        links.append(full_url)
        except Exception:
            pass

        return list(set(links))  # Duplikate entfernen

    async def _resolve_ip(self, url: str) -> Optional[str]:
        """Löst die IP-Adresse einer URL auf."""
        try:
            import socket
            hostname = urlparse(url).netloc
            ip = socket.gethostbyname(hostname)
            return ip
        except Exception:
            return None

    async def run_llm_test(
        self,
        content: ScrapedContent,
        task_name: str = "summarize",
    ) -> ScanResult:
        """Führt einen LLM-Test mit dem gescrapten Content durch.

        Args:
            content: Der gescrapte Content.
            task_name: Name der Test-Aufgabe.

        Returns:
            ScanResult mit den Analyseergebnissen.
        """
        # LLM-Client initialisieren
        if self.settings.anthropic_api_key:
            client = AnthropicClient(
                api_key=self.settings.anthropic_api_key,
                model=self.settings.llm.primary_analyzer,
                max_tokens=self.settings.llm.max_output_tokens,
                temperature=self.settings.llm.temperature,
            )
        elif self.settings.openai_api_key:
            client = OpenAIClient(
                api_key=self.settings.openai_api_key,
                max_tokens=self.settings.llm.max_output_tokens,
                temperature=self.settings.llm.temperature,
            )
        else:
            raise ValueError("No LLM API key configured")

        # Prompt erstellen
        user_prompt = SUMMARIZE_USER_PROMPT_TEMPLATE.format(
            content=content.extracted_text[:self.settings.llm.max_input_tokens * 4]
        )

        # LLM aufrufen MIT Tool-Definitionen (um Tool-Call-Verhalten zu testen)
        result = await client.generate(
            system_prompt=SUMMARIZE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tools=DUMMY_TOOLS,
        )

        # Red Flags erkennen (inkl. Content-Analyse)
        flags = self.detector.detect_all(
            llm_output=result.text,
            tool_calls=result.tool_calls,
            expected_format="text",
            original_content=content.extracted_text,
            raw_html=content.raw_html,
        )

        # Format erkennen
        output_format = self.detector.detect_format(result.text)

        return ScanResult(
            url_id=content.url_id,
            task_name=task_name,
            llm_provider=client.provider_name,
            llm_model=client.model,
            output_length=len(result.text),
            output_word_count=len(result.text.split()),
            output_format_detected=output_format,
            tool_calls_attempted=result.has_tool_calls,
            tool_calls_count=len(result.tool_calls),
            flags_detected=flags,
            format_match_score=self.detector.calculate_format_match(
                result.text, "text"
            ),
            expected_vs_actual_length_ratio=len(result.text) / 500,  # Erwartete ~500 Zeichen
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
            cost_estimated=result.cost_estimated,
        )


def _handle_shutdown_signal(signum, frame):
    """Signal-Handler für graceful shutdown."""
    global _shutdown_requested
    _shutdown_requested = True
    log_info("shutdown_requested", signal=signum)


async def worker_main():
    """Hauptschleife des Workers mit Redis Queue.

    Der Worker:
    1. Holt Jobs aus der Redis Queue
    2. Scraped die Website (speichert Rohdaten in DB)
    3. Führt LLM-Test durch
    4. Sendet NUR strukturiertes JobResult zurück (keine Rohdaten!)
    """
    global _shutdown_requested

    # Structlog nach stderr ausgeben (Docker captured das für Dashboard-Log-Tailing)
    setup_logging(verbose=True)

    # Signal-Handler registrieren
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)

    settings = get_settings()

    # Redis Queue Konfiguration aus Settings
    queue_config = QueueConfig(
        host=settings.redis.host,
        port=settings.redis.port,
        db=settings.redis.db,
        password=settings.redis.password,
        job_timeout_seconds=settings.redis.job_timeout_seconds,
        result_ttl_seconds=settings.redis.result_ttl_seconds,
    )
    queue = JobQueue(queue_config)

    # Datenbank-Verbindung (für Rohdaten-Speicherung)
    engine = get_async_engine(settings.database.url)
    SessionFactory = get_async_session_factory(engine)

    worker = ScraperWorker()

    log_info("worker_starting", redis_host=settings.redis.host, redis_port=settings.redis.port)

    try:
        await worker.start()
        await queue.connect()

        log_info("worker_started", status="ready")
        print(f"Scraper Worker started. Waiting for jobs from Redis queue...")

        while not _shutdown_requested:
            try:
                # Job aus Queue holen (blocking, 5s timeout für shutdown-check)
                job = await queue.dequeue_scan(timeout_seconds=5)

                if job is None:
                    # Timeout, check for shutdown
                    continue

                log_info("job_processing", job_id=job.job_id, url=job.url)
                print(f"Processing job {job.job_id[:8]}...: {job.url}")

                start_time = time.time()

                try:
                    # =========================================================
                    # 1. Website scrapen (Rohdaten bleiben im Subsystem!)
                    # =========================================================
                    content = await worker.scrape_url(job.url)

                    log_info(
                        "website_scraped",
                        job_id=job.job_id,
                        url=job.url,
                        text_length=content.text_length,
                        word_count=content.word_count,
                        http_status=content.http_status,
                    )

                    # =========================================================
                    # 2. Rohdaten in Datenbank speichern (nur Subsystem sieht das!)
                    # =========================================================
                    log_info("saving_to_db", job_id=job.job_id, url=job.url)
                    async with SessionFactory() as session:
                        # URL in DB anlegen oder holen
                        url_id = await get_or_create_url(session, job.url)

                        content_db = ScrapedContentDB(
                            url_id=url_id,
                            scraped_at=content.scraped_at,
                            server_ip=content.server_ip,
                            http_status=content.http_status,
                            response_time_ms=content.response_time_ms,
                            ssl_valid=content.ssl_valid,
                            raw_html=content.raw_html,
                            extracted_text=content.extracted_text,
                            text_length=content.text_length,
                            word_count=content.word_count,
                            meta_tags=content.meta_tags,
                            scripts_content=content.scripts_content,
                            external_links=content.external_links,
                            content_hash=content.content_hash,
                        )
                        session.add(content_db)
                        await session.commit()
                        log_info("scraped_content_saved", job_id=job.job_id, url_id=url_id)

                    # =========================================================
                    # 3. Check HTTP status and content before LLM test
                    # =========================================================
                    processing_time_ms = int((time.time() - start_time) * 1000)

                    if content.http_status >= 400:
                        log_warning(
                            "http_error_skipping_llm",
                            job_id=job.job_id,
                            url=job.url,
                            http_status=content.http_status,
                        )
                        result = JobResult(
                            job_id=job.job_id,
                            url=job.url,
                            status="completed",
                            severity_score=0.0,
                            flags_count=0,
                            classification="error",
                            flags=[],
                            error_message=f"HTTP {content.http_status} response",
                            processing_time_ms=processing_time_ms,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                        )
                    elif content.word_count == 0:
                        log_warning(
                            "empty_content_skipping_llm",
                            job_id=job.job_id,
                            url=job.url,
                        )
                        result = JobResult(
                            job_id=job.job_id,
                            url=job.url,
                            status="completed",
                            severity_score=0.0,
                            flags_count=0,
                            classification="error",
                            flags=[],
                            error_message="Empty page content (0 words)",
                            processing_time_ms=processing_time_ms,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                        )
                    else:
                        # =========================================================
                        # 3b. Check for bot protection before LLM test
                        # =========================================================
                        is_blocked, block_reason = is_bot_protection_page(
                            content.extracted_text, content.word_count
                        )
                        if is_blocked:
                            log_warning(
                                "bot_protection_detected",
                                job_id=job.job_id,
                                url=job.url,
                                reason=block_reason,
                            )
                            result = JobResult(
                                job_id=job.job_id,
                                url=job.url,
                                status="completed",
                                severity_score=0.0,
                                flags_count=0,
                                classification="error",
                                flags=[],
                                error_message=block_reason,
                                processing_time_ms=processing_time_ms,
                                completed_at=datetime.now(timezone.utc).isoformat(),
                            )
                        else:
                            # =========================================================
                            # 3c. Content-basierte Injection-Erkennung (VOR LLM-Test)
                            # =========================================================
                            content_flags = worker.detector.detect_content_injection(
                                extracted_text=content.extracted_text,
                                raw_html=content.raw_html,
                            )
                            if content_flags:
                                log_info(
                                    "content_injection_detected",
                                    job_id=job.job_id,
                                    url=job.url,
                                    content_flags_count=len(content_flags),
                                    flags=[f.type.value for f in content_flags],
                                )

                            # =========================================================
                            # 3d. LLM-Test durchführen (only for valid responses)
                            # =========================================================
                            log_info("llm_test_started", job_id=job.job_id, url=job.url)
                            scan_result = await worker.run_llm_test(content, task_name=job.task_name)

                            # Content-Flags mit LLM-Flags zusammenführen (Duplikate vermeiden)
                            existing_types = {
                                (f.type, f.description) for f in scan_result.flags_detected
                            }
                            for flag in content_flags:
                                if (flag.type, flag.description) not in existing_types:
                                    scan_result.flags_detected.append(flag)

                            log_info(
                                "llm_test_completed",
                                job_id=job.job_id,
                                flags_count=len(scan_result.flags_detected),
                                tool_calls=scan_result.tool_calls_count,
                                llm_provider=scan_result.llm_provider,
                                llm_model=scan_result.llm_model,
                                tokens_input=scan_result.tokens_input,
                                tokens_output=scan_result.tokens_output,
                                cost_estimated=scan_result.cost_estimated,
                            )

                            # =========================================================
                            # 4. NUR strukturiertes Ergebnis zurücksenden!
                            #    KEINE Rohdaten (raw_html, extracted_text) im Result!
                            # =========================================================

                            # Severity Score berechnen
                            severity_score = worker.detector.calculate_severity_score(
                                scan_result.flags_detected
                            )

                            # Classification ableiten
                            if severity_score >= 6.0:
                                classification = "dangerous"
                            elif severity_score >= 3.0:
                                classification = "suspicious"
                            elif severity_score > 0:
                                classification = "suspicious"
                            else:
                                classification = "safe"

                            # JobResult erstellen (NUR strukturierte Daten!)
                            result = JobResult(
                                job_id=job.job_id,
                                url=job.url,
                                status="completed",
                                severity_score=severity_score,
                                flags_count=len(scan_result.flags_detected),
                                classification=classification,
                                flags=[
                                    {
                                        "type": flag.type.value,
                                        "severity": flag.severity.value,
                                        "description": flag.description,
                                    }
                                    for flag in scan_result.flags_detected
                                ],
                                llm_provider=scan_result.llm_provider,
                                llm_model=scan_result.llm_model,
                                tokens_input=scan_result.tokens_input,
                                tokens_output=scan_result.tokens_output,
                                cost_estimated=scan_result.cost_estimated,
                                processing_time_ms=processing_time_ms,
                                completed_at=datetime.now(timezone.utc).isoformat(),
                            )

                    # Ergebnis in Redis speichern
                    await queue.set_result(result)

                    log_info(
                        "job_completed",
                        job_id=job.job_id,
                        severity=result.severity_score,
                        classification=result.classification,
                        processing_time_ms=result.processing_time_ms,
                        tokens_input=result.tokens_input,
                        tokens_output=result.tokens_output,
                        cost_estimated=result.cost_estimated,
                    )
                    print(f"Job {job.job_id[:8]}... completed: {result.classification} (severity: {result.severity_score:.1f}, tokens: {result.tokens_input}+{result.tokens_output})")

                except Exception as e:
                    # Fehler-Result senden
                    log_error("job_failed", job_id=job.job_id, error_message=str(e))
                    log_error_with_trace("job_failed_trace", e)

                    error_result = JobResult(
                        job_id=job.job_id,
                        url=job.url,
                        status="failed",
                        classification="error",
                        error_message=str(e),
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    await queue.set_result(error_result)

                    print(f"Job {job.job_id[:8]}... failed: {e}")

            except Exception as e:
                log_error_with_trace("worker_loop_error", e)
                await asyncio.sleep(1)  # Kurze Pause bei Fehlern

    finally:
        log_info("worker_stopping")
        await worker.stop()
        await queue.disconnect()
        log_info("worker_stopped")
        print("Worker stopped.")


async def run_single_scan(url: str, queue: JobQueue) -> JobResult:
    """Führt einen einzelnen Scan durch (für Tests/CLI).

    Diese Funktion umgeht die Queue und führt direkt einen Scan durch.
    Nützlich für lokale Entwicklung ohne Docker/Redis.
    """
    worker = ScraperWorker()
    await worker.start()

    try:
        content = await worker.scrape_url(url)

        # Content-basierte Injection-Erkennung (VOR LLM-Test)
        content_flags = worker.detector.detect_content_injection(
            extracted_text=content.extracted_text,
            raw_html=content.raw_html,
        )

        scan_result = await worker.run_llm_test(content)

        # Content-Flags mit LLM-Flags zusammenführen (Duplikate vermeiden)
        existing_types = {
            (f.type, f.description) for f in scan_result.flags_detected
        }
        for flag in content_flags:
            if (flag.type, flag.description) not in existing_types:
                scan_result.flags_detected.append(flag)

        severity_score = worker.detector.calculate_severity_score(
            scan_result.flags_detected
        )

        if severity_score >= 6.0:
            classification = "dangerous"
        elif severity_score >= 3.0:
            classification = "suspicious"
        else:
            classification = "safe"

        return JobResult(
            job_id="local-scan",
            url=url,
            status="completed",
            severity_score=severity_score,
            flags_count=len(scan_result.flags_detected),
            classification=classification,
            flags=[
                {
                    "type": flag.type.value,
                    "severity": flag.severity.value,
                    "description": flag.description,
                }
                for flag in scan_result.flags_detected
            ],
            llm_provider=scan_result.llm_provider,
            llm_model=scan_result.llm_model,
            tokens_input=scan_result.tokens_input,
            tokens_output=scan_result.tokens_output,
            cost_estimated=scan_result.cost_estimated,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(worker_main())
