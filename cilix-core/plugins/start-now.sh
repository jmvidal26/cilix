#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  start-now.sh — Iniciar Sylix OS Core Assistant inmediatamente
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
cd "$(dirname "$0")/.."

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║           SYLIX OS CORE ASSISTANT - STARTING NOW         ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Verificar dependencias básicas
echo "Verificando dependencias..."

check_command() {
    if ! command -v "$1" &>/dev/null; then
        echo -e "${RED}[✗] $1 no encontrado${NC}"
        return 1
    fi
    echo -e "${GREEN}[✓] $1 encontrado${NC}"
    return 0
}

check_command python3
check_command node

# Activar entorno virtual Python
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo -e "${GREEN}[✓] Entorno Python activado${NC}"
else
    echo -e "${RED}[✗] Entorno virtual Python no encontrado${NC}"
    echo "Ejecuta primero: python3 -m venv .venv"
    exit 1
fi

# Crear directorios necesarios
mkdir -p static logs scripts assets

# Verificar si hay icono
if [ ! -f "assets/icon.png" ]; then
    echo "Creando icono placeholder..."
    echo "Icono placeholder" > assets/icon.png
    cp assets/icon.png assets/tray-icon.png
fi

# Iniciar backend Python
echo "Iniciando backend Python en puerto 8000..."
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
PYTHON_PID=$!

echo -e "${GREEN}[✓] Backend Python iniciado (PID: $PYTHON_PID)${NC}"
echo "URL del backend: http://localhost:8000"

# Esperar que el backend esté listo
echo "Esperando que el backend se inicie..."
sleep 5

# Verificar si el backend está funcionando
if curl -s http://localhost:8000/health > /dev/null; then
    echo -e "${GREEN}[✓] Backend funcionando correctamente${NC}"
else
    echo -e "${RED}[✗] Backend no responde. Intentando continuar...${NC}"
fi

# Opciones para el usuario
echo ""
echo -e "${CYAN}Opciones disponibles:${NC}"
echo "1. Abrir en navegador (modo web tradicional)"
echo "2. Intentar iniciar aplicación Electron (si npm install completó)"
echo "3. Solo mantener backend Python"
echo ""
read -rp "Selecciona opción (1/2/3): " OPTION

case $OPTION in
    1)
        echo "Abriendo en navegador..."
        if command -v xdg-open &>/dev/null; then
            xdg-open "http://localhost:8000"
        elif command -v firefox &>/dev/null; then
            firefox "http://localhost:8000"
        else
            echo "Abre manualmente: http://localhost:8000"
        fi
        ;;
    2)
        # Verificar si npm install se completó
        if [ -d "node_modules" ]; then
            echo "Iniciando aplicación Electron..."
            export NODE_ENV=development
            npm start || echo "Error al iniciar Electron. Usando opción 1..."
            
            if [ $? -ne 0 ]; then
                echo "Abriendo en navegador como fallback..."
                xdg-open "http://localhost:8000" 2>/dev/null || true
            fi
        else
            echo -e "${RED}[✗] node_modules no encontrado. Ejecuta 'npm install' primero.${NC}"
            echo "Usando opción 1 (navegador)..."
            xdg-open "http://localhost:8000" 2>/dev/null || true
        fi
        ;;
    3)
        echo "Manteniendo solo backend Python..."
        echo "Accede en: http://localhost:8000"
        ;;
    *)
        echo "Opción no válida. Usando navegador por defecto..."
        xdg-open "http://localhost:8000" 2>/dev/null || true
        ;;
esac

# Mantener script ejecutándose
echo ""
echo -e "${CYAN}Backend Python corriendo en segundo plano (PID: $PYTHON_PID)${NC}"
echo -e "${CYAN}Presiona Ctrl+C para detener${NC}"
echo ""

# Capturar Ctrl+C para limpiar
trap 'echo ""; echo "Deteniendo backend..."; kill $PYTHON_PID 2>/dev/null; deactivate; echo "Aplicación detenida"; exit 0' INT

# Mantener script vivo
wait $PYTHON_PID 2>/dev/null || true

echo "Backend detenido"
deactivate