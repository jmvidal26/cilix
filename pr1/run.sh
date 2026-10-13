#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  run.sh — Sylix OS Core Assistant — Script de arranque
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'   # No Color
BOLD='\033[1m'

VENV_DIR=".venv"
PYTHON_BIN="python3"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

banner() {
  echo -e "${CYAN}"
  echo "  ╔═══════════════════════════════════════════════════════╗"
  echo "  ║           SYLIX OS CORE ASSISTANT  v1.0.0             ║"
  echo "  ║    VTuber Agent · Bash Automation · Desktop Control   ║"
  echo "  ╚═══════════════════════════════════════════════════════╝"
  echo -e "${NC}"
}

log_info()    { echo -e "${GREEN}[✓]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[⚠]${NC} $*"; }
log_error()   { echo -e "${RED}[✗]${NC} $*"; }
log_section() { echo -e "\n${BOLD}${CYAN}── $* ──────────────────────────${NC}"; }

# ─── 0. Banner ────────────────────────────────────────────────────────────────
banner

# ─── 1. Verificar Python ──────────────────────────────────────────────────────
log_section "Verificando entorno"

if ! command -v "$PYTHON_BIN" &>/dev/null; then
  log_error "Python 3 no encontrado. Instálalo con: sudo apt install python3"
  exit 1
fi

PYTHON_VERSION=$($PYTHON_BIN --version 2>&1)
log_info "Python detectado: $PYTHON_VERSION"

# ─── 2. Crear entorno virtual ─────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
  log_info "Creando entorno virtual en $VENV_DIR/ ..."
  $PYTHON_BIN -m venv "$VENV_DIR"
  log_info "Entorno virtual creado."
else
  log_info "Entorno virtual existente: $VENV_DIR/"
fi

# Activar entorno virtual
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
log_info "Entorno virtual activado."

# ─── 3. Instalar dependencias del sistema (opcional) ─────────────────────────
log_section "Dependencias del sistema"

SYSTEM_PKGS=()

if ! command -v xdotool &>/dev/null; then
  SYSTEM_PKGS+=("xdotool")
  log_warn "xdotool no encontrado (necesario para automatización de escritorio)."
fi

if ! command -v wmctrl &>/dev/null; then
  SYSTEM_PKGS+=("wmctrl")
  log_warn "wmctrl no encontrado (necesario para gestión de ventanas)."
fi

if ! command -v nmap &>/dev/null; then
  SYSTEM_PKGS+=("nmap")
  log_warn "nmap no encontrado (necesario para escaneo de red)."
fi

