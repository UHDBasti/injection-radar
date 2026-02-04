#!/bin/bash
#
# InjectionRadar Installation Script
# Installiert alle Dependencies und richtet das Projekt ein
#

set -e  # Exit on error

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Banner
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║${NC}           ${GREEN}InjectionRadar Installation${NC}                       ${BLUE}║${NC}"
echo -e "${BLUE}║${NC}     Prompt Injection Scanner für Web-Inhalte               ${BLUE}║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Arbeitsverzeichnis
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

log_info "Arbeitsverzeichnis: $SCRIPT_DIR"

# ============================================================================
# 1. Python Version prüfen
# ============================================================================
log_info "Prüfe Python Installation..."

if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; then
        log_success "Python $PYTHON_VERSION gefunden"
    else
        log_error "Python 3.11+ erforderlich (gefunden: $PYTHON_VERSION)"
        exit 1
    fi
else
    log_error "Python3 nicht gefunden. Bitte installieren: apt install python3"
    exit 1
fi

# ============================================================================
# 2. Virtual Environment erstellen
# ============================================================================
log_info "Erstelle Virtual Environment..."

if [ -d ".venv" ]; then
    log_warn "Virtual Environment existiert bereits"
else
    # Versuche venv zu erstellen
    if python3 -m venv .venv 2>/dev/null; then
        log_success "Virtual Environment erstellt"
    else
        # Fallback: venv ohne pip erstellen und pip manuell installieren
        log_warn "Erstelle venv ohne pip (ensurepip nicht verfügbar)..."
        python3 -m venv --without-pip .venv

        log_info "Installiere pip manuell..."
        curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
        .venv/bin/python3 /tmp/get-pip.py --quiet
        rm /tmp/get-pip.py
        log_success "pip installiert"
    fi
fi

# Aktiviere venv
source .venv/bin/activate
log_success "Virtual Environment aktiviert"

# ============================================================================
# 3. Python Dependencies installieren
# ============================================================================
log_info "Installiere Python Dependencies..."

# Upgrade pip
pip install --upgrade pip --quiet

# Installiere Projekt mit dev dependencies
pip install -e ".[dev]" --quiet

log_success "Python Dependencies installiert"

# ============================================================================
# 4. Playwright Browser installieren
# ============================================================================
log_info "Installiere Playwright Chromium Browser..."

# Prüfe ob Playwright system deps verfügbar sind
if playwright install chromium 2>&1 | grep -q "Host system is missing dependencies"; then
    log_warn "Playwright System-Dependencies fehlen"
    log_info "Versuche System-Dependencies zu installieren..."

    # Versuche playwright install-deps (braucht sudo)
    if command -v sudo &> /dev/null; then
        if sudo playwright install-deps chromium 2>/dev/null; then
            log_success "Playwright System-Dependencies installiert"
            playwright install chromium --quiet
        else
            log_warn "Konnte System-Dependencies nicht installieren"
            log_warn "Für vollständiges Scraping führe aus: sudo playwright install-deps chromium"
        fi
    else
        log_warn "sudo nicht verfügbar - überspringe System-Dependencies"
        log_warn "Für vollständiges Scraping führe aus: playwright install-deps chromium"
    fi
else
    playwright install chromium --quiet 2>/dev/null || true
    log_success "Playwright Chromium installiert"
fi

# ============================================================================
# 5. Konfiguration erstellen
# ============================================================================
log_info "Erstelle Konfiguration..."

if [ ! -f "config/config.yaml" ]; then
    if [ -f "config/config.example.yaml" ]; then
        cp config/config.example.yaml config/config.yaml
        log_success "config/config.yaml erstellt (aus Beispiel)"
    else
        log_warn "Keine Beispiel-Konfiguration gefunden"
    fi
else
    log_warn "config/config.yaml existiert bereits"
fi

# ============================================================================
# 6. Docker/PostgreSQL Setup (optional)
# ============================================================================
log_info "Prüfe Docker Installation..."

DOCKER_AVAILABLE=false
if command -v docker &> /dev/null; then
    if docker info &> /dev/null; then
        DOCKER_AVAILABLE=true
        log_success "Docker verfügbar"
    else
        log_warn "Docker installiert aber nicht erreichbar (Daemon läuft nicht oder keine Rechte)"
    fi
else
    log_warn "Docker nicht installiert"
fi

