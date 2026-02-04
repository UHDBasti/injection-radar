-- InjectionRadar Database Schema
-- PostgreSQL 16+

-- Enum Types
DO $$ BEGIN
    CREATE TYPE classification_enum AS ENUM ('safe', 'suspicious', 'dangerous', 'error', 'pending');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Domains Table
CREATE TABLE IF NOT EXISTS domains (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL UNIQUE,
    first_seen TIMESTAMP NOT NULL DEFAULT NOW(),
    total_urls_scanned INTEGER NOT NULL DEFAULT 0,
    dangerous_urls_count INTEGER NOT NULL DEFAULT 0,
    suspicious_urls_count INTEGER NOT NULL DEFAULT 0,
    risk_score FLOAT NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_domains_domain ON domains(domain);
CREATE INDEX IF NOT EXISTS idx_domains_risk_score ON domains(risk_score);

-- URLs Table
CREATE TABLE IF NOT EXISTS urls (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    domain_id INTEGER REFERENCES domains(id),
    current_status classification_enum NOT NULL DEFAULT 'pending',
    current_confidence FLOAT NOT NULL DEFAULT 0.0,
    first_scanned TIMESTAMP,
    last_scanned TIMESTAMP,
    scan_count INTEGER NOT NULL DEFAULT 0,
    next_scan TIMESTAMP,
    content_hash VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_urls_domain_id ON urls(domain_id);
CREATE INDEX IF NOT EXISTS idx_urls_status ON urls(current_status);
CREATE INDEX IF NOT EXISTS idx_urls_next_scan ON urls(next_scan);

-- Scraped Content Table (Subsystem only!)
CREATE TABLE IF NOT EXISTS scraped_content (
    id SERIAL PRIMARY KEY,
    url_id INTEGER NOT NULL REFERENCES urls(id),
    scraped_at TIMESTAMP NOT NULL DEFAULT NOW(),
    server_ip VARCHAR(45),
    http_status INTEGER NOT NULL,
    response_time_ms INTEGER NOT NULL,
    ssl_valid BOOLEAN,
    raw_html TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    text_length INTEGER NOT NULL,
    word_count INTEGER NOT NULL,
    meta_tags JSONB NOT NULL DEFAULT '{}',
    scripts_content JSONB NOT NULL DEFAULT '[]',
    external_links JSONB NOT NULL DEFAULT '[]',
    content_hash VARCHAR(64) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scraped_content_url_id ON scraped_content(url_id);
CREATE INDEX IF NOT EXISTS idx_scraped_content_hash ON scraped_content(content_hash);

-- LLM Requests Table
CREATE TABLE IF NOT EXISTS llm_requests (
    id SERIAL PRIMARY KEY,
    scraped_content_id INTEGER NOT NULL REFERENCES scraped_content(id),
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL,
    system_prompt TEXT NOT NULL,
    user_prompt TEXT NOT NULL,
    temperature FLOAT NOT NULL DEFAULT 0.1,
    requested_at TIMESTAMP NOT NULL DEFAULT NOW(),
    response_time_ms INTEGER,
    tokens_input INTEGER,
    tokens_output INTEGER,
    cost_estimated FLOAT
);

CREATE INDEX IF NOT EXISTS idx_llm_requests_scraped_content_id ON llm_requests(scraped_content_id);
CREATE INDEX IF NOT EXISTS idx_llm_requests_provider ON llm_requests(provider);

-- LLM Responses Table
CREATE TABLE IF NOT EXISTS llm_responses (
    id SERIAL PRIMARY KEY,
    request_id INTEGER NOT NULL UNIQUE REFERENCES llm_requests(id),
    raw_response TEXT NOT NULL,
    finish_reason VARCHAR(50) NOT NULL,
    tool_calls JSONB NOT NULL DEFAULT '[]',
    has_tool_calls BOOLEAN NOT NULL DEFAULT FALSE
);

-- Scan Results Table (Structured report from Subsystem)
CREATE TABLE IF NOT EXISTS scan_results (
    id SERIAL PRIMARY KEY,
    url_id INTEGER NOT NULL REFERENCES urls(id),
    task_name VARCHAR(50) NOT NULL,
    scanned_at TIMESTAMP NOT NULL DEFAULT NOW(),
    llm_provider VARCHAR(50) NOT NULL,
    llm_model VARCHAR(100) NOT NULL,
    output_length INTEGER NOT NULL,
    output_word_count INTEGER NOT NULL,
    output_format_detected VARCHAR(50) NOT NULL,
    tool_calls_attempted BOOLEAN NOT NULL DEFAULT FALSE,
    tool_calls_count INTEGER NOT NULL DEFAULT 0,
    flags_detected JSONB NOT NULL DEFAULT '[]',
    format_match_score FLOAT NOT NULL DEFAULT 0.0,
    expected_vs_actual_length_ratio FLOAT NOT NULL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_scan_results_url_id ON scan_results(url_id);
CREATE INDEX IF NOT EXISTS idx_scan_results_task ON scan_results(task_name);

-- Analysis Results Table (Final classification from Orchestrator)
CREATE TABLE IF NOT EXISTS analysis_results (
    id SERIAL PRIMARY KEY,
    url_id INTEGER NOT NULL REFERENCES urls(id),
    scan_result_id INTEGER NOT NULL UNIQUE REFERENCES scan_results(id),
    classification classification_enum NOT NULL,
    confidence FLOAT NOT NULL,
    severity_score FLOAT NOT NULL,
    flags_triggered JSONB NOT NULL DEFAULT '[]',
    reasoning TEXT NOT NULL,
    analyzed_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analysis_results_url_id ON analysis_results(url_id);
CREATE INDEX IF NOT EXISTS idx_analysis_results_classification ON analysis_results(classification);

-- Crawl Checkpoints Table
CREATE TABLE IF NOT EXISTS crawl_checkpoints (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    last_processed_index INTEGER NOT NULL,
    last_processed_url TEXT NOT NULL,
    total_in_source INTEGER NOT NULL,
    processed_count INTEGER NOT NULL,
    started_at TIMESTAMP NOT NULL,
    last_updated TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_source ON crawl_checkpoints(source);

-- Useful Views

-- Domain Risk Overview
CREATE OR REPLACE VIEW domain_risk_overview AS
SELECT
    d.domain,
    d.risk_score,
    d.total_urls_scanned,
    d.dangerous_urls_count,
    d.suspicious_urls_count,
    CASE
        WHEN d.total_urls_scanned > 0
        THEN ROUND((d.dangerous_urls_count::FLOAT / d.total_urls_scanned * 100)::NUMERIC, 2)
        ELSE 0
    END as dangerous_percentage
FROM domains d
ORDER BY d.risk_score DESC;

-- Recent Dangerous URLs
CREATE OR REPLACE VIEW recent_dangerous_urls AS
SELECT
    u.url,
    d.domain,
    ar.classification,
    ar.confidence,
    ar.severity_score,
    ar.reasoning,
    ar.analyzed_at
FROM analysis_results ar
JOIN urls u ON ar.url_id = u.id
JOIN domains d ON u.domain_id = d.id
WHERE ar.classification = 'dangerous'
ORDER BY ar.analyzed_at DESC
LIMIT 100;

-- Crawl Progress
CREATE OR REPLACE VIEW crawl_progress AS
SELECT
    source,
    processed_count,
    total_in_source,
    ROUND((processed_count::FLOAT / total_in_source * 100)::NUMERIC, 2) as progress_percentage,
    last_updated,
    completed_at
FROM crawl_checkpoints
ORDER BY last_updated DESC;

-- Grant permissions (adjust user as needed)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO pishield;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pishield;
