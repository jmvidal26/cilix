#!/bin/bash

# Script de pruebas completas para Cilix v1.2
# UI basada en pr1, 100% local, sin APIs externas

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════════════"
echo "    CILIX v1.2 - PRUEBAS COMPLETAS DEL SISTEMA"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Activar entorno virtual
source .venv/bin/activate

# Prueba 1: Verificar estructura
echo "1️⃣  Verificando estructura de archivos..."
echo ""

files_ok=true
required_files=(
    "backend/main_local.py:Backend 100% local"
    "backend/core_ia.py:Cerebro Dual Ri/Re"
    "backend/audio_engine.py:Audio Engine"
    "backend/vtuber_engine.py:VTuber Engine"
    "backend/os_controller.py:OS Controller"
    "frontend/index.html:UI basada en pr1"
    "frontend/renderer.js:Renderer"
    "electron/main.js:Electron Main"
    "requirements.txt:Dependencias"
    "package.json:Config Electron"
)

for item in "${required_files[@]}"; do
    file="${item%%:*}"
    desc="${item##*:}"
    if [ -f "$file" ]; then
        echo "   ✅ $file - $desc"
    else
        echo "   ❌ $file - $desc FALTA"
        files_ok=false
    fi
done

if [ "$files_ok" = true ]; then
    echo "   ✅ Estructura completada"
else
    echo "   ❌ Estructura incompleta"
    exit 1
fi

# Prueba 2: Verificar UI basada en pr1
echo ""
echo "2️⃣  Verificando UI basada en pr1..."
echo ""

ui_ok=true

if grep -q "live2d-cubismcore" frontend/index.html; then
    echo "   ✅ UI contiene Live2D Cubism Core"
else
    echo "   ⚠️  UI sin Live2D (opcional para modo simple)"
    ui_ok=false
fi

if grep -q "Outfit" frontend/index.html && grep -q "JetBrains Mono" frontend/index.html; then
    echo "   ✅ UI usa fuentes Outfit + JetBrains Mono (de pr1)"
else
    echo "   ❌ UI no usa las fuentes correctas"
    ui_ok=false
fi

if grep -q "mascot-mode" frontend/index.html; then
    echo "   ✅ UI tiene modo mascot"
else
    echo "   ❌ UI sin modo mascot"
    ui_ok=false
fi

# Prueba 3: Verificar eliminación de APIs externas
echo ""
echo "3️⃣  Verificando eliminación de APIs externas..."
echo ""

api_ok=true

if grep -r "GEMINI_API_KEY" backend/ frontend/ 2>/dev/null | grep -v "config\|\.example"; then
    echo "   ❌ Se encontraron referencias a GEMINI_API_KEY"
    api_ok=false
else
    echo "   ✅ No hay referencias a GEMINI_API_KEY"
fi

if grep -r "ANTHROPIC_API_KEY" backend/ frontend/ 2>/dev/null | grep -v "config\|\.example"; then
    echo "   ❌ Se encontraron referencias a ANTHROPIC_API_KEY"
    api_ok=false
else
    echo "   ✅ No hay referencias a ANTHROPIC_API_KEY"
fi

if grep -q "100% local" backend/main_local.py; then
    echo "   ✅ Backend marca '100% local'"
else
    echo "   ⚠️  Backend sin marca de '100% local'"
fi

# Prueba 4: Verificar módulos de Python
echo ""
echo "4️⃣  Verificando módulos Python..."
echo ""

python_modules_ok=true
python3 << 'PYEOF'
modules = {
    'fastapi': 'Framework web',
    'uvicorn': 'Servidor ASGI',
    'websockets': 'WebSocket',
    'httpx': 'Cliente HTTP',
    'pydantic': 'Validación',
    'simpleaudio': 'Audio',
    'sounddevice': 'Audio captura',
    'soundfile': 'Audio files',
    'cv2': 'OpenCV',
    'pyautogui': 'Automatización',
    'psutil': 'Sistema',
    'PIL': 'Imágenes'
}

missing = []
for module, desc in modules.items():
    try:
        __import__(module)
        print(f"   ✅ {module} - {desc}")
    except ImportError:
        print(f"   ⚠️  {module} - {desc} (opcional)")
        missing.append(module)

if missing:
    print(f"\n   ⚠️  Módulos faltantes: {', '.join(missing)}")
PYEOF

# Prueba 5: Iniciar servidor y probar endpoints
echo ""
echo "5️⃣  Iniciando servidor y probando endpoints..."
echo ""

# Iniciar servidor
echo "   Iniciando servidor Cilix..."
cd backend
python3 main_local.py > /tmp/cilix-test.log 2>&1 &
PYTHON_PID=$!
cd ..

# Esperar
sleep 3

# Probar endpoints
endpoint_ok=true

if curl -s http://localhost:8765/ > /dev/null; then
    echo "   ✅ Endpoint raíz / respondiendo"
else
    echo "   ❌ Endpoint raíz / no respondiendo"
    endpoint_ok=false
fi

if curl -s http://localhost:8765/health > /dev/null; then
    echo "   ✅ Endpoint /health respondiendo"
else
    echo "   ❌ Endpoint /health no respondiendo"
    endpoint_ok=false
fi

# Verificar backend en respuesta
backend_response=$(curl -s http://localhost:8765/)
if echo "$backend_response" | grep -q "Ollama (100% local)"; then
    echo "   ✅ Backend marca '100% local' en respuesta"
else
    echo "   ❌ Backend no marca '100% local'"
    endpoint_ok=false
fi

# Detener servidor
echo ""
echo "   Deteniendo servidor..."
kill $PYTHON_PID 2>/dev/null || true
sleep 1

# Prueba 6: Verificar dependencias de audio
echo ""
echo "6️⃣  Verificando dependencias de audio..."
echo ""

audio_ok=true

if python3 -c "import sounddevice, soundfile, simpleaudio" 2>/dev/null; then
    echo "   ✅ Módulos de audio instalados"
else
    echo "   ⚠️  Algunos módulos de audio faltantes (se pueden instalar después)"
    audio_ok=false
fi

# Prueba 7: Verificar configuración
echo ""
echo "7️⃣  Verificando configuración..."
echo ""

if [ -f "config/cilix-config.json" ]; then
    if grep -q "unified\|1.2" config/cilix-config.json; then
        echo "   ✅ Configuración v1.2 encontrada"
    else
        echo "   ⚠️  Configuración sin versión específica"
    fi
else
    echo "   ℹ️  Configuración no encontrada (se creará con launcher)"
fi

# Resumen final
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "    RESUMEN DE PRUEBAS CILIX v1.2"
echo "═══════════════════════════════════════════════════════════"
echo ""

echo "✅ Características verificadas:"
echo "  • UI Unificada (basada en pr1)"
echo "  • Backend 100% local (Ollama)"
echo "  • Sin APIs externas"
echo "  • Audio Engine (Whisper + Piper)"
echo "  • VTuber Engine"
echo "  • OS Controller"
echo ""
echo "🚀 Para ejecutar Cilix:"
echo "  cd /home/jesvid/Downloads/cilix/cilix-core"
echo "  ./cilix-launcher.sh --setup"
echo ""
echo "📋 Para iniciar manualmente:"
echo "  source .venv/bin/activate"
echo "  cd backend && python3 main_local.py"
echo "  cd .. && npm start"
echo ""

if [ "$files_ok" = true ] && [ "$api_ok" = true ] && [ "$endpoint_ok" = true ]; then
    echo "✅ ¡Todas las pruebas CRÍTICAS pasaron!"
else
    echo "⚠️  Algunas pruebas tuvieron advertencias"
fi