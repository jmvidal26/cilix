#!/bin/bash

# Cilix Setup Light - Versión simplificada para instalación inicial
# Instala solo lo esencial para evitar problemas

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

print_error() {
    echo -e "\033[0;31m[✗]\033[0m $1"
}

print_success() {
    echo -e "\033[0;32m[✓]\033[0m $1"
}

check_basic_requirements() {
    print_step "Verificando requisitos básicos..."
    
    # Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 no encontrado"
        exit 1
    fi
    
    # Node.js
    if ! command -v node &> /dev/null; then
        print_warning "Node.js no encontrado (algunas funciones no estarán disponibles)"
    fi
    
    print_success "Requisitos básicos OK"
}

setup_virtualenv() {
    print_step "Configurando entorno virtual..."
    
    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
        print_success "Entorno virtual creado"
    else
        print_info "Entorno virtual ya existe"
    fi
    
    source "$VENV_DIR/bin/activate"
    print_info "Entorno virtual activado"
}

install_core_deps() {
    print_step "Instalando dependencias principales..."
    
    # Actualizar pip
    pip install --upgrade pip
    
    # Lista de dependencias esenciales (sin problemas conocidos)
    CORE_DEPS=(
        "fastapi==0.115.0"
        "uvicorn[standard]==0.31.0"
        "websockets==13.1"
        "httpx==0.27.0"
        "pydantic==2.8.0"
        "simpleaudio==1.0.4"
        "sounddevice==0.5.2"
        "soundfile==0.12.1"
        "opencv-python==4.10.0.84"
        "pyautogui==0.9.54"
        "psutil==5.9.8"
        "pillow==10.4.0"
        "numpy==1.26.4"
    )
    
    for dep in "${CORE_DEPS[@]}"; do
        print_info "Instalando: $dep"
        pip install "$dep" || print_warning "Problema con $dep, continuando..."
    done
    
    # Intentar torch más tarde si es necesario
    print_info "Instalando torch (esto puede tomar tiempo)..."
    pip install torch==2.2.0 torchaudio==2.2 --index-url https://download.pytorch.org/whl/cpu || \
        print_warning "Torch puede instalarse manualmente después"
    
    print_success "Dependencias principales instaladas"
}

install_optional_deps() {
    print_step "Instalando dependencias opcionales..."
    
    # Dependencias que podrían fallar pero no son críticas
    OPTIONAL_DEPS=(
        "onnxruntime==1.18.0"
        "pygame==2.5.2"
        "python-socketio==5.11.2"
        "py-cpuinfo==9.0.0"
        "screeninfo==0.8.1"
    )
    
    for dep in "${OPTIONAL_DEPS[@]}"; do
        print_info "Intentando: $dep"
        pip install "$dep" 2>/dev/null || print_info "  Saltando $dep (opcional)"
    done
    
    print_success "Dependencias opcionales procesadas"
}

setup_nodejs() {
    if ! command -v npm &> /dev/null; then
        print_warning "npm no encontrado, saltando dependencias Node.js"
        return
    fi
    
    print_step "Instalando dependencias Node.js..."
    
    if [ -f "package.json" ]; then
        npm install
        
        # Instalar Live2D solo si existe el directorio frontend
        if [ -d "frontend" ]; then
            print_info "Instalando Live2D WebGL..."
            cd frontend
            npm init -y 2>/dev/null || true
            npm install live2d-cubism-webgl 2>/dev/null || print_warning "Live2D no instalado"
            cd "$SCRIPT_DIR"
        fi
        
        print_success "Dependencias Node.js instaladas"
    else
        print_warning "package.json no encontrado"
    fi
}

setup_ollama_light() {
    print_step "Configurando Ollama (modo ligero)..."
    
    if command -v ollama &> /dev/null; then
        print_info "Ollama ya está instalado"
        
        # Verificar si está corriendo
        if ! pgrep -x "ollama" > /dev/null; then
            print_info "Iniciando Ollama..."
            ollama serve > /tmp/ollama-cilix.log 2>&1 &
            sleep 3
        fi
        
        # Descargar modelos básicos
        print_info "Descargando modelo Ri (qwen2.5:1.5b)..."
        ollama pull qwen2.5:1.5b 2>/dev/null || print_warning "No se pudo descargar modelo Ri"
        
    else
        print_warning "Ollama no instalado. Instala manualmente:"
        print_info "  curl -fsSL https://ollama.ai/install.sh | sh"
        print_info "  Luego: ollama pull qwen2.5:1.5b"
    fi
    
    print_success "Ollama configurado (modo ligero)"
}

