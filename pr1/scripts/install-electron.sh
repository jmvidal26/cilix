#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  install-electron.sh — Instalador de Sylix OS Core Assistant (Electron)
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
cd "$(dirname "$0")/.."

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

banner() {
    echo -e "${CYAN}"
    echo "  ╔══════════════════════════════════════════════════════════╗"
    echo "  ║      SYLIX OS CORE ASSISTANT - ELECTRON INSTALLER        ║"
    echo "  ║       Convert Web App → Native Desktop Application       ║"
    echo "  ╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info()    { echo -e "${GREEN}[✓]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[⚠]${NC} $*"; }
log_error()   { echo -e "${RED}[✗]${NC} $*"; }
log_section() { echo -e "\n${BOLD}${CYAN}── $* ──────────────────────────${NC}"; }

# ─── Banner ──────────────────────────────────────────────────────────────────
banner

# ─── Verificar sistema ───────────────────────────────────────────────────────
log_section "Verificando sistema"

OS_TYPE=$(uname -s)
ARCH_TYPE=$(uname -m)

if [[ "$OS_TYPE" != "Linux" ]]; then
    log_error "Este instalador es solo para sistemas Linux"
    exit 1
fi

log_info "Sistema: $OS_TYPE ($ARCH_TYPE)"

# ─── Verificar Node.js ───────────────────────────────────────────────────────
log_section "Verificando Node.js"

if ! command -v node &>/dev/null; then
    log_warn "Node.js no encontrado"
    
    echo -e "${YELLOW}Opciones de instalación:${NC}"
    echo "  1. Instalar desde repositorio oficial (recomendado)"
    echo "  2. Usar nvm (Node Version Manager)"
    echo "  3. Instalar desde package manager del sistema"
    
    read -rp "¿Cómo quieres instalar Node.js? (1/2/3): " NODE_CHOICE
    
    case $NODE_CHOICE in
        1)
            # Instalar desde nodesource
            curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
            sudo apt-get install -y nodejs
            ;;
        2)
            # Instalar nvm
            curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
            source ~/.bashrc
            nvm install 18
            nvm use 18
            ;;
        3)
            # Instalar desde repositorio del sistema
            sudo apt-get update
            sudo apt-get install -y nodejs npm
            ;;
        *)
            log_error "Opción no válida"
            exit 1
            ;;
    esac
fi

NODE_VERSION=$(node --version)
NPM_VERSION=$(npm --version)
log_info "Node.js: $NODE_VERSION"
log_info "npm: $NPM_VERSION"

# ─── Verificar Python ────────────────────────────────────────────────────────
log_section "Verificando Python"

if ! command -v python3 &>/dev/null; then
    log_error "Python 3 no encontrado. Instálalo con:"
    echo "  sudo apt-get install python3 python3-venv python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
log_info "Python: $PYTHON_VERSION"

# ─── Instalar dependencias del sistema ──────────────────────────────────────
log_section "Instalando dependencias del sistema"

SYSTEM_DEPS=(
    "xdotool"      # Automatización de escritorio
    "wmctrl"       # Control de ventanas
    "nmap"         # Escaneo de red
    "ffmpeg"       # Procesamiento de audio
    "scrot"        # Captura de pantalla
    "alsa-utils"   # Audio
    "pulseaudio"   # Audio
)

MISSING_DEPS=()
for dep in "${SYSTEM_DEPS[@]}"; do
    if ! command -v "$dep" &>/dev/null; then
        MISSING_DEPS+=("$dep")
        log_warn "$dep no encontrado"
    fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo -e "${YELLOW}Dependencias del sistema faltantes: ${MISSING_DEPS[*]}${NC}"
    read -rp "¿Instalar automáticamente con apt? (s/N): " INSTALL_DEPS
    
    if [[ "$INSTALL_DEPS" =~ ^[sS]$ ]]; then
        sudo apt-get update
        sudo apt-get install -y "${MISSING_DEPS[@]}"
        log_info "Dependencias instaladas"
    else
        log_warn "Algunas funcionalidades podrían no estar disponibles"
    fi
fi

# ─── Configurar entorno Python ───────────────────────────────────────────────
log_section "Configurando entorno Python"

if [ ! -d ".venv" ]; then
    log_info "Creando entorno virtual Python..."
    python3 -m venv .venv
fi

source .venv/bin/activate
log_info "Entorno virtual activado"

# Instalar dependencias Python
if [ -f "requirements.txt" ]; then
    log_info "Instalando dependencias Python..."
    pip install --upgrade pip
    pip install -r requirements.txt
    
    # Instalar edge-tts para TTS
    pip install edge-tts pyttsx3 sounddevice
    
    log_info "Dependencias Python instaladas"
else
    log_error "requirements.txt no encontrado"
    exit 1
fi

# ─── Instalar dependencias Node.js ───────────────────────────────────────────
log_section "Instalando dependencias Node.js"

if [ -f "package.json" ]; then
    log_info "Instalando dependencias Node.js (esto puede tomar unos minutos)..."
    npm install
    
    # Instalar electron-builder globalmente si no está
    if ! npm list -g electron-builder &>/dev/null; then
        log_info "Instalando electron-builder globalmente..."
        sudo npm install -g electron-builder
    fi
    
    log_info "Dependencias Node.js instaladas"
else
    log_error "package.json no encontrado"
    exit 1
fi

# ─── Configurar estructura de directorios ────────────────────────────────────
log_section "Configurando estructura"

mkdir -p assets logs scripts

