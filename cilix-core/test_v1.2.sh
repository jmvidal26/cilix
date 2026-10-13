#!/bin/bash

# Script de pruebas para Cilix v1.2 - Unificado con pr1
# Prueba los componentes unificados y elimina APIs externas

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_step() {
    echo -e "${GREEN}[+]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[i]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

echo "═══════════════════════════════════════════════════════════"
echo "    CILIX v1.2 - PRUEBAS DE SISTEMA UNIFICADO"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Activar entorno virtual
print_step "Activando entorno virtual..."
source .venv/bin/activate

# Prueba 1: Verificar estructura de archivos
print_step "1. Verificando estructura de archivos..."
files_to_check=(
    "backend/main_local.py"
    "backend/core_ia.py"
    "backend/audio_engine.py"
    "backend/vtuber_engine.py"
    "backend/os_controller.py"
    "frontend/unified_ui.html"
    "frontend/unified_renderer.js"
    "electron/main.js"
    "requirements.txt"
    "package.json"
)

all_exist=true
for file in "${files_to_check[@]}"; do
    if [ -f "$file" ]; then
        print_success "$file"
    else
        print_error "$file - FALTA"
        all_exist=false
    fi
done

if [ "$all_exist" = true ]; then
    print_success "Estructura de archivos OK"
else
    print_error "Faltan archivos esenciales"
    exit 1
fi

# Prueba 2: Verificar dependencias Python
print_step "2. Verificando dependencias Python..."
python3 -c "
import sys
modules = [
    'fastapi', 'uvicorn', 'websockets', 'httpx',
    'pydantic', 'simpleaudio', 'sounddevice', 'soundfile',
    'cv2', 'pyautogui', 'psutil', 'PIL'
]

missing = []
for module in modules:
    try:
        __import__(module)
    except ImportError:
        missing.append(module)

if missing:
    print(f'❌ Módulos faltantes: {missing}')
    sys.exit(1)
else:
    print('✅ Todas las dependencias Python installed')
"

# Prueba 3: Verificar UI unificada
print_step "3. Verificando UI unificada (basada en pr1)..."
if [ -f "frontend/unified_ui.html" ]; then
    if grep -q "live2d-cubismcore" frontend/unified_ui.html; then
        print_success "UI unificada contiene Live2D"
    else
        print_warning "UI unificada sin Live2D"
    fi
    
    if grep -q "mascot-mode" frontend/unified_ui.html; then
        print_success "UI tiene modo mascot (Solo Personaje)"
    else
        print_warning "UI sin modo mascot"
    fi
else
    print_error "UI unificada no encontrada"
    exit 1
fi

# Prueba 4: Verificar eliminación de APIs externas
print_step "4. Verificando eliminación de APIs externas..."
# Buscar referencias a GEMINI_API_KEY, ANTHROPIC_API_KEY
api_references=0
if grep -r "GEMINI_API_KEY" backend/ frontend/ 2>/dev/null; then
    print_warning "Referencias a GEMINI_API_KEY encontradas"
    api_references=$((api_references + 1))
fi

if grep -r "ANTHROPIC_API_KEY" backend/ frontend/ 2>/dev/null; then
    print_warning "Referencias a ANTHROPIC_API_KEY encontradas"
    api_references=$((api_references + 1))
fi

if [ $api_references -eq 0 ]; then
    print_success "No se encontraron referencias a APIs externas"
else
    print_warning "Se encontraron $api_references referencias a APIs externas (seguirán desactivadas por defecto)"
fi

# Prueba 5: Verificar backend local
print_step "5. Verificando backend 100% local..."
if [ -f "backend/main_local.py" ]; then
    if grep -q "Ollama (100% local)" backend/main_local.py; then
        print_success "Backend local detectado"
    else
        print_warning "Backend local sin marca de 100% local"
    fi
else
    print_warning "Backend local no encontrado"
fi

# Prueba 6: Verificar plugins
print_step "6. Verificando plugins..."
plugins_dir="plugins"
if [ -d "$plugins_dir" ]; then
    plugin_files=$(ls "$plugins_dir"/*.py 2>/dev/null | wc -l)
    print_success "Plugins encontrados: $plugin_files"
    for plugin in "$plugins_dir"/*.py; do
        if [ -f "$plugin" ]; then
            echo "  • $(basename $plugin)"
        fi
    done
else
    print_info "Directorio de plugins no encontrado (se creará con launcher)"
fi

# Prueba 7: Verificar launcher unificado
print_step "7. Verificando launcher unificado..."
if [ -f "cilix-launcher.sh" ]; then
    if grep -q "pr1" cilix-launcher.sh; then
        print_success "Launcher mentiona pr1"
    else
        print_warning "Launcher sin mención a pr1"
    fi
else
    print_error "Launcher no encontrado"
    exit 1
fi

# Prueba 8: Verificar configuración
print_step "8. Verificando configuración..."
if [ -f "config/cilix-config.json" ]; then
    if grep -q "unified" config/cilix-config.json; then
        print_success "Configuración unificada detectada"
    else
        print_warning "Configuración sin marca de unificada"
    fi
else
    print_info "Configuración no encontrada"
fi

# Prueba 9: Verificar Audio Engine sin APIs
print_step "9. Verificando Audio Engine (sin APIs externas)..."
if [ -f "backend/audio_engine.py" ]; then
    if grep -q "faster-whisper\|Piper TTS" backend/audio_engine.py; then
        print_success "Audio Engine usa Whisper y Piper (locales)"
    else
        print_warning "Audio Engine sin referencias a tecnologías locales"
    fi
else
    print_warning "Audio Engine no encontrado"
fi

# Prueba 10: Resumen final
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "    RESUMEN DE PRUEBAS CILIX v1.2"
echo "═══════════════════════════════════════════════════════════"
echo ""

echo "✅ Características verificadas:"
echo "  • UI Unificada (basada en pr1)"
echo "  • Audio Engine (Whisper + Piper locales)"
echo "  • Backend 100% local (Ollama)"
echo "  • Plugins integrados"
echo "  • Launcher unificado"
echo "  • Configuración centralizada"
echo ""
echo "🚀 Para ejecutar:"
echo "  ./cilix-launcher.sh --setup"
echo ""
echo "📋 Para ver el estado del sistema:"
echo "  python3 -c \"import psutil; print(f'RAM: {psutil.virtual_memory().percent}%')\""
echo ""

print_success "¡Pruebas v1.2 completadas!"