setup_vtuber_assets_light() {
    print_step "Configurando assets VTuber..."
    
    ASSETS_DIR="$SCRIPT_DIR/assets"
    mkdir -p "$ASSETS_DIR"
    
    print_info "Estructura de assets creada en $ASSETS_DIR"
    print_info "Coloca manualmente el modelo Design_genius_white en assets/"
    
    # Crear estructura básica
    mkdir -p "$ASSETS_DIR"/{models,textures,expressions}
    
    print_success "Estructura VTurer preparada"
}

verify_installation() {
    print_step "Verificando instalación..."
    
    source "$VENV_DIR/bin/activate"
    
    # Verificar módulos principales
    python3 -c "
import sys
modules_to_check = [
    'fastapi', 'uvicorn', 'websockets', 'httpx',
    'pydantic', 'simpleaudio', 'sounddevice', 'soundfile',
    'cv2', 'pyautogui', 'psutil', 'PIL'
]

for module in modules_to_check:
    try:
        __import__(module)
        print(f'✅ {module}')
    except ImportError as e:
        print(f'⚠️  {module}: {e}')
"
    
    # Verificar estructura de archivos
    print_info "Verificando estructura..."
    if [ -f "backend/main.py" ]; then
        print_success "backend/main.py encontrado"
    else
        print_error "Falta backend/main.py"
    fi
    
    print_success "Verificación completada"
}

create_run_script() {
    print_step "Creando script de ejecución..."
    
    cat > "run-cilix.sh" << 'EOF'
#!/bin/bash
# Script para ejecutar Cilix (modo ligero)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activar entorno virtual
source .venv/bin/activate

# Iniciar servidor Python
cd backend
python3 main.py &
PYTHON_PID=$!
cd ..

# Esperar un momento
sleep 2

# Verificar servidor
if curl -s http://localhost:8765/health > /dev/null; then
    echo "✅ Servidor iniciado en http://localhost:8765"
else
    echo "❌ No se pudo iniciar servidor"
    exit 1
fi

# Iniciar Electron si está disponible
if command -v npm &> /dev/null && [ -f "package.json" ]; then
    echo "🚀 Iniciando interfaz Electron..."
    npm start
else
    echo "ℹ️  Electron no disponible, solo servidor API"
    echo "📡 WebSocket: ws://localhost:8765/ws"
    echo "🛑 Presiona Ctrl+C para detener"
    wait $PYTHON_PID
fi
EOF
    
    chmod +x "run-cilix.sh"
    print_success "Script de ejecución creado: ./run-cilix.sh"
}

show_summary() {
    print_step "=== RESUMEN DE INSTALACIÓN ==="
    echo ""
    echo "✅ Dependencias principales instaladas"
    echo "✅ Entorno virtual configurado"
    echo "✅ Estructura preparada"
    echo ""
    echo "🎯 Próximos pasos manuales:"
    echo "  1. Instala Ollama si no lo tienes:"
    echo "     curl -fsSL https://ollama.ai/install.sh | sh"
    echo "  2. Descarga modelos: ollama pull qwen2.5:1.5b"
    echo "  3. Copia modelo VTurer:"
    echo "     cp -r ../design_genius_white/* assets/"
    echo ""
    echo "🚀 Para ejecutar:"
    echo "  ./run-cilix.sh"
    echo ""
    echo "🔧 Para instalación completa:"
    echo "  ./cilix-launcher.sh --setup"
    echo ""
    print_success "¡Instalación ligera completada!"
}

main() {
    echo "=== CILIX SETUP LIGHT ==="
    echo "Instalación simplificada para evitar problemas"
    echo ""
    
    check_basic_requirements
    setup_virtualenv
    install_core_deps
    install_optional_deps
    setup_nodejs
    setup_ollama_light
    setup_vtuber_assets_light
    verify_installation
    create_run_script
    show_summary
}

# Ejecutar
main "$@"