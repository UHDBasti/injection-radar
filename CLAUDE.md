# InjectionRadar - Claude Code Projektdokumentation

> **Für Claude Code:** Diese Datei enthält alle wichtigen Informationen über das Projekt.
> Lies sie vollständig, bevor du Code schreibst oder änderst.

---

## 🎯 Projektübersicht

**InjectionRadar** ist ein System zur automatischen Erkennung von Prompt Injection in Web-Inhalten. Es funktioniert wie ein "Virenscanner für AI-Agents" – testet Websites proaktiv und katalogisiert gefährliche Quellen.

### Kernkonzept
```
Website → Scraper (Docker) → Test-LLM → Red-Flag Detection → Klassifizierung → Datenbank
```

---

## ⚠️ KRITISCHE SICHERHEITSARCHITEKTUR

**WICHTIG:** Das System hat ein Zwei-System-Design aus Sicherheitsgründen:

### Hauptsystem (Orchestrator)
- **DARF NIEMALS** gescrapte Rohdaten (HTML, Text) verarbeiten
- Sieht **NUR** strukturierte Reports vom Subsystem
- Kommuniziert via Redis Queue mit dem Subsystem
- Speichert Klassifizierungen in der Datenbank

### Subsystem (Scraper in Docker)
- Läuft in isolierten Docker-Containern (read-only, no-new-privileges)
- Scraped Websites mit Playwright und führt LLM-Tests durch
- Speichert Rohdaten **DIREKT** in die Datenbank
- Gibt nur `JobResult` (strukturierter Report) ans Hauptsystem zurück

**Grund:** Wenn das Hauptsystem Rohdaten verarbeiten würde, könnte es selbst Opfer von Prompt Injection werden!

---

## 📁 Projektstruktur

```
injection-radar/
├── CLAUDE.md              # Diese Datei (für Claude Code)
├── README.md              # Projekt-Dokumentation
├── pyproject.toml         # Python Package Config
├── requirements.txt       # Python Dependencies
├── .env                   # API Keys (nicht committen!)
│
├── docker/
│   ├── docker-compose.yml     # Komplettes Docker Setup
│   ├── Dockerfile.orchestrator
│   └── Dockerfile.scraper
│
├── src/
│   ├── core/                  # Kernlogik
│   │   ├── models.py          # Pydantic Datenmodelle
│   │   ├── config.py          # Konfigurationsmanagement
│   │   ├── database.py        # SQLAlchemy Models
│   │   ├── queue.py           # Redis Job Queue
│   │   ├── logging.py         # Strukturiertes Logging
│   │   └── startup.py         # Docker Service Management
│   │
│   ├── scraper/               # Web-Scraping (Subsystem)
│   │   └── worker.py          # Playwright Scraper Worker
│   │
│   ├── llm/                   # LLM-Provider
│   │   ├── base.py            # Base-Klasse
│   │   ├── anthropic.py       # Claude Integration
│   │   └── openai.py          # OpenAI Integration
│   │
│   ├── analysis/              # Red-Flag Detection
│   │   └── detector.py        # Pattern-Analyse
│   │
│   ├── cli/                   # Command Line Interface
│   │   ├── main.py            # Typer CLI
│   │   └── interactive.py     # Interaktive Shell
│   │
│   ├── api/                   # REST API (Orchestrator)
│   │   └── main.py            # FastAPI Server
│   │
│   └── mcp/                   # MCP Server für AI-Tools
│       └── server.py          # MCP Integration
│
└── tests/                     # Tests
```

---

## 🚀 Verwendung

### Starten
```bash
# Interaktive Shell (startet automatisch Docker Services)
injection-radar

# Oder direkt mit Typer CLI
injection-radar scan https://example.com
```

### CLI-Befehle
| Befehl | Beschreibung |
|--------|--------------|
| `scan <url>` | Scannt eine URL |
| `scan <url1> <url2> ...` | Scannt mehrere URLs parallel (max 10) |
| `scan list <file.csv>` | Scannt URLs aus einer CSV-Datei |
| `scan <url> --local` | Lokaler Scan ohne Docker |
| `scan <url> --quick` | Schneller Pattern-Scan ohne LLM |
| `history [n]` | Zeigt die letzten n Scans |
| `status` | Zeigt den aktuellen Status |
| `services` | Zeigt Docker-Service-Status |
| `config` | Öffnet den Konfigurations-Wizard |

### API Endpoints
| Endpoint | Methode | Beschreibung |
|----------|---------|--------------|
| `/scan` | POST | Scannt eine URL |
| `/history` | GET | Scan-Historie |
| `/url/status` | GET | Status einer URL |
| `/domains/dangerous` | GET | Gefährliche Domains |
| `/health` | GET | Health Check |

---

## 🔧 Wichtige Datenmodelle

### `JobResult` - Report vom Subsystem
```python
class JobResult(BaseModel):
    """Ergebnis eines Scan-Jobs (nur strukturierte Daten!)."""
    job_id: str
    url: str
    status: str  # "completed", "failed", "timeout"
    severity_score: float
    flags_count: int
    flags: list[dict]
    classification: str  # "safe", "suspicious", "dangerous"
    llm_provider: str
    llm_model: str
    processing_time_ms: int
```

