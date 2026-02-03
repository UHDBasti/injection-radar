"""
Datenmodelle für Prompt Injection Shield.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


class Classification(str, Enum):
    """Klassifizierung einer URL nach Scan."""
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    DANGEROUS = "dangerous"
    ERROR = "error"
    PENDING = "pending"


class Severity(str, Enum):
    """Schweregrad eines Red Flags."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RedFlagType(str, Enum):
    """Arten von erkannten Red Flags."""
    TOOL_CALL = "tool_call"
    CODE_EXECUTION = "code_execution"
    SYSTEM_PROMPT_LEAK = "system_prompt_leak"
    DIRECT_INSTRUCTIONS = "direct_instructions"
    FORMAT_DEVIATION = "format_deviation"
    EXTERNAL_URLS = "external_urls"
    UNEXPECTED_DATA = "unexpected_data"
    HALLUCINATION = "hallucination"
    SENTIMENT_SHIFT = "sentiment_shift"


class RedFlag(BaseModel):
    """Ein erkanntes Red Flag."""
    type: RedFlagType
    severity: Severity
    description: str
    evidence: Optional[str] = None  # Konkreter Beweis aus dem Output


class Domain(BaseModel):
    """Eine Domain mit aggregierten Statistiken."""
    id: Optional[int] = None
    domain: str
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    total_urls_scanned: int = 0
    dangerous_urls_count: int = 0
    suspicious_urls_count: int = 0
    risk_score: float = 0.0  # 0.0 - 1.0


class URL(BaseModel):
    """Eine zu scannende URL."""
    id: Optional[int] = None
    url: HttpUrl
    domain_id: Optional[int] = None

    # Status
    current_status: Classification = Classification.PENDING
    current_confidence: float = 0.0

    # Crawl-Management
    first_scanned: Optional[datetime] = None
    last_scanned: Optional[datetime] = None
    scan_count: int = 0
    next_scan: Optional[datetime] = None

    # Content Hash für Change-Detection
    content_hash: Optional[str] = None


class ScrapedContent(BaseModel):
    """Gescrapeter Inhalt einer Website."""
    url_id: int
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    # Server-Info
    server_ip: Optional[str] = None
    http_status: int
    response_time_ms: int
    ssl_valid: Optional[bool] = None

    # Content
    raw_html: str
    extracted_text: str
    text_length: int
    word_count: int

    # Extrahierte Elemente
    meta_tags: dict = Field(default_factory=dict)
    scripts_content: list[str] = Field(default_factory=list)
    external_links: list[str] = Field(default_factory=list)

    # Hash
    content_hash: str


class LLMRequest(BaseModel):
    """Ein Request an ein LLM."""
    id: Optional[int] = None
    scraped_content_id: int

    # LLM Info
    provider: str  # "anthropic", "openai", "google", etc.
    model: str
    role: str  # "subsystem" oder "analyzer"

    # Request
    system_prompt: str
    user_prompt: str
    temperature: float = 0.1

    # Timing
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    response_time_ms: Optional[int] = None

    # Tokens
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    cost_estimated: Optional[float] = None


class LLMResponse(BaseModel):
    """Antwort von einem LLM."""
    id: Optional[int] = None
    request_id: int

    # Response
    raw_response: str
    finish_reason: str  # "stop", "length", "tool_calls", etc.

    # Tool Calls (Red Flag!)
    tool_calls: list[dict] = Field(default_factory=list)
    has_tool_calls: bool = False


class ScanResult(BaseModel):
    """Strukturierter Report vom Subsystem ans Hauptsystem.

    WICHTIG: Dies ist das EINZIGE was das Hauptsystem vom Subsystem bekommt!
    Keine Rohdaten, kein HTML, kein Originaltext.
    """
    url_id: int
    task_name: str  # z.B. "summarize"

    # LLM Info
    llm_provider: str
    llm_model: str

    # Output-Analyse (KEIN Rohtext!)
    output_length: int
    output_word_count: int
    output_format_detected: str  # "text", "list", "code", etc.

    # Flags
    tool_calls_attempted: bool = False
    tool_calls_count: int = 0

    # Red Flags
    flags_detected: list[RedFlag] = Field(default_factory=list)

    # Metriken
    format_match_score: float = 0.0  # 0.0 - 1.0
    expected_vs_actual_length_ratio: float = 1.0


class AnalysisResult(BaseModel):
    """Finale Analyse vom Hauptsystem."""
    id: Optional[int] = None
    url_id: int
    scan_result_id: int

    # Klassifizierung
    classification: Classification
    confidence: float  # 0.0 - 1.0
    severity_score: float  # 0.0 - 10.0

    # Details
    flags_triggered: list[RedFlag] = Field(default_factory=list)
    reasoning: str  # Erklärung der Klassifizierung

    # Timestamps
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)


class CrawlCheckpoint(BaseModel):
    """Checkpoint für Crawl-Fortschritt."""
    id: Optional[int] = None
    source: str  # "tranco", "wikipedia", etc.

    # Position
    last_processed_index: int
    last_processed_url: str

    # Status
    total_in_source: int
    processed_count: int

    # Timestamps
    started_at: datetime
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