if [ "$DOCKER_AVAILABLE" = true ]; then
    log_info "Starte PostgreSQL Container..."

    # Prüfe ob Container bereits läuft
    if docker ps --format '{{.Names}}' | grep -q "^injectionradar-db$"; then
        log_warn "PostgreSQL Container läuft bereits"
    elif docker ps -a --format '{{.Names}}' | grep -q "^injectionradar-db$"; then
        log_info "Starte existierenden Container..."
        docker start injectionradar-db
        log_success "PostgreSQL Container gestartet"
    else
        log_info "Erstelle neuen PostgreSQL Container..."
        docker run -d \
            --name injectionradar-db \
            -e POSTGRES_USER=pishield \
            -e POSTGRES_PASSWORD=pishield123 \
            -e POSTGRES_DB=pishield \
            -p 5432:5432 \
            --health-cmd="pg_isready -U pishield" \
            --health-interval=10s \
            --health-timeout=5s \
            --health-retries=5 \
            postgres:16-alpine \
            > /dev/null

        log_info "Warte auf PostgreSQL..."
        sleep 5

        # Warte bis healthy
        for i in {1..30}; do
            if docker exec injectionradar-db pg_isready -U pishield &> /dev/null; then
                log_success "PostgreSQL ist bereit"
                break
            fi
            sleep 1
        done
    fi

    # Update config mit DB Password
    if [ -f "config/config.yaml" ]; then
        # Setze DB Password in config
        sed -i 's/password: "changeme"/password: "pishield123"/' config/config.yaml 2>/dev/null || true
    fi

    # Setze Umgebungsvariable
    export PISHIELD_DB_PASSWORD="pishield123"
else
    log_warn "Docker nicht verfügbar - PostgreSQL muss manuell installiert werden"
    log_info "Alternative: Installiere PostgreSQL mit: apt install postgresql"
fi

# ============================================================================
# 7. Datenbank initialisieren
# ============================================================================
if [ "$DOCKER_AVAILABLE" = true ]; then
    log_info "Initialisiere Datenbank-Schema..."

    # Warte kurz auf DB
    sleep 2

    # Führe init-db.sql aus
    if [ -f "docker/init-db.sql" ]; then
        if docker exec -i injectionradar-db psql -U pishield -d pishield < docker/init-db.sql &> /dev/null; then
            log_success "Datenbank-Schema initialisiert"
        else
            log_warn "Schema bereits vorhanden oder Fehler bei Initialisierung"
        fi
    fi
fi

# ============================================================================
# 8. .env Datei erstellen
# ============================================================================
log_info "Erstelle .env Datei..."

if [ ! -f ".env" ]; then
    cat > .env << 'ENVEOF'
# InjectionRadar Environment Variables
# Kopiere diese Datei und fülle die API Keys aus

# LLM API Keys (mindestens einer erforderlich)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Datenbank (wird automatisch gesetzt wenn Docker verwendet wird)
PISHIELD_DB_PASSWORD=pishield123
ENVEOF
    log_success ".env Datei erstellt"
    log_warn "Bitte füge deinen API Key in .env ein!"
else
    log_warn ".env existiert bereits"
fi

# ============================================================================
# 9. Globale Installation (~/bin)
# ============================================================================
log_info "Erstelle globalen CLI-Befehl..."

# Erstelle Wrapper-Script falls nicht vorhanden
if [ ! -f "$SCRIPT_DIR/injection-radar" ] || [ ! -x "$SCRIPT_DIR/injection-radar" ]; then
    cat > "$SCRIPT_DIR/injection-radar" << 'WRAPPEREOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
exec injection-radar "$@"
WRAPPEREOF
    chmod +x "$SCRIPT_DIR/injection-radar"
fi

# Erstelle ~/bin und Symlink
mkdir -p "$HOME/bin"
ln -sf "$SCRIPT_DIR/injection-radar" "$HOME/bin/injection-radar"

# Füge ~/bin zum PATH hinzu wenn nötig
if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then
    # Für bash
    if [ -f "$HOME/.bashrc" ]; then
        echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.bashrc"
    fi
    # Für zsh
    if [ -f "$HOME/.zshrc" ]; then
        echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.zshrc"
    fi
    export PATH="$HOME/bin:$PATH"
    log_success "~/bin zum PATH hinzugefügt"
fi

log_success "CLI global verfügbar: injection-radar"

# ============================================================================
# 10. Abschluss
# ============================================================================
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║${NC}              ${GREEN}Installation abgeschlossen!${NC}                    ${GREEN}║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

echo -e "${BLUE}Starte jetzt InjectionRadar:${NC}"
echo ""
echo -e "     ${YELLOW}injection-radar${NC}"
echo ""
echo -e "${DIM}(Falls 'command not found': source ~/.bashrc)${NC}"
echo ""

# Teste Installation
log_info "Teste Installation..."
if .venv/bin/python3 -c "from src.analysis.detector import RedFlagDetector; print('OK')" 2>/dev/null | grep -q "OK"; then
    log_success "Core-Module funktionieren"
fi

if .venv/bin/injection-radar --help &> /dev/null; then
    log_success "CLI funktioniert"
fi

echo ""
log_success "InjectionRadar ist bereit!"
echo ""
echo -e "${YELLOW}Starte mit:  injection-radar${NC}"
