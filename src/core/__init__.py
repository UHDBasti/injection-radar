"""
Core module - Datenmodelle, Enums, und gemeinsame Utilities.
"""

from .models import (
    URL,
    Domain,
    ScanResult,
    LLMResponse,
    AnalysisResult,
    RedFlag,
    Classification,
    Severity,
)
from .config import Settings, get_settings

__all__ = [
    "URL",
    "Domain",
    "ScanResult",
    "LLMResponse",
    "AnalysisResult",
    "RedFlag",
    "Classification",
    "Severity",
    "Settings",
    "get_settings",
]
