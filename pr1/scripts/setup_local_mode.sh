#!/bin/bash
# Script de configuración automática para modo local (Ollama/Offline)

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()    { echo -e "${GREEN}[✓]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[⚠]${NC} $*"; }
log_error()   { echo -e "${RED}[✗]${NC} $*"; }
log_section() { echo -e "\n${CYAN}── $* ──────────────────────────${NC}"; }

echo "╔═══════════════════════════════════════════════════════╗"
echo "║   CONFIGURACIÓN MODO LOCAL - SYLIX OS CORE v1.1.0    ║"
echo "║        Ollama • Piper TTS • Optimizaciones           ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

log_section "1. Verificando sistema"
# Verificar Python
if ! command -v python3 &>/dev/null; then
    log_error "Python 3 no encontrado"
    echo "Instala con: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi
log_info "Python 3 disponible"

# Verificar RAM
if command -v free &>/dev/null; then
    total_ram=$(free -m | awk '/^Mem:/{print $2}')
    if [ "$total_ram" -lt 2048 ]; then
        log_warn "RAM baja ($total_ram MB). Recomendado: 4+ GB para modo local"
    else
        log_info "RAM: $total_ram MB (adecuada)"
    fi
fi

log_section "2. Configurando entorno Python"
if [ ! -d ".venv" ]; then
    log_info "Creando entorno virtual..."
    python3 -m venv .venv
fi

# Activar entorno
source .venv/bin/activate

# Instalar dependencias básicas
log_info "Instalando dependencias optimizadas..."
pip install -U pip setuptools wheel
pip install httpx>=0.27.0 numpy>=1.26.0 psutil>=7.0.0

log_section "3. Configurando Ollama (modo local)"
if ! command -v ollama &>/dev/null; then
    log_warn "Ollama no instalado"
    echo ""
    echo "📦 Para instalar Ollama:"
    echo "   1. Visita: https://ollama.com/download"
    echo "   2. O ejecuta: curl -fsSL https://ollama.com/install.sh | sh"
    echo ""
    read -p "¿Continuar sin Ollama? (s/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Ss]$ ]]; then
        echo "Instala Ollama y vuelve a ejecutar este script."
        exit 0
    fi
else
    log_info "Ollama instalado"
    
    # Verificar si está corriendo
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        log_info "Ollama está corriendo"
        
        # Mostrar modelos instalados
        models=$(curl -s http://localhost:11434/api/tags | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    models = [m['name'] for m in data.get('models', [])]
    print('\\n'.join(models[:5]))
except:
    print('')
")
        
        if [ -n "$models" ]; then
            log_info "Modelos disponibles:"
            echo "$models" | while read model; do
                echo "   • $model"
            done
        else
            log_warn "No hay modelos instalados"
        fi
    else
        log_warn "Ollama no está corriendo"
        echo "Ejecuta en otra terminal: ollama serve"
    fi
fi

log_section "4. Instalando modelo recomendado"
echo "📦 Modelos recomendados para Sylix OS Core:"
echo "   1. qwen2.5:1.5b (900 MB) - Buen balance velocidad/calidad"
echo "   2. llama3.2:3b (1.8 GB) - Alta calidad con tool calling"
echo "   3. mistral:7b (4.1 GB) - Muy potente (más RAM requerida)"
echo ""

read -p "¿Instalar qwen2.5:1.5b (recomendado)? (s/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Ss]$ ]] && command -v ollama &>/dev/null; then
    log_info "Instalando qwen2.5:1.5b..."
    ollama pull qwen2.5:1.5b
    log_info "Modelo instalado ✓"
fi

log_section "5. Configurando TTS offline"
# Verificar Piper TTS
piper_model="models/piper/es_ES-sharvard-medium.onnx"
if [ -f "$piper_model" ]; then
    log_info "Piper TTS disponible ($(du -h "$piper_model" | cut -f1))"
else
    log_warn "Piper TTS no encontrado en $piper_model"
    echo "💡 Descarga el modelo español desde:"
    echo "   https://github.com/rhasspy/piper/releases"
    echo "   Busca: 'es_ES-sharvard-medium.onnx'"
fi

# Verificar reproductor de audio
if command -v paplay &>/dev/null; then
    log_info "paplay disponible (PipeWire/PulseAudio)"
elif command -v aplay &>/dev/null; then
    log_info "aplay disponible (ALSA)"
else
    log_warn "No se encontró reproductor de audio"
    echo "Instala: sudo apt install pulseaudio-utils alsa-utils"
fi

log_section "6. Configurando entorno .env"
env_file=".env"
if [ ! -f "$env_file" ]; then
    log_info "Creando archivo .env..."
    cat > "$env_file" << 'EOF'
# Modo Local (Offline) - Configuración optimizada
OLLAMA_MODEL=qwen2.5:1.5b
OLLAMA_BASE_URL=http://localhost:11434

# TTS Offline
EDGE_TTS_VOICE=es-CO-SalomeNeural
EDGE_TTS_RATE=+10%
EDGE_TTS_PITCH=+5Hz

# Características avanzadas (modo local)
ADVANCED_FEATURES_ENABLED=true
LOCAL_MODE_OPTIMIZED=true

# Performance
MAX_RESPONSE_TOKENS=256
TTS_CHUNK_SIZE=100
TOOL_CALL_TIMEOUT=10
EOF
    log_info "Archivo .env creado ✓"
else
    log_info "Archivo .env ya existe"
    
    # Actualizar configuración para modo local
    if ! grep -q "LOCAL_MODE_OPTIMIZED" "$env_file"; then
        echo -e "\n# Modo local optimizado\nLOCAL_MODE_OPTIMIZED=true" >> "$env_file"
        log_info "Configuración de modo local añadida ✓"
    fi
fi

log_section "7. Verificando estructura del proyecto"
# Crear directorios necesarios
for dir in logs scripts tests; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        log_info "Directorio creado: $dir/"
    fi
done

# Verificar archivos principales
for file in main.py requirements.txt run.sh; do
    if [ -f "$file" ]; then
        log_info "Archivo presente: $file"
    else
        log_error "Archivo faltante: $file"
    fi
done

log_section "8. Prueba final"
echo "🎯 Configuración completada. Para probar:"
echo ""
echo "   🔧 Verificar optimizaciones:"
echo "        python scripts/check_optimizations.py"
echo ""
echo "   🚀 Iniciar Sylix en modo local optimizado:"
echo "        ./start_sylix.sh"
echo ""
echo "   🤖 Probar características avanzadas:"
echo "        python tests/test_advanced_integration.py"
echo ""
echo "   📊 Monitorear recursos:"
echo "        watch -n 2 'free -m && echo && ps aux | grep -E \"(ollama|python)\"'"
echo ""
echo "💡 Consejos para modo local:"
echo "   • Mantén Ollama corriendo: ollama serve"
echo "   • Usa modelos ligeros para mejor rendimiento"
echo "   • Activa características avanzadas gradualmente"
echo "   • Monitorea uso de RAM con 'htop' o 'free -m'"
echo ""
echo "✅ Configuración de modo local completada ✓"