### `Classification` - Ergebnis
```python
class Classification(str, Enum):
    SAFE = "safe"           # ✅ Keine Probleme erkannt
    SUSPICIOUS = "suspicious"  # ⚠️ Verdächtig, nicht eindeutig
    DANGEROUS = "dangerous"    # 🚨 Klare Prompt Injection
    ERROR = "error"         # ❌ Scan fehlgeschlagen
    PENDING = "pending"     # ⏳ Noch nicht gescannt
```

### `RedFlagType` - Erkannte Probleme
```python
class RedFlagType(str, Enum):
    TOOL_CALL = "tool_call"              # 🔴 CRITICAL
    CODE_EXECUTION = "code_execution"    # 🔴 CRITICAL
    SYSTEM_PROMPT_LEAK = "system_prompt_leak"  # 🟠 HIGH
    DIRECT_INSTRUCTIONS = "direct_instructions"  # 🟠 HIGH
    FORMAT_DEVIATION = "format_deviation"  # 🟡 MEDIUM
    EXTERNAL_URLS = "external_urls"      # 🟡 MEDIUM
    HALLUCINATION = "hallucination"      # 🔵 LOW
    SENTIMENT_SHIFT = "sentiment_shift"  # 🔵 LOW
```

---

## 🐳 Docker Services

```bash
# Services werden automatisch beim Start von injection-radar gestartet

# Manuell starten
cd docker && docker compose up -d

# Logs anzeigen
docker compose logs -f orchestrator

# Status prüfen
docker compose ps

# Alles stoppen
docker compose down

# Volumes löschen (Datenbank reset)
docker compose down -v
```

### Container
| Container | Port | Beschreibung |
|-----------|------|--------------|
| pishield-db | 5432 | PostgreSQL Datenbank |
| pishield-redis | 6379 | Redis Job Queue |
| pishield-orchestrator | 8000 | FastAPI Orchestrator |
| docker-scraper-1/2 | - | Playwright Scraper Workers |

---

## 📊 Datenbank

### Wichtige Tabellen
- `domains` - Aggregierte Domain-Statistiken
- `urls` - Einzelne URLs mit Status
- `scraped_content` - Rohdaten (nur Subsystem!)
- `scan_results` - Strukturierte Reports
- `analysis_results` - Finale Klassifizierungen

### Direkter Zugriff
```bash
docker exec -it pishield-db psql -U pishield -d pishield
```

---

## 🔐 Sicherheitsregeln

1. **NIEMALS** API-Keys in Code oder Commits
2. **NIEMALS** Rohdaten im Hauptsystem verarbeiten
3. **IMMER** strukturierte Reports verwenden
4. **IMMER** Input validieren (Pydantic)
5. **IMMER** Sandbox-Container isoliert halten
6. **IMMER** `datetime.utcnow()` für DB-Timestamps (nicht timezone-aware!)

---

## 📝 Code-Konventionen

### Python Style
- Python 3.11+
- Type Hints überall
- Pydantic für Datenvalidierung
- async/await für I/O-Operationen
- Docstrings im Google-Style

### Naming
- Dateien: `snake_case.py`
- Klassen: `PascalCase`
- Funktionen/Variablen: `snake_case`
- Konstanten: `UPPER_SNAKE_CASE`

### Bekannte Fallstricke
- PostgreSQL `TIMESTAMP WITHOUT TIME ZONE` braucht naive datetimes (`datetime.utcnow()`)
- `dict.get(key, default)` gibt default nur zurück wenn key nicht existiert, nicht wenn value `None` ist
- Nutze `value = result.get("key") or []` statt `result.get("key", [])`

---

## 🎯 Aktueller Status

**Phase:** Funktionsfähiger Prototyp

**Erledigt:**
- [x] Zwei-System-Architektur mit Docker
- [x] Redis Job Queue
- [x] Playwright Scraper in Sandbox
- [x] LLM Integration (Anthropic, OpenAI)
- [x] Red-Flag Detection
- [x] Interaktive CLI Shell
- [x] REST API (FastAPI)
- [x] Paralleles Scannen (bis zu 10 URLs)
- [x] CSV Batch Import
- [x] History Command
- [x] MCP Server für AI-Tools
- [x] Automatischer Docker Service Start

**Offen:**
- [ ] Rate Limiting
- [ ] Checkpoint-System für große Crawls
- [ ] Web Dashboard
- [ ] Scheduled Scans

---

## 💡 Für Claude Code

Wenn du an diesem Projekt arbeitest:

1. **Lies immer zuerst** `src/core/models.py` und `src/core/queue.py`
2. **Beachte die Sicherheitsarchitektur** - Hauptsystem sieht keine Rohdaten!
3. **Nutze Pydantic** für alle Datenvalidierung
4. **Schreibe async Code** für I/O-Operationen
5. **Teste mit Docker** - `docker compose up -d` vor dem Testen
6. **Nutze naive datetimes** für PostgreSQL (`datetime.utcnow()`)

Bei Fragen zur Architektur: Frag nach, bevor du implementierst!
