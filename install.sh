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
# 6. Docker Installation und Setup
# ============================================================================
log_info "Prüfe Docker Installation..."

DOCKER_AVAILABLE=false

# Funktion um Docker zu installieren
install_docker() {
    log_info "Installiere Docker..."

    # Alte Versionen entfernen
    sudo apt-get remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

    # Dependencies installieren
    sudo apt-get update
    sudo apt-get install -y \
        ca-certificates \
        curl \
        gnupg \
        lsb-release

    # Docker GPG Key hinzufügen
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

    # Docker Repository hinzufügen
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Docker installieren
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

    # User zur docker Gruppe hinzufügen
    sudo usermod -aG docker $USER

    # Docker starten
    sudo systemctl start docker
    sudo systemctl enable docker

    log_success "Docker installiert"
    log_warn "WICHTIG: Bitte einmal aus- und wieder einloggen, damit die docker-Gruppe aktiv wird!"
    log_warn "Oder führe aus: newgrp docker"
}

# Prüfe ob Docker installiert ist
if command -v docker &> /dev/null; then
    # Docker ist installiert, prüfe ob es läuft
    if docker info &> /dev/null; then
        DOCKER_AVAILABLE=true
        log_success "Docker verfügbar und läuft"
    else
        # Docker installiert aber läuft nicht - versuche zu starten
        log_warn "Docker installiert aber nicht erreichbar"

        # Versuche Docker zu starten
        if command -v sudo &> /dev/null; then
            log_info "Versuche Docker zu starten..."
            sudo systemctl start docker 2>/dev/null || true
            sleep 2

            # Prüfe ob User in docker Gruppe ist
            if ! groups | grep -q docker; then
                log_info "Füge User zur docker-Gruppe hinzu..."
                sudo usermod -aG docker $USER
                log_warn "Bitte führe 'newgrp docker' aus oder logge dich neu ein"
            fi

            # Nochmal prüfen
            if docker info &> /dev/null; then
                DOCKER_AVAILABLE=true
                log_success "Docker gestartet"
            else
                # Versuche mit newgrp
                log_info "Versuche Docker mit newgrp..."
                if sg docker -c "docker info" &> /dev/null; then
                    DOCKER_AVAILABLE=true
                    log_success "Docker verfügbar (via docker-Gruppe)"
                fi
            fi
        fi
    fi
else
    # Docker nicht installiert
    log_warn "Docker nicht installiert"

    # Frage ob installiert werden soll
    if command -v sudo &> /dev/null && command -v apt-get &> /dev/null; then
        echo ""
        echo -e "${YELLOW}Docker wird für die Zwei-System-Architektur benötigt.${NC}"
        echo -e "${YELLOW}Ohne Docker läuft InjectionRadar im lokalen Modus (weniger sicher).${NC}"
        echo ""
        read -p "Docker jetzt installieren? [j/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Jj]$ ]]; then
            install_docker

            # Nach Installation nochmal prüfen (mit newgrp)
            if sg docker -c "docker info" &> /dev/null; then
                DOCKER_AVAILABLE=true
            fi
        fi
    else
        log_warn "Automatische Docker-Installation nicht möglich"
        log_info "Installiere Docker manuell: https://docs.docker.com/engine/install/"
    fi
fi

