"""
Scraper module - Web-Scraping mit Playwright in isolierten Containern.
"""

from .worker import ScraperWorker, worker_main

__all__ = [
    "ScraperWorker",
    "worker_main",
]