# Crear icono por defecto si no existe
if [ ! -f "assets/icon.png" ]; then
    log_info "Creando icono por defecto..."
    # Crear un icono simple con ImageMagick si está disponible
    if command -v convert &>/dev/null; then
        convert -size 256x256 xc:#050a14 -fill "#00f5ff" -draw "circle 128,128 128,64" \
                -fill "#ff2d78" -draw "circle 128,128 100,100" assets/icon.png
        convert assets/icon.png -resize 48x48 assets/tray-icon.png
    else
        log_warn "ImageMagick no encontrado, creando iconos placeholder"
        echo "Placeholder icon" > assets/icon.png
        cp assets/icon.png assets/tray-icon.png
    fi
fi

# ─── Configurar archivo de entorno ───────────────────────────────────────────
log_section "Configurando variables de entorno"

ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
    log_info "Creando archivo de configuración..."
    
    cat > "$ENV_FILE" << EOF
# Sylix OS Core Assistant - Configuración

# Backends de IA
# Obtén tu API key gratuita en: https://aistudio.google.com
GEMINI_API_KEY=
ANTHROPIC_API_KEY=

# Modelos
GEMINI_MODEL=gemini-2.0-flash
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
OLLAMA_MODEL=qwen2.5:1.5b
OLLAMA_BASE_URL=http://localhost:11434

# TTS (Text-to-Speech)
EDGE_TTS_VOICE=es-CO-SalomeNeural
EDGE_TTS_RATE=+10%
EDGE_TTS_PITCH=+5Hz

# Servidor
PORT=8000
HOST=0.0.0.0

# Configuración de Electron
ELECTRON_START_URL=http://localhost:8000
NODE_ENV=development
EOF
    
    log_info "Archivo .env creado. Configura tus API keys antes de ejecutar."
fi

# ─── Crear script de inicio ──────────────────────────────────────────────────
log_section "Creando scripts de inicio"

# Script para desarrollo
cat > "start-dev.sh" << 'EOF'
#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  start-dev.sh — Iniciar Sylix OS Core en modo desarrollo
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║         SYLIX OS CORE ASSISTANT - DEVELOPMENT MODE       ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Activar entorno virtual Python
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo -e "${GREEN}[✓] Entorno Python activado${NC}"
else
    echo "Creando entorno virtual Python..."
    python3 -m venv .venv
    source .venv/bin/activate
fi

# Iniciar backend Python en segundo plano
echo "Iniciando backend Python..."
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
PYTHON_PID=$!

echo -e "${GREEN}[✓] Backend Python iniciado (PID: $PYTHON_PID)${NC}"
echo "URL: http://localhost:8000"

# Esperar un momento para que el backend se inicie
sleep 3

# Iniciar aplicación Electron
echo "Iniciando aplicación Electron..."
export NODE_ENV=development
npm start

# Limpiar al salir
echo "Deteniendo procesos..."
kill $PYTHON_PID 2>/dev/null || true
deactivate

echo -e "${GREEN}[✓] Aplicación detenida${NC}"
EOF

chmod +x start-dev.sh

# Script para producción
cat > "start.sh" << 'EOF'
#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  start.sh — Iniciar Sylix OS Core Assistant
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║           SYLIX OS CORE ASSISTANT - STARTING             ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Verificar dependencias
check_dependency() {
    if ! command -v "$1" &>/dev/null; then
        echo -e "${RED}[✗] $1 no encontrado${NC}"
        echo "Instala con: sudo apt-get install $1"
        exit 1
    fi
    echo -e "${GREEN}[✓] $1 encontrado${NC}"
}

echo "Verificando dependencias..."
check_dependency node
check_dependency python3
check_dependency xdotool
check_dependency wmctrl

# Iniciar aplicación
echo "Iniciando Sylix OS Core Assistant..."
export NODE_ENV=production
electron .

echo -e "${GREEN}[✓] Aplicación detenida${NC}"
EOF

chmod +x start.sh

# ─── Crear desktop entry ─────────────────────────────────────────────────────
log_section "Creando acceso directo"

DESKTOP_ENTRY="$HOME/.local/share/applications/sylix-os-core.desktop"

cat > "$DESKTOP_ENTRY" << EOF
[Desktop Entry]
Type=Application
Name=Sylix OS Core Assistant
Comment=VTuber Agent with Linux Desktop Automation
Exec=$(pwd)/start.sh
Icon=$(pwd)/assets/icon.png
Terminal=false
Categories=System;Utility;
Keywords=vtuber;ai;assistant;automation;linux;
StartupWMClass=Sylix OS Core Assistant
EOF

chmod +x "$DESKTOP_ENTRY"
log_info "Acceso directo creado en el menú de aplicaciones"

# ─── Finalización ────────────────────────────────────────────────────────────
log_section "Instalación completada"

echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          INSTALACIÓN COMPLETADA CON ÉXITO                ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Comandos disponibles:${NC}"
echo "  ./start-dev.sh    - Modo desarrollo (backend + frontend)"
echo "  ./start.sh        - Modo producción (solo aplicación)"
echo "  npm start         - Iniciar aplicación Electron"
echo "  npm run build-linux - Construir paquete para Linux"
echo ""
echo -e "${CYAN}Configuración recomendada:${NC}"
echo "  1. Edita el archivo .env y configura tus API keys"
echo "  2. Para IA offline, instala Ollama: curl -fsSL https://ollama.com/install.sh | sh"
echo "  3. Ejecuta: ollama pull qwen2.5:1.5b"
echo ""
echo -e "${CYAN}Iniciar ahora:${NC}"
echo "  ./start-dev.sh"
echo ""

# Preguntar si iniciar ahora
read -rp "¿Iniciar Sylix OS Core Assistant ahora? (s/N): " START_NOW

if [[ "$START_NOW" =~ ^[sS]$ ]]; then
    ./start-dev.sh
fi