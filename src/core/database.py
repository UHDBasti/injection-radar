"""
SQLAlchemy Datenbankmodelle für InjectionRadar.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# Verwende JSON für SQLite-Kompatibilität, JSONB für PostgreSQL
def get_json_type(url: str):
    """Gibt den richtigen JSON-Typ basierend auf der DB zurück."""
    if "postgresql" in url:
        return JSONB
    return JSON

# Default zu JSON für SQLite-Kompatibilität
JSONType = JSON
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from .models import Classification, RedFlagType, Severity


class Base(DeclarativeBase):
    """Basis für alle SQLAlchemy Models."""
    pass


class DomainDB(Base):
    """Domain mit aggregierten Statistiken."""
    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domain = Column(String(255), unique=True, nullable=False, index=True)
    first_seen = Column(DateTime, default=datetime.utcnow, nullable=False)
    total_urls_scanned = Column(Integer, default=0, nullable=False)
    dangerous_urls_count = Column(Integer, default=0, nullable=False)
    suspicious_urls_count = Column(Integer, default=0, nullable=False)
    risk_score = Column(Float, default=0.0, nullable=False)

    # Relationships
    urls = relationship("URLDB", back_populates="domain")

    __table_args__ = (
        Index("idx_domains_risk_score", "risk_score"),
    )


class URLDB(Base):
    """Eine zu scannende URL."""
    __tablename__ = "urls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(Text, unique=True, nullable=False)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=True, index=True)

    # Status (values_callable damit .value statt Name verwendet wird)
    current_status = Column(
        Enum(Classification, name="classification_enum", values_callable=lambda x: [e.value for e in x]),
        default=Classification.PENDING,
        nullable=False,
    )
    current_confidence = Column(Float, default=0.0, nullable=False)

    # Crawl-Management
    first_scanned = Column(DateTime, nullable=True)
    last_scanned = Column(DateTime, nullable=True)
    scan_count = Column(Integer, default=0, nullable=False)
    next_scan = Column(DateTime, nullable=True)

    # Content Hash für Change-Detection
    content_hash = Column(String(64), nullable=True)

    # Relationships
    domain = relationship("DomainDB", back_populates="urls")
    scraped_contents = relationship("ScrapedContentDB", back_populates="url")
    scan_results = relationship("ScanResultDB", back_populates="url")
    analysis_results = relationship("AnalysisResultDB", back_populates="url")

    __table_args__ = (
        Index("idx_urls_status", "current_status"),
        Index("idx_urls_next_scan", "next_scan"),
    )


class ScrapedContentDB(Base):
    """Gescrapeter Inhalt einer Website (nur Subsystem!)."""
    __tablename__ = "scraped_content"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url_id = Column(Integer, ForeignKey("urls.id"), nullable=False, index=True)
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Server-Info
    server_ip = Column(String(45), nullable=True)  # IPv6 max length
    http_status = Column(Integer, nullable=False)
    response_time_ms = Column(Integer, nullable=False)
    ssl_valid = Column(Boolean, nullable=True)

    # Content
    raw_html = Column(Text, nullable=False)
    extracted_text = Column(Text, nullable=False)
    text_length = Column(Integer, nullable=False)
    word_count = Column(Integer, nullable=False)

    # Extrahierte Elemente (JSONB für PostgreSQL)
    meta_tags = Column(JSON, default=dict, nullable=False)
    scripts_content = Column(JSON, default=list, nullable=False)
    external_links = Column(JSON, default=list, nullable=False)

    # Hash
    content_hash = Column(String(64), nullable=False)

    # Relationships
    url = relationship("URLDB", back_populates="scraped_contents")
    llm_requests = relationship("LLMRequestDB", back_populates="scraped_content")

    __table_args__ = (
        Index("idx_scraped_content_hash", "content_hash"),
    )


class LLMRequestDB(Base):
    """Ein Request an ein LLM."""
    __tablename__ = "llm_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scraped_content_id = Column(
        Integer, ForeignKey("scraped_content.id"), nullable=False, index=True
    )

    # LLM Info
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False)  # "subsystem" oder "analyzer"

    # Request
    system_prompt = Column(Text, nullable=False)
    user_prompt = Column(Text, nullable=False)
    temperature = Column(Float, default=0.1, nullable=False)

    # Timing
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    response_time_ms = Column(Integer, nullable=True)

    # Tokens
    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)
    cost_estimated = Column(Float, nullable=True)

    # Relationships
    scraped_content = relationship("ScrapedContentDB", back_populates="llm_requests")
    response = relationship("LLMResponseDB", back_populates="request", uselist=False)

    __table_args__ = (
        Index("idx_llm_requests_provider", "provider"),
    )


class LLMResponseDB(Base):
    """Antwort von einem LLM."""
    __tablename__ = "llm_responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(
        Integer, ForeignKey("llm_requests.id"), unique=True, nullable=False
    )

    # Response
    raw_response = Column(Text, nullable=False)
    finish_reason = Column(String(50), nullable=False)

    # Tool Calls (Red Flag!)
    tool_calls = Column(JSON, default=list, nullable=False)
    has_tool_calls = Column(Boolean, default=False, nullable=False)

    # Relationships
    request = relationship("LLMRequestDB", back_populates="response")


class ScanResultDB(Base):
    """Strukturierter Report vom Subsystem."""
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url_id = Column(Integer, ForeignKey("urls.id"), nullable=False, index=True)
    task_name = Column(String(50), nullable=False)
    scanned_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # LLM Info
    llm_provider = Column(String(50), nullable=False)
    llm_model = Column(String(100), nullable=False)

    # Output-Analyse
    output_length = Column(Integer, nullable=False)
    output_word_count = Column(Integer, nullable=False)
    output_format_detected = Column(String(50), nullable=False)

    # LLM Output Text (die Zusammenfassung die das Test-LLM erzeugt hat)
    llm_output_text = Column(Text, nullable=True)

    # Flags
    tool_calls_attempted = Column(Boolean, default=False, nullable=False)
    tool_calls_count = Column(Integer, default=0, nullable=False)

    # Red Flags (JSONB für flexible Struktur)
    flags_detected = Column(JSON, default=list, nullable=False)

    # Metriken
    format_match_score = Column(Float, default=0.0, nullable=False)
    expected_vs_actual_length_ratio = Column(Float, default=1.0, nullable=False)

    # Relationships
    url = relationship("URLDB", back_populates="scan_results")
    analysis_result = relationship(
        "AnalysisResultDB", back_populates="scan_result", uselist=False
    )

    __table_args__ = (
        Index("idx_scan_results_task", "task_name"),
    )


class AnalysisResultDB(Base):
    """Finale Analyse vom Hauptsystem."""
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url_id = Column(Integer, ForeignKey("urls.id"), nullable=False, index=True)
    scan_result_id = Column(
        Integer, ForeignKey("scan_results.id"), unique=True, nullable=False
    )

    # Klassifizierung (values_callable damit .value statt Name verwendet wird)
    classification = Column(
        Enum(Classification, name="classification_enum", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    confidence = Column(Float, nullable=False)
    severity_score = Column(Float, nullable=False)

    # Details
    flags_triggered = Column(JSON, default=list, nullable=False)
    reasoning = Column(Text, nullable=False)

    # Timestamps
    analyzed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    url = relationship("URLDB", back_populates="analysis_results")
    scan_result = relationship("ScanResultDB", back_populates="analysis_result")


class CrawlCheckpointDB(Base):
    """Checkpoint für Crawl-Fortschritt."""
    __tablename__ = "crawl_checkpoints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(255), nullable=False, unique=True, index=True)

    # Position
    last_processed_index = Column(Integer, nullable=False)
    last_processed_url = Column(Text, nullable=False)

    # Status
    total_in_source = Column(Integer, nullable=False)
    processed_count = Column(Integer, nullable=False)

    # Timestamps
    started_at = Column(DateTime, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = ()


# Database Connection Utilities

def get_sync_engine(database_url: str):
    """Erstellt eine synchrone Engine."""
    if "sqlite" in database_url:
        return create_engine(database_url, connect_args={"check_same_thread": False})
    return create_engine(database_url, pool_pre_ping=True)


def get_async_engine(database_url: str):
    """Erstellt eine asynchrone Engine."""
    if "sqlite" in database_url:
        # SQLite async URL
        async_url = database_url.replace("sqlite:///", "sqlite+aiosqlite:///")
        return create_async_engine(async_url)
    # PostgreSQL async URL
    async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    return create_async_engine(async_url, pool_pre_ping=True)


def get_async_session_factory(engine):
    """Erstellt eine Session Factory für async Operationen."""
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db(engine):
    """Initialisiert die Datenbank (erstellt alle Tabellen)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
