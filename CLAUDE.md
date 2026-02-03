# InjectionRadar - Claude Code Projektdokumentation

> **Für Claude Code:** Diese Datei enthält alle wichtigen Informationen über das Projekt.
> Lies sie vollständig, bevor du Code schreibst oder änderst.

---

## 🎯 Projektübersicht

**InjectionRadar** ist ein System zur automatischen Erkennung von Prompt Injection in Web-Inhalten. Es funktioniert wie ein "Virenscanner für AI-Agents" – testet Websites proaktiv und katalogisiert gefährliche Quellen.

### Kernkonzept
```
Website → Scraper → Test-LLM (wird Injection ausgesetzt) → Analyse → Datenbank
```

---

## ⚠️ KRITISCHE SICHERHEITSARCHITEKTUR

**WICHTIG:** Das System hat ein Zwei-System-Design aus Sicherheitsgründen:

### Hauptsystem (Orchestrator)
- **DARF NIEMALS** gescrapte Rohdaten (HTML, Text) verarbeiten
- Sieht **NUR** strukturierte Reports vom Subsystem
- Analysiert Reports und klassifiziert Ergebnisse
- Schreibt in die Datenbank

### Subsystem (Sandbox)
- Läuft in isolierten Docker-Containern
- Scraped Websites und führt LLM-Tests durch
- Speichert Rohdaten **DIREKT** in die Datenbank
- Gibt nur `ScanResult` (strukturierter Report) ans Hauptsystem zurück

**Grund:** Wenn das Hauptsystem Rohdaten verarbeiten würde, könnte es selbst Opfer von Prompt Injection werden!

---

## 📁 Projektstruktur

```
injection-radar/
├── CLAUDE.md              # Diese Datei (für Claude Code)
├── README.md              # Projekt-Dokumentation
├── requirements.txt       # Python Dependencies
├── LICENSE                # MIT Lizenz
│
├── config/
│   └── config.example.yaml    # Beispiel-Konfiguration
│
├── data/
│   └── top-1m.csv            # Tranco Domain-Liste (1M URLs)
│
├── docker/
│   ├── docker-compose.yml     # Komplettes Docker Setup
│   ├── Dockerfile.orchestrator
│   └── Dockerfile.scraper
│
├── src/
│   ├── core/                  # Kernlogik
│   │   ├── models.py          # Pydantic Datenmodelle
│   │   └── config.py          # Konfigurationsmanagement
│   │
│   ├── scraper/               # Web-Scraping (Subsystem)
│   │   └── worker.py          # TODO: Scraper-Worker
│   │
│   ├── llm/                   # LLM-Provider
│   │   ├── base.py            # TODO: Base-Klasse
│   │   ├── anthropic.py       # TODO: Claude Integration
│   │   └── openai.py          # TODO: OpenAI Integration
│   │
│   ├── analysis/              # Red-Flag Detection
│   │   └── detector.py        # TODO: Analyse-Logik
│   │
│   ├── cli/                   # Command Line Interface
│   │   └── main.py            # TODO: CLI Tool
│   │
│   └── api/                   # REST API
│       └── main.py            # TODO: FastAPI Server
│
└── tests/                     # Tests
```

---

## 🔧 Wichtige Datenmodelle

### `ScanResult` - Der strukturierte Report
```python
class ScanResult(BaseModel):
    """Das EINZIGE was das Hauptsystem vom Subsystem bekommt!"""
    url_id: int
    task_name: str  # z.B. "summarize"

    # LLM Info
    llm_provider: str
    llm_model: str

    # Output-Analyse (KEIN Rohtext!)
    output_length: int
    output_word_count: int
    output_format_detected: str

    # Red Flags
    tool_calls_attempted: bool
    tool_calls_count: int
    flags_detected: list[RedFlag]

    # Metriken
    format_match_score: float
    expected_vs_actual_length_ratio: float
```

