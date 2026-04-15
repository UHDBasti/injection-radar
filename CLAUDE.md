# InjectionRadar - Projektdokumentation

> **Stand:** 15. April 2026
> **Phase:** Research-First MVP
> **Sprache:** Antworten IMMER auf Deutsch. Englische Fachbegriffe beim ersten Mal kurz erklären.

---

## Projektbeschreibung

**InjectionRadar** ist eine proaktive Datenbank/Blacklist von Websites die Prompt Injection enthalten — "Google Safe Browsing für AI-Agents". Websites werden automatisch gescraped und mit LLMs auf Prompt Injection getestet. Ergebnisse werden katalogisiert und als API/Feed bereitgestellt.

---

## Strategiewechsel (April 2026)

**Alt (verworfen):** Vollständiges Zwei-System-Design mit Docker-Sandbox-Pool, PostgreSQL, Redis, Multi-LLM. Ergebnis: 2 Monate Architektur ohne funktionierenden Prototyp.

**Neu (aktiv):** Research-First MVP. Minimaler Scanner. Kein Docker, keine Sandboxes. Einfaches Python-Script das Websites scraped, analysiert und Ergebnisse speichert. Ziel: In 4-6 Wochen einen veröffentlichbaren Research-Beitrag mit echten Daten.

---

## MVP-Architektur

```
[Tranco .de-Domains CSV]
         |
         v
[scanner.py] ──── scrapt URL (httpx)
         |
         v
[detector.py] ── Pattern-basierte Analyse (lokal, kostenlos)
         |
         v  (nur wenn Pattern unsicher)
[llm_analyzer.py] ── GPT-4o-mini Analyse (~$0.003/URL)
         |
         v
[SQLite DB] + [JSON/CSV Export]
```

---

## Projektstruktur (MVP)

```
injection-radar/
├── CLAUDE.md              # Diese Datei
├── README.md              # Projekt-Dokumentation
├── pyproject.toml         # MVP Dependencies
├── .env.example           # API-Key Template
├── .gitignore
├── LICENSE                # MIT
├── top-1m.csv             # Tranco Top-1M (nicht in Git)
├── data/
│   └── de-domains.csv     # Gefilterte .de-Domains
├── src/
│   ├── scanner.py         # Haupt-Script: URL -> Scrape -> Analyse -> Ergebnis
│   ├── scraper.py         # httpx-basiertes Scraping
│   ├── detector.py        # Pattern-basierte Red-Flag Detection (EXISTIERT)
│   ├── llm_analyzer.py    # GPT-4o-mini Analyse
│   ├── models.py          # Pydantic Models (vereinfacht)
│   └── db.py              # SQLite Storage
├── results/               # Scan-Ergebnisse (JSON/CSV)
└── tests/
    └── test_detector.py   # Detector Tests (EXISTIERT)
```

### Bestehender Code (aus Architektur-Phase)

Der alte Code unter `src/core/`, `src/analysis/`, `src/llm/`, `src/scraper/`, `src/cli/`, `src/api/`, `src/mcp/`, `src/dashboard/`, `src/scheduler/` bleibt vorerst erhalten. Daraus wird selektiv Code für den MVP extrahiert:

| Quelle | Zeilen | MVP-Nutzung |
|--------|--------|-------------|
| `src/analysis/detector.py` | 905 | DIREKT ÜBERNEHMEN — Kern der Detection |
| `src/core/models.py` | 217 | Vereinfachen, Enums + RedFlag übernehmen |
| `src/llm/openai.py` | 135 | ÜBERNEHMEN für GPT-4o-mini |
| `src/llm/base.py` | 164 | LLMResult übernehmen |
| `src/scraper/worker.py` | 943 | Extraktionslogik portieren (httpx statt Playwright) |
| `tests/test_detector.py` | 257 | ÜBERNEHMEN |

Alles andere (Docker, Redis, PostgreSQL, FastAPI, Interactive CLI, MCP) ist Ballast für den MVP und wird erst nach Validierung wieder aktiviert.

---

## Tech-Stack MVP

```
python >= 3.11
httpx              # Async HTTP Client
beautifulsoup4     # HTML Parsing
lxml               # Fast HTML Parser
pydantic           # Datenvalidierung
openai             # GPT-4o-mini API
rich               # CLI Output
python-dotenv      # .env laden
sqlite3            # Datenbank (built-in)
```

---

## Session-Plan

| # | Session | Status | Beschreibung |
|---|---------|--------|--------------|
| 1 | Projekt-Setup | IN ARBEIT | Bereinigung, .de-Domains filtern, Dependencies verschlanken |
| 2 | Scraper bauen | OFFEN | httpx-basiertes Scraping mit Text-Extraktion |
| 3 | Detection-Engine | OFFEN | detector.py übernehmen + llm_analyzer.py bauen |
| 4 | Pipeline | OFFEN | scanner.py + SQLite + erster Testlauf (100 URLs) |
| 5 | Erster Scan | OFFEN | 1.000 .de-Domains scannen, Ergebnisse analysieren |
| 6 | VPS + Skalierung | OFFEN | Hetzner VPS, 10.000 Domains scannen |
| 7 | Veröffentlichung | OFFEN | README, GitHub public, Blog-Post Outline |

---

## Sicherheitsregeln

1. **NIEMALS** API-Keys in Code oder Commits (.env ist in .gitignore)
2. **NIEMALS** top-1m.csv committen (22 MB, in .gitignore)
3. **IMMER** Input validieren (Pydantic)
4. **IMMER** Rate-Limiting beim Scraping beachten

---

## Code-Konventionen

- Python 3.11+, Type Hints
- Pydantic für Datenvalidierung
- async/await für I/O
- Dateien: `snake_case.py`, Klassen: `PascalCase`
- Kein Over-Engineering: Einfachste Lösung zuerst
- Code sauber ohne Inline-Kommentare

---

## Kosten MVP

| Posten | Kosten |
|--------|--------|
| 10.000 URLs scrapen (httpx) | ~0 EUR |
| Pattern-Detection (lokal) | 0 EUR |
| ~2.000 URLs LLM-Analyse (GPT-4o-mini) | ~6-10 EUR |
| VPS Hetzner CX22 | 5 EUR/Monat |
| **Gesamt** | **~15-20 EUR** |