if [ ${#SYSTEM_PKGS[@]} -gt 0 ]; then
  echo -e "${YELLOW}Paquetes del sistema faltantes: ${SYSTEM_PKGS[*]}${NC}"
  read -t 2 -rp "¿Instalar automáticamente con apt? (s/N): " INSTALL_PKGS || INSTALL_PKGS="N"
  if [[ "$INSTALL_PKGS" =~ ^[sS]$ ]]; then
    sudo apt-get update -qq
    sudo apt-get install -y "${SYSTEM_PKGS[@]}"
    log_info "Paquetes instalados."
  else
    log_warn "Omitiendo instalación de paquetes del sistema."
  fi
fi

# ─── 4. Instalar dependencias Python ─────────────────────────────────────────
log_section "Dependencias Python"

pip install --upgrade pip --quiet

if [ -f "requirements.txt" ]; then
  log_info "Instalando desde requirements.txt ..."
  pip install -r requirements.txt --quiet
  log_info "Dependencias instaladas correctamente."
else
  log_error "requirements.txt no encontrado."
  exit 1
fi

# ─── 5. Instalar edge-tts (TTS de alta calidad) ──────────────────────────────
log_section "TTS Backend (edge-tts)"

if pip show edge-tts &>/dev/null; then
  log_info "edge-tts ya instalado."
else
  log_warn "edge-tts no instalado. Instalando..."
  if pip install edge-tts --quiet 2>/dev/null; then
    log_info "edge-tts instalado (Microsoft Neural Voices)."
  else
    log_warn "edge-tts no disponible. Se usará pyttsx3 como fallback."
    pip install pyttsx3 --quiet || true
  fi
fi

# ─── 6. Verificar Backends de IA (Gemini / Anthropic / Ollama) ───────────────
log_section "Configuración de IA (Gemini / Claude / Ollama Offline)"

ENV_FILE=".env"

if [ -f "$ENV_FILE" ]; then
  log_info "Cargando variables desde $ENV_FILE ..."
  set -a
  # shellcheck disable=SC1090
  source <(grep -v '^\s*#' "$ENV_FILE" | grep -v '^\s*$')
  set +a
fi

HAS_CLOUD_KEY=false

if [ -n "${GEMINI_API_KEY:-}" ]; then
  log_info "GEMINI_API_KEY configurada (Backend Primario Online)."
  HAS_CLOUD_KEY=true
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  log_info "ANTHROPIC_API_KEY configurada (Backend Secundario Online)."
  HAS_CLOUD_KEY=true
else
  log_warn "Ni GEMINI_API_KEY ni ANTHROPIC_API_KEY están configuradas."
  echo ""
  echo -e "${YELLOW}Configuración recomendada:${NC}"
  echo "  1. Obtén tu API key gratuita de Gemini en: https://aistudio.google.com"
  echo "  2. O usa Ollama en local para modo sin conexión (offline)"
  echo ""
  if [ -t 0 ] && [ -z "${CI:-}" ]; then
    read -t 3 -rp "¿Ingresar GEMINI_API_KEY ahora? (s/N): " ENTER_GEMINI || ENTER_GEMINI="N"
    if [[ "$ENTER_GEMINI" =~ ^[sS]$ ]]; then
      read -rsp "GEMINI_API_KEY: " GEMINI_API_KEY
      echo ""
      export GEMINI_API_KEY
      echo "GEMINI_API_KEY=$GEMINI_API_KEY" >> "$ENV_FILE"
      log_info "GEMINI_API_KEY guardada en $ENV_FILE."
      HAS_CLOUD_KEY=true
    fi
  else
    log_info "Modo no-interactivo: continuando con modelo local Ollama."
  fi
fi

# Verificar Ollama (modelo local offline)
if command -v ollama &>/dev/null; then
  if curl -s http://localhost:11434/api/tags &>/dev/null; then
    log_info "Ollama detectado y activo en localhost:11434 (Modo Offline listo)."
  else
    log_warn "Ollama instalado pero el servicio no está corriendo. Inícialo con: ollama serve"
  fi
else
  log_warn "Ollama no detectado. Para soporte offline sin WiFi:"
  echo "       curl -fsSL https://ollama.com/install.sh | sh"
  echo "       ollama pull qwen2.5:0.5b"
fi

# ─── 7. Crear directorios necesarios ─────────────────────────────────────────
log_section "Estructura de directorios"

mkdir -p static models logs

log_info "Directorios: static/, models/, logs/"

# Detección de modelo Live2D
MODEL_COUNT=$(find models -name "*.model3.json" 2>/dev/null | wc -l)
if [ "$MODEL_COUNT" -gt 0 ]; then
  ACTIVE_MODEL=$(find models -name "*.model3.json" 2>/dev/null | head -n 1)
  log_info "Modelo Live2D detectado: $ACTIVE_MODEL"
  if [ -d "models/design_genius_white" ]; then
    log_info "Modelo Design Genius White listo y vinculado."
  fi
else
  log_warn "Modelo Live2D no encontrado en models/"
  log_warn "El avatar se mostrará en modo demo animado."
fi

# ─── 8. Verificar puerto libre ────────────────────────────────────────────────
log_section "Verificando puerto $PORT"

if lsof -Pi ":$PORT" -sTCP:LISTEN -t &>/dev/null 2>&1; then
  log_warn "Puerto $PORT ocupado. Intentando liberar..."
  BLOCKING_PID=$(lsof -Pi ":$PORT" -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$BLOCKING_PID" ]; then
    echo "  PID usando el puerto: $BLOCKING_PID"
    read -rp "  ¿Matar el proceso? (s/N): " KILL_IT
    if [[ "$KILL_IT" =~ ^[sS]$ ]]; then
      kill "$BLOCKING_PID" 2>/dev/null || true
      sleep 1
      log_info "Proceso terminado."
    fi
  fi
fi

# ─── 9. Abrir navegador (opcional) ───────────────────────────────────────────
open_browser() {
  sleep 2.5
  URL="http://localhost:$PORT"
  if command -v xdg-open &>/dev/null; then
    xdg-open "$URL" &>/dev/null &
  elif command -v firefox &>/dev/null; then
    firefox "$URL" &>/dev/null &
  elif command -v google-chrome &>/dev/null; then
    google-chrome "$URL" &>/dev/null &
  fi
}

open_browser &

# ─── 10. Iniciar servidor ─────────────────────────────────────────────────────
log_section "Iniciando Sylix OS Core"
echo -e "${GREEN}"
echo "  → URL Local:    http://localhost:$PORT"
echo "  → WebSocket:    ws://localhost:$PORT/ws"
echo "  → Health:       http://localhost:$PORT/health"
echo "  → Status:       http://localhost:$PORT/status"
echo -e "${NC}"
echo -e "${YELLOW}  Presiona Ctrl+C para detener el servidor.${NC}"
echo ""

exec python3 -m uvicorn main:app \
  --host "$HOST" \
  --port "$PORT" \
  --log-level info \
  --access-log \
  --reload