### `RedFlag` - Erkannte Probleme
```python
class RedFlagType(str, Enum):
    TOOL_CALL = "tool_call"              # 🔴 CRITICAL
    CODE_EXECUTION = "code_execution"    # 🔴 CRITICAL
    SYSTEM_PROMPT_LEAK = "system_prompt_leak"  # 🟠 HIGH
    DIRECT_INSTRUCTIONS = "direct_instructions"  # 🟠 HIGH
    FORMAT_DEVIATION = "format_deviation"  # 🟡 MEDIUM
    EXTERNAL_URLS = "external_urls"      # 🟡 MEDIUM
    UNEXPECTED_DATA = "unexpected_data"  # 🟡 MEDIUM
    HALLUCINATION = "hallucination"      # 🔵 LOW
    SENTIMENT_SHIFT = "sentiment_shift"  # 🔵 LOW
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

---

## 🚀 Entwicklungs-Tasks

### Priorität 1 (Kern-Funktionalität)
1. **Datenbank-Schema** - SQLAlchemy Models für PostgreSQL
2. **Scraper-Worker** - Playwright Integration in Docker
3. **LLM-Client** - Anthropic SDK Wrapper
4. **Red-Flag Detector** - Analyse-Logik

### Priorität 2 (Usability)
5. **CLI-Tool** - Interaktive Einrichtung, Scan-Befehle
6. **Checkpoint-System** - Fortschritt speichern/fortsetzen

### Priorität 3 (API)
7. **REST API** - FastAPI für externe Abfragen
8. **Rate Limiting** - Schutz vor Überlastung

---

## 📝 Code-Konventionen

### Python Style
- Python 3.11+
- Type Hints überall
- Pydantic für Datenvalidierung
- async/await für I/O-Operationen
- Docstrings im Google-Style

### Beispiel
```python
async def analyze_scan_result(
    result: ScanResult,
    settings: Settings,
) -> AnalysisResult:
    """Analysiert einen Scan-Report und klassifiziert das Ergebnis.

    Args:
        result: Der strukturierte Report vom Subsystem.
        settings: Anwendungskonfiguration.

    Returns:
        AnalysisResult mit Klassifizierung und Reasoning.

    Raises:
        AnalysisError: Wenn die Analyse fehlschlägt.
    """
    # Implementation...
```

### Naming
- Dateien: `snake_case.py`
- Klassen: `PascalCase`
- Funktionen/Variablen: `snake_case`
- Konstanten: `UPPER_SNAKE_CASE`

---

## 🔐 Sicherheitsregeln

1. **NIEMALS** API-Keys in Code oder Commits
2. **NIEMALS** Rohdaten im Hauptsystem verarbeiten
3. **IMMER** strukturierte Reports verwenden
4. **IMMER** Input validieren (Pydantic)
5. **IMMER** Sandbox-Container isoliert halten

---

## 🧪 Testen

```bash
# Unit Tests
pytest tests/

# Mit Coverage
pytest --cov=src tests/

# Einzelnen Test
pytest tests/test_analysis.py -v
```

---

## 🐳 Docker Befehle

```bash
# Alles starten
cd docker && docker-compose up -d

# Logs anzeigen
docker-compose logs -f orchestrator

# Scraper skalieren (max 10)
docker-compose up -d --scale scraper=5

# Alles stoppen
docker-compose down
```

---

## 📊 Datenbank

### Verbindung
```python
from src.core.config import get_settings

settings = get_settings()
db_url = settings.database.url
# postgresql://user:pass@localhost:5432/injectionradar
```

### Wichtige Tabellen
- `domains` - Aggregierte Domain-Statistiken
- `urls` - Einzelne URLs mit Status
- `scraped_content` - Rohdaten (nur Subsystem!)
- `scan_results` - Strukturierte Reports
- `analysis_results` - Finale Klassifizierungen
- `crawl_checkpoints` - Fortschritts-Tracking

---

## 🎯 Aktueller Status

**Phase:** Prototyp-Entwicklung

**Erledigt:**
- [x] Projektstruktur
- [x] Datenmodelle (Pydantic)
- [x] Konfigurationsmanagement
- [x] Docker-Setup
- [x] Domain-Liste (Tranco 1M)

**Offen:**
- [ ] Datenbank-Schema (SQLAlchemy)
- [ ] Scraper-Worker
- [ ] LLM-Integration
- [ ] Red-Flag Detection
- [ ] CLI-Tool
- [ ] API

---

## 💡 Für Claude Code

Wenn du an diesem Projekt arbeitest:

1. **Lies immer zuerst** `src/core/models.py` um die Datenstrukturen zu verstehen
2. **Beachte die Sicherheitsarchitektur** - Hauptsystem sieht keine Rohdaten!
3. **Nutze Pydantic** für alle Datenvalidierung
4. **Schreibe async Code** für I/O-Operationen
5. **Teste deinen Code** bevor du ihn als fertig markierst

Bei Fragen zur Architektur: Frag nach, bevor du implementierst!
