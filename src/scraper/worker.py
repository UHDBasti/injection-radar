"""
Scraper-Worker für InjectionRadar.

Läuft in isolierten Docker-Containern und scraped Websites mit Playwright.
Speichert Rohdaten direkt in die Datenbank und gibt nur strukturierte
ScanResults an das Hauptsystem zurück.
"""

import asyncio
import hashlib
import re
from datetime import datetime
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
    get_async_engine,
    get_async_session_factory,
)
from ..llm import AnthropicClient, OpenAIClient, LLMResult, DUMMY_TOOLS
from ..llm.anthropic import (
    SUMMARIZE_SYSTEM_PROMPT,
    SUMMARIZE_USER_PROMPT_TEMPLATE,
)
from ..analysis.detector import RedFlagDetector


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

        start_time = datetime.utcnow()
        context = await self.browser.new_context(
            user_agent=self.settings.scraping.user_agent,
        )
        page = await context.new_page()

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
            response_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return ScrapedContent(
                url_id=0,  # Wird später gesetzt
                scraped_at=datetime.utcnow(),
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
        soup = BeautifulSoup(html, "lxml")

        # Entferne Script und Style Tags
        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()

        # Text extrahieren
        text = soup.get_text(separator=" ", strip=True)

        # Mehrfache Whitespaces entfernen
        text = re.sub(r"\s+", " ", text)

        # Auf maximale Länge beschränken
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

        # Red Flags erkennen
        flags = self.detector.detect_all(
            llm_output=result.text,
            tool_calls=result.tool_calls,
            expected_format="text",
            original_content=content.extracted_text,
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
        )


async def worker_main():
    """Hauptschleife des Workers."""
    settings = get_settings()

    # Datenbank-Verbindung
    engine = get_async_engine(settings.database.url)
    SessionFactory = get_async_session_factory(engine)

    worker = ScraperWorker()
    await worker.start()

    print(f"Scraper Worker started. Polling for jobs...")

    try:
        while True:
            # TODO: Jobs aus Redis-Queue holen
            # Für jetzt: Simple Polling aus der DB
            async with SessionFactory() as session:
                # Hole nächste URL mit Status PENDING
                result = await session.execute(
                    """
                    SELECT id, url FROM urls
                    WHERE current_status = 'pending'
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                )
                row = result.fetchone()

                if row:
                    url_id, url = row
                    print(f"Processing: {url}")

                    try:
                        # Scrape
                        content = await worker.scrape_url(url)
                        content.url_id = url_id

                        # In DB speichern
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

                        # LLM Test
                        scan_result = await worker.run_llm_test(content)

                        # TODO: ScanResult an Orchestrator senden
                        print(f"Scan complete: {len(scan_result.flags_detected)} flags detected")

                        await session.commit()

                    except Exception as e:
                        print(f"Error processing {url}: {e}")
                        await session.rollback()
                else:
                    # Keine Jobs, warten
                    await asyncio.sleep(5)

    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(worker_main())