if [ "$DOCKER_AVAILABLE" = true ]; then
    log_info "Starte alle Docker Services (DB, Redis)..."

    # Setze Umgebungsvariablen für docker-compose
    export DB_PASSWORD="pishield123"
    export PISHIELD_DB_PASSWORD="pishield123"

    # Lade API Keys aus .env wenn vorhanden
    if [ -f ".env" ]; then
        set -a
        source .env 2>/dev/null || true
        set +a
    fi

    # Prüfe ob User docker ohne sudo ausführen kann
    if docker info &> /dev/null; then
        DOCKER_CMD="docker"
        COMPOSE_CMD="docker compose"
    else
        # Braucht sudo (User noch nicht in docker-Gruppe)
        log_info "Docker braucht sudo (Gruppe wird erst nach Neuanmeldung aktiv)"
        DOCKER_CMD="sudo docker"
        COMPOSE_CMD="sudo docker compose"
    fi

    # Prüfe ob Services bereits laufen
    if $DOCKER_CMD ps --format '{{.Names}}' 2>/dev/null | grep -q "pishield-db"; then
        log_warn "Services laufen bereits"
    else
        # Alte einzelne Container entfernen (falls vorhanden)
        $DOCKER_CMD rm -f injectionradar-db 2>/dev/null || true

        log_info "Baue und starte Docker Services..."

        cd docker

        # Nur DB und Redis beim Install starten (schneller)
        if $COMPOSE_CMD up -d db redis 2>&1 | tee /tmp/compose-output.log; then
            log_success "Basis-Services gestartet (DB, Redis)"
        else
            log_error "Docker Compose fehlgeschlagen:"
            cat /tmp/compose-output.log
        fi

        cd ..

        log_info "Warte auf PostgreSQL..."
        for i in {1..30}; do
            if $DOCKER_CMD exec pishield-db pg_isready -U pishield &> /dev/null; then
                log_success "PostgreSQL ist bereit"
                break
            fi
            sleep 1
        done

        log_info "Warte auf Redis..."
        for i in {1..10}; do
            if $DOCKER_CMD exec pishield-redis redis-cli ping &> /dev/null; then
                log_success "Redis ist bereit"
                break
            fi
            sleep 1
        done
    fi

    # Update config mit DB Password
    if [ -f "config/config.yaml" ]; then
        sed -i 's/password: "changeme"/password: "pishield123"/' config/config.yaml 2>/dev/null || true
    fi
else
    log_warn "Docker nicht verfügbar - nutze lokalen SQLite Modus"
    log_info "InjectionRadar funktioniert auch ohne Docker (eingeschränkt)"
fi

# ============================================================================
# 7. Datenbank initialisieren
# ============================================================================
if [ "$DOCKER_AVAILABLE" = true ]; then
    log_info "Initialisiere Datenbank-Schema..."

    # Warte kurz auf DB
    sleep 2

    # Schema wird automatisch durch docker-entrypoint-initdb.d geladen
    # Prüfe ob Tabellen existieren
    if $DOCKER_CMD exec pishield-db psql -U pishield -d pishield -c "SELECT 1 FROM domains LIMIT 1" &> /dev/null; then
        log_success "Datenbank-Schema bereits vorhanden"
    else
        # Falls init-db.sql nicht automatisch geladen wurde
        if [ -f "docker/init-db.sql" ]; then
            if cat docker/init-db.sql | $DOCKER_CMD exec -i pishield-db psql -U pishield -d pishield &> /dev/null; then
                log_success "Datenbank-Schema initialisiert"
            else
                log_warn "Schema-Initialisierung fehlgeschlagen (evtl. bereits vorhanden)"
            fi
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

# Erstelle Wrapper-Script (löst Symlinks korrekt auf)
cat > "$SCRIPT_DIR/injection-radar" << 'WRAPPEREOF'
#!/bin/bash
# InjectionRadar CLI Wrapper - löst Symlinks auf
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
exec injection-radar "$@"
WRAPPEREOF
chmod +x "$SCRIPT_DIR/injection-radar"

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

# Hinweis auf docker-Gruppe
if [ "$DOCKER_AVAILABLE" = true ]; then
    echo -e "${YELLOW}WICHTIG:${NC} Für Docker-Zugriff musst du dich einmal neu anmelden"
    echo -e "         (oder 'newgrp docker' ausführen)"
    echo ""
    echo -e "${BLUE}Dann starte mit:${NC}"
    echo -e "     ${YELLOW}injection-radar${NC}"
    echo ""
    echo -e "${DIM}Ohne Neuanmeldung kannst du auch so starten:${NC}"
    echo -e "     ${YELLOW}sg docker -c 'injection-radar'${NC}"
else
    echo -e "${YELLOW}Starte mit:  injection-radar${NC}"
fi
