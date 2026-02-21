"""
Core module - Datenmodelle, Enums, und gemeinsame Utilities.
"""

from .models import (
    URL,
    Domain,
    ScanResult,
    LLMRequest,
    LLMResponse,
    ScrapedContent,
    AnalysisResult,
    CrawlCheckpoint,
    RedFlag,
    RedFlagType,
    Classification,
    Severity,
)
from .checkpoint import CheckpointManager
from .config import Settings, get_settings
from .database import (
    Base,
    DomainDB,
    URLDB,
    ScrapedContentDB,
    LLMRequestDB,
    LLMResponseDB,
    ScanResultDB,
    AnalysisResultDB,
    CrawlCheckpointDB,
    get_sync_engine,
    get_async_engine,
    get_async_session_factory,
    init_db,
)

__all__ = [
    # Pydantic Models
    "URL",
    "Domain",
    "ScanResult",
    "LLMRequest",
    "LLMResponse",
    "ScrapedContent",
    "AnalysisResult",
    "CrawlCheckpoint",
    "RedFlag",
    "RedFlagType",
    "Classification",
    "Severity",
    # Checkpoint
    "CheckpointManager",
    # Config
    "Settings",
    "get_settings",
    # SQLAlchemy Models
    "Base",
    "DomainDB",
    "URLDB",
    "ScrapedContentDB",
    "LLMRequestDB",
    "LLMResponseDB",
    "ScanResultDB",
    "AnalysisResultDB",
    "CrawlCheckpointDB",
    # Database Utils
    "get_sync_engine",
    "get_async_engine",
    "get_async_session_factory",
    "init_db",
]
