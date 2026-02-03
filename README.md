# 🎯 InjectionRadar

> Automatische Erkennung von Prompt Injection in Web-Inhalten – wie ein Virenscanner für AI-Agents.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## 🎯 Was ist InjectionRadar?

InjectionRadar testet Websites automatisch auf Prompt Injection und katalogisiert die Ergebnisse in einer zentralen Datenbank. AI-Agents können diese Datenbank abfragen, bevor sie eine Website verarbeiten.

**Das Problem:** AI-Agents (wie Claude Computer Use, OpenAI Operator, etc.) können durch bösartige Inhalte auf Websites manipuliert werden.

**Die Lösung:** Eine proaktive Datenbank die vorher weiß, welche Quellen gefährlich sind.

## 🏗️ Architektur

```
┌─────────────────────────────────────────────────────────────────┐
│                         VPS SERVER                               │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              HAUPTSYSTEM (Orchestrator)                  │   │
│  │  ⚠️ Verarbeitet NIEMALS Rohdaten - nur Reports          │   │
│  └─────────────────────────┬───────────────────────────────┘   │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │         SUBSYSTEM SANDBOX POOL (max. 10 Container)       │   │
│  │  • Scraped Websites • Führt LLM-Tests aus               │   │
│  │  • Speichert Rohdaten direkt in DB                      │   │
│  └─────────────────────────┬───────────────────────────────┘   │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              POSTGRESQL DATENBANK                        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 🚀 Schnellstart

```bash
# Repository klonen
git clone https://github.com/YOUR_USERNAME/injection-radar.git
cd injection-radar

# Abhängigkeiten installieren
pip install -r requirements.txt

# Konfiguration erstellen
cp config/config.example.yaml config/config.yaml
# API-Keys als Umgebungsvariablen setzen

# Docker starten
cd docker && docker-compose up -d

# CLI starten
python -m src.cli.main init
```

## 🔍 Features

- **Multi-LLM Testing:** Teste mit Claude, GPT, Gemini, Llama, Grok
- **Automatisches Crawling:** Scanne Websites aus der Tranco Top 1M Liste
- **Red Flag Detection:** Erkennt Tool-Calls, Code-Execution, Format-Abweichungen
- **Cross-LLM Vergleich:** Welches LLM ist anfälliger für Injections?
- **REST API:** Integriere die Datenbank in deine eigenen Projekte
- **CLI Tool:** Einfache Steuerung über die Kommandozeile

## 🚨 Erkannte Red Flags

| Severity | Typ | Beschreibung |
|----------|-----|--------------|
| 🔴 Critical | Tool Calls | LLM versucht Tools ohne Erlaubnis auszuführen |
| 🔴 Critical | Code Execution | Output enthält ausführbaren Code |
| 🟠 High | System Prompt Leak | Patterns wie "Ignore previous instructions" |
| 🟠 High | Direct Instructions | Anweisungen im Output statt Inhalt |
| 🟡 Medium | Format-Abweichung | Output weicht stark vom Erwarteten ab |
| 🔵 Low | Halluzination | Erfundene Fakten oder Quellen |

## 📁 Projektstruktur

```
injection-radar/
├── CLAUDE.md           # Dokumentation für Claude Code
├── README.md           # Diese Datei
├── requirements.txt    # Python Dependencies
├── LICENSE             # MIT Lizenz
│
├── config/             # Konfigurationsdateien
├── data/               # Domain-Listen (Tranco 1M)
├── docker/             # Docker & Compose Configs
├── src/                # Quellcode
│   ├── core/           # Datenmodelle, Config
│   ├── scraper/        # Web-Scraping
│   ├── llm/            # LLM-Provider
│   ├── analysis/       # Red-Flag Detection
│   ├── cli/            # CLI Tool
│   └── api/            # REST API
└── tests/              # Tests
```

## ⚙️ Konfiguration

Erstelle `config/config.yaml`:

```yaml
llm:
  primary_analyzer: "claude-sonnet-4-5-20250929"
  test_agents:
    - model: "gpt-4o-mini"
      provider: "openai"

database:
  host: "localhost"
  port: 5432
  name: "injectionradar"

scraping:
  max_concurrent: 10
  timeout: 30
```

Umgebungsvariablen:
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

## 🐳 Docker

```bash
# Alles starten
cd docker && docker-compose up -d

# Scraper skalieren (max 10)
docker-compose up -d --scale scraper=5

# Stoppen
docker-compose down
```

## 🤝 Contributing

Beiträge sind willkommen! Bitte lies zuerst `CLAUDE.md` für die Architektur-Details.

## 📄 Lizenz

MIT License - siehe [LICENSE](LICENSE)

---

*Built with ❤️ for a safer AI future*
