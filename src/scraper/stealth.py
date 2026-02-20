"""Stealth utilities for avoiding bot detection during web scraping.

Provides User-Agent rotation, playwright-stealth integration, and
bot-protection page detection.
"""

import re
from typing import Optional

from ..core.logging import log_debug, log_warning

# Fallback User-Agent strings in case browserforge is unavailable
_FALLBACK_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

# Bot-protection patterns: (compiled_regex, description)
_BOT_PROTECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Cloudflare
    (re.compile(r"checking your browser", re.IGNORECASE), "Cloudflare browser check"),
    (re.compile(r"cf-browser-verification", re.IGNORECASE), "Cloudflare verification"),
    (re.compile(r"cloudflare", re.IGNORECASE), "Cloudflare protection"),
    (re.compile(r"ray id", re.IGNORECASE), "Cloudflare Ray ID"),
    (re.compile(r"enable javascript and cookies", re.IGNORECASE), "Cloudflare JS/cookie requirement"),
    # Akamai
    (re.compile(r"access denied", re.IGNORECASE), "Akamai access denied"),
    (re.compile(r"reference #", re.IGNORECASE), "Akamai reference block"),
    # Generic
    (re.compile(r"please verify you are a human", re.IGNORECASE), "Human verification prompt"),
    (re.compile(r"captcha", re.IGNORECASE), "CAPTCHA challenge"),
    (re.compile(r"bot detection", re.IGNORECASE), "Bot detection page"),
]


def get_random_user_agent() -> str:
    """Generate a realistic Chrome User-Agent string.

    Uses the browserforge library to generate realistic headers. Falls back
    to a hardcoded list of Chrome User-Agents if browserforge is unavailable.

    Returns:
        A Chrome User-Agent string.
    """
    try:
        from browserforge.headers import HeaderGenerator

        generator = HeaderGenerator(
            browser="chrome", os=("windows", "macos", "linux")
        )
        headers = generator.generate()
        ua = headers["user-agent"]
        log_debug("Generated User-Agent via browserforge", user_agent=ua)
        return ua
    except (ImportError, Exception) as exc:
        import random

        log_warning(
            "browserforge unavailable, using fallback User-Agent",
            error=str(exc),
        )
        ua = random.choice(_FALLBACK_USER_AGENTS)
        log_debug("Using fallback User-Agent", user_agent=ua)
        return ua


async def apply_stealth(page) -> None:
    """Apply playwright-stealth patches to a Playwright page.

    Applies various patches to make the browser appear more like a regular
    user's browser, reducing the chance of bot detection.

    Args:
        page: A Playwright page instance to apply stealth patches to.
    """
    try:
        from playwright_stealth import stealth_async

        await stealth_async(page)
        log_debug("Applied playwright-stealth patches")
    except ImportError:
        log_warning(
            "playwright_stealth not installed, skipping stealth patches. "
            "Install with: pip install playwright-stealth"
        )
    except Exception as exc:
        log_warning(
            "Failed to apply stealth patches",
            error=str(exc),
        )


def is_bot_protection_page(
    extracted_text: str, word_count: int
) -> tuple[bool, str]:
    """Detect if the scraped page is a bot-protection or challenge page.

    Checks extracted page text against known bot-protection patterns
    (Cloudflare, Akamai, generic CAPTCHAs). Only flags pages with low
    word counts to avoid false positives on real content that happens
    to mention these services.

    Args:
        extracted_text: The text content extracted from the page.
        word_count: The number of words in the extracted text.

    Returns:
        A tuple of (is_blocked, reason). If the page appears to be a
        bot-protection page, is_blocked is True and reason describes the
        detected pattern. Otherwise returns (False, "").
    """
    if word_count >= 100:
        return (False, "")

    for pattern, description in _BOT_PROTECTION_PATTERNS:
        if pattern.search(extracted_text):
            reason = f"Bot protection detected: {description}"
            log_debug(
                "Bot protection page detected",
                pattern=description,
                word_count=word_count,
            )
            return (True, reason)

    return (False, "")
