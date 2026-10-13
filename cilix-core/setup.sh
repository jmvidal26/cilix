#!/bin/bash

# Script de instalación y configuración para Cilix Assistant
# Optimizado para sistemas Linux con 8GB RAM

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║                   Cilix Assistant Setup                  ║"
    echo "║           Asistente local con VTuber - 100% offline      ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_step() {
    echo -e "${GREEN}[+]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[!]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

check_requirements() {
    print_step "Verificando requisitos del sistema..."
    
    # Verificar sistema operativo
    if [[ "$OSTYPE" != "linux-gnu"* ]]; then
        print_warning "Este script está optimizado para Linux. Continuando con precaución..."
    fi
    
    # Verificar Python
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
        print_success "Python $PYTHON_VERSION encontrado"
    else
        print_error "Python 3 no encontrado. Instala: sudo apt install python3 python3-pip"
        exit 1
    fi
    
    # Verificar Node.js
    if command -v node &> /dev/null; then
        NODE_VERSION=$(node --version)
        print_success "Node.js $NODE_VERSION encontrado"
    else
        print_error "Node.js no encontrado. Instala: sudo apt install nodejs npm"
        exit 1
    fi
    
    # Verificar RAM (aproximado)
    TOTAL_RAM=$(free -g | awk '/^Mem:/{print $2}')
    if [ "$TOTAL_RAM" -lt 6 ]; then
        print_warning "Sistema con solo ${TOTAL_RAM}GB RAM detectado"
        print_warning "Cilix está optimizado para 8GB. Algunas funciones pueden ser limitadas."
    else
        print_success "RAM disponible: ${TOTAL_RAM}GB"
    fi
    
    # Verificar Ollama
    if command -v ollama &> /dev/null; then
        print_success "Ollama encontrado"
    else
        print_warning "Ollama no encontrado. Se instalará más adelante."
    fi
}

install_python_deps() {
    print_step "Instalando dependencias de Python..."
    
    # Actualizar pip
    python3 -m pip install --upgrade pip
    
    # Instalar dependencias del archivo requirements.txt
    if [ -f "requirements.txt" ]; then
        python3 -m pip install -r requirements.txt
        print_success "Dependencias de Python instaladas"
    else
        print_error "Archivo requirements.txt no encontrado"
        exit 1
    fi
    
    # Instalar dependencias adicionales específicas del sistema
    print_step "Instalando dependencias del sistema..."
    
    # Para Ubuntu/Debian
    if command -v apt &> /dev/null; then
        sudo apt update
        sudo apt install -y \
            portaudio19-dev \
            python3-dev \
            libasound2-dev \
            libjack-dev \
            ffmpeg \
            libsm6 \
            libxext6 \
            libxrender-dev
    fi
    
    # Para Fedora
    if command -v dnf &> /dev/null; then
        sudo dnf install -y \
            portaudio-devel \
            python3-devel \
            alsa-lib-devel \
            jack-audio-connection-kit-devel \
            ffmpeg \
            libSM \
            libXext \
            libXrender
    fi
}

install_node_deps() {
    print_step "Instalando dependencias de Node.js..."
    
    if [ -f "package.json" ]; then
        npm install
        print_success "Dependencias de Node.js instaladas"
    else
        print_error "Archivo package.json no encontrado"
        exit 1
    fi
}

setup_ollama() {
    print_step "Configurando Ollama..."
    
    if ! command -v ollama &> /dev/null; then
        print_step "Instalando Ollama..."
        
        # Descargar e instalar Ollama
        curl -fsSL https://ollama.ai/install.sh | sh
        
        if command -v ollama &> /dev/null; then
            print_success "Ollama instalado"
        else
            print_error "No se pudo instalar Ollama"
            print_warning "Instala manualmente desde: https://ollama.ai"
            return 1
        fi
    fi
    
    # Iniciar Ollama en segundo plano si no está corriendo
    if ! pgrep -x "ollama" > /dev/null; then
        print_step "Iniciando servidor Ollama..."
        ollama serve > /tmp/ollama.log 2>&1 &
        OLLAMA_PID=$!
        echo $OLLAMA_PID > /tmp/ollama.pid
        sleep 5
        
        if kill -0 $OLLAMA_PID 2>/dev/null; then
            print_success "Servidor Ollama iniciado (PID: $OLLAMA_PID)"
        else
            print_error "No se pudo iniciar Ollama"
            return 1
        fi
    else
        print_success "Ollama ya está corriendo"
    fi
    
    # Descargar modelos necesarios
    print_step "Descargando modelos de IA..."
    
    # Modelo para Ri (hermana menor) - ligero
    print_step "Descargando modelo Ri (qwen2.5:1.5b)..."
    ollama pull qwen2.5:1.5b
    
    # Modelo para Re (hermana mayor) - especialista
    print_step "Descargando modelo Re (deepseek-coder:1.3b)..."
    ollama pull deepseek-coder:1.3b
    
    # Modelos alternativos (opcionales)
    print_step "Descargando modelos alternativos..."
    ollama pull llama3.2:1b
    ollama pull phi3:mini
    
    print_success "Modelos de IA configurados"
}

