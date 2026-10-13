#!/bin/bash

# Cilix Launcher Unificado v1.2
# Con soporte para pr1 (Sylix OS Core)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

print_step() {
    echo -e "\033[0;32m[+]\033[0m $1"
}

print_info() {
    echo -e "\033[0;36m[i]\033[0m $1"
}

print_warning() {
    echo -e "\033[1;33m[!]\033[0m $1"
}

print_success() {
    echo -e "\033[0;32m[✓]\033[0m $1"
}

start_cilix() {
    print_step "Iniciando Cilix Unificado..."
    
    cd "$SCRIPT_DIR"
    source "$VENV_DIR/bin/activate"
    
    # Iniciar servidor Python con backend unificado
    cd backend
    python3 main.py &
    PYTHON_PID=$!
    cd ..
    
    # Esperar
    sleep 3
    
    # Verificar
    if curl -s "http://localhost:8765/health" > /dev/null; then
        print_success "Servidor Python iniciado"
    else
        print_error "No se pudo iniciar servidor"
        return 1
    fi
    
    # Iniciar Electron
    print_info "Iniciando interfaz Electron..."
    npm start &
    ELECTRON_PID=$!
    
    # Esperar señal de terminación
    wait $ELECTRON_PID
    
    # Limpiar
    kill $PYTHON_PID 2>/dev/null || true
}

case "${1:-}" in
    "--start")
        start_cilix
        ;;
    *)
        echo "Cilix Launcher Unificado v1.2"
        echo "Uso: $0 --start"
        ;;
esac