setup_tts_voices() {
    print_step "Configurando voces TTS (Piper)..."
    
    # Crear directorio para voces
    VOICES_DIR="$HOME/.cache/cilix/voices"
    mkdir -p "$VOICES_DIR"
    
    print_step "Descargando modelos de voz femeninos..."
    
    # Modelos de voz femeninos pre-entrenados para Piper
    # Estos son enlaces de ejemplo - en producción usar URLs reales
    
    print_warning "Descarga manual requerida para modelos de voz"
    echo ""
    echo "Para voces femeninas de Piper TTS:"
    echo "1. Visita: https://github.com/rhasspy/piper-tts"
    echo "2. Descarga modelos .onnx de voces femeninas"
    echo "3. Colócalos en: $VOICES_DIR/"
    echo ""
    echo "Ejemplos recomendados:"
    echo "  - female-light (voz ligera y amigable)"
    echo "  - female-warm (voz cálida y expresiva)"
    echo ""
    read -p "Presiona Enter para continuar..."
    
    # Verificar si hay modelos descargados
    if ls "$VOICES_DIR"/*.onnx 1> /dev/null 2>&1; then
        print_success "Modelos de voz encontrados en $VOICES_DIR"
    else
        print_warning "No se encontraron modelos de voz"
        print_warning "Cilix usará TTS simulado hasta que instales voces reales"
    fi
}

create_desktop_entry() {
    print_step "Creando entrada de escritorio..."
    
    DESKTOP_FILE="$HOME/.local/share/applications/cilix.desktop"
    
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Cilix Assistant
Comment=Asistente local con VTuber - 100% offline
Exec=$(pwd)/run.sh
Icon=$(pwd)/assets/cilix-icon.png
Terminal=false
Type=Application
Categories=Utility;Application;
StartupNotify=true
Keywords=ai;assistant;vtuber;local
EOF
    
    chmod +x "$DESKTOP_FILE"
    print_success "Entrada de escritorio creada: $DESKTOP_FILE"
}

create_run_script() {
    print_step "Creando script de ejecución..."
    
    cat > "run.sh" << 'EOF'
#!/bin/bash

# Script de ejecución para Cilix Assistant

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[Cilix]${NC} $1"
}

print_error() {
    echo -e "${RED}[Error]${NC} $1"
}

# Verificar dependencias
check_dependencies() {
    # Verificar Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 no encontrado"
        exit 1
    fi
    
    # Verificar Node.js
    if ! command -v node &> /dev/null; then
        print_error "Node.js no encontrado"
        exit 1
    fi
    
    # Verificar Ollama
    if ! command -v ollama &> /dev/null; then
        print_error "Ollama no encontrado. Ejecuta ./setup.sh primero."
        exit 1
    fi
}

# Iniciar Ollama si no está corriendo
start_ollama() {
    if ! pgrep -x "ollama" > /dev/null; then
        print_status "Iniciando Ollama..."
        ollama serve > /tmp/ollama-cilix.log 2>&1 &
        OLLAMA_PID=$!
        echo $OLLAMA_PID > /tmp/ollama-cilix.pid
        sleep 3
    fi
}

# Detener Ollama al salir
cleanup() {
    if [ -f "/tmp/ollama-cilix.pid" ]; then
        OLLAMA_PID=$(cat /tmp/ollama-cilix.pid)
        if kill -0 $OLLAMA_PID 2>/dev/null; then
            print_status "Deteniendo Ollama..."
            kill $OLLAMA_PID
            rm /tmp/ollama-cilix.pid
        fi
    fi
}

# Configurar trap para limpieza
trap cleanup EXIT

# Función principal
main() {
    print_status "Iniciando Cilix Assistant..."
    
    # Verificar dependencias
    check_dependencies
    
    # Iniciar Ollama
    start_ollama
    
    # Iniciar servidor Python en segundo plano
    print_status "Iniciando servidor Python..."
    cd backend
    python3 main.py > /tmp/cilix-python.log 2>&1 &
    PYTHON_PID=$!
    cd ..
    
    # Esperar que el servidor Python inicie
    sleep 2
    
    # Verificar que el servidor esté corriendo
    if curl -s http://localhost:8765/health > /dev/null; then
        print_status "Servidor Python iniciado"
    else
        print_error "No se pudo iniciar servidor Python"
        exit 1
    fi
    
    # Iniciar aplicación Electron
    print_status "Iniciando interfaz Electron..."
    npm start
    
    # Cuando Electron cierre, terminar procesos hijos
    print_status "Cerrando Cilix..."
    kill $PYTHON_PID 2>/dev/null || true
}

# Ejecutar
main
EOF
    
    chmod +x "run.sh"
    print_success "Script de ejecución creado: run.sh"
}

run_tests() {
    print_step "Ejecutando pruebas básicas..."
    
    # Probar Python
    print_step "Probando módulos Python..."
    cd backend
    python3 -c "import sys; print('✅ Python OK')"
    
    # Probar importaciones básicas
    python3 -c "
try:
    import fastapi
    import uvicorn
    import websockets
    print('✅ Dependencias principales OK')
except ImportError as e:
    print(f'❌ Error: {e}')
    sys.exit(1)
    "
    cd ..
    
    # Probar Node.js
    print_step "Probando Node.js..."
    node -e "console.log('✅ Node.js OK')"
    
    # Probar Ollama
    print_step "Probando Ollama..."
    if command -v ollama &> /dev/null; then
        if ollama list 2>/dev/null | grep -q "qwen2.5:1.5b"; then
            print_success "Modelo Ri encontrado"
        else
            print_warning "Modelo Ri no encontrado"
        fi
    fi
    
    print_success "Pruebas completadas"
}

print_summary() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║                INSTALACIÓN COMPLETADA                   ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${GREEN}✅ Cilix Assistant ha sido instalado exitosamente${NC}"
    echo ""
    echo "📋 Resumen de la instalación:"
    echo "  • Dependencias de Python instaladas"
    echo "  • Dependencias de Node.js instaladas"
    echo "  • Ollama configurado con modelos Ri/Re"
    echo "  • Script de ejecución creado: ./run.sh"
    echo "  • Entrada de escritorio creada"
    echo ""
    echo "🚀 Para iniciar Cilix:"
    echo "  1. Asegúrate que Ollama esté corriendo: ollama serve"
    echo "  2. Ejecuta: ./run.sh"
    echo "  3. O busca 'Cilix' en el menú de aplicaciones"
    echo ""
    echo "🔧 Configuración adicional:"
    echo "  • Voces TTS: Descarga modelos de Piper a ~/.cache/cilix/voices/"
    echo "  • Personalización: Edita los archivos en backend/ y frontend/"
    echo ""
    echo "📚 Documentación:"
    echo "  • Lee README.md para más detalles"
    echo "  • Visita issues en GitHub para soporte"
    echo ""
    echo -e "${YELLOW}⚠️  IMPORTANTE: Cilix está optimizado para sistemas con 8GB RAM${NC}"
    echo -e "${YELLOW}   Monitoriza el uso de recursos durante las primeras ejecuciones${NC}"
    echo ""
}

main() {
    print_header
    
    # Verificar que estamos en el directorio correcto
    if [ ! -f "requirements.txt" ] || [ ! -f "package.json" ]; then
        print_error "Ejecuta este script desde el directorio cilix-core/"
        exit 1
    fi
    
    # Ejecutar pasos de instalación
    check_requirements
    install_python_deps
    install_node_deps
    setup_ollama
    setup_tts_voices
    create_run_script
    create_desktop_entry
    run_tests
    print_summary
}

# Ejecutar función principal
main "$@"