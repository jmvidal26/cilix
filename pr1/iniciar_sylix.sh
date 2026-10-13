#!/bin/bash
# Script para iniciar Sylix OS Core Assistant con características avanzadas

echo "🚀 Iniciando Sylix OS Core Assistant..."
echo "========================================"

# Verificar si estamos en Wayland
if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    echo "⚠️  Sesión Wayland detectada"
    echo "   El monitor de pantalla puede tener limitaciones en Wayland."
    echo "   xdotool/wmctrl funcionan mejor en X11."
    echo ""
    echo "🔧 Soluciones posibles:"
    echo "   1. Cambiar a sesión X11 en el login"
    echo "   2. Usar 'xhost +' para permitir acceso"
    echo "   3. Instalar herramientas compatibles con Wayland"
    echo ""
    read -p "¿Continuar de todas formas? (s/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Ss]$ ]]; then
        echo "⏹️  Inicio cancelado"
        exit 0
    fi
fi

# Activar entorno virtual
if [ -d ".venv" ]; then
    echo "🐍 Activando entorno virtual..."
    source .venv/bin/activate
else
    echo "⚠️  No se encontró entorno virtual .venv"
    echo "   Usando Python del sistema..."
fi

# Verificar dependencias críticas
echo "🔍 Verificando dependencias..."
if ! python -c "import numpy" &>/dev/null; then
    echo "❌ NumPy no está instalado"
    echo "🔧 Instalando dependencias..."
    pip install numpy
fi

# Iniciar servidor
echo ""
echo "🌐 Iniciando servidor Sylix..."
echo "   API: http://localhost:8000"
echo "   WebSocket: ws://localhost:8000/ws"
echo "   Interface web: http://localhost:8000/"
echo ""
echo "📋 Características avanzadas activas:"
python -c "
import json
try:
    config = json.load(open('advanced_config.json'))
    features = config.get('advanced_features', {})
    print('   🧠 Memoria persistente: ✅ SIEMPRE ACTIVA')
    print('   👁️  Monitor de actividad:', '✅ ACTIVO' if features.get('activity_monitor', {}).get('enabled', False) else '❌ OPcional')
    print('   💭 Pensamiento proactivo:', '✅ ACTIVO' if features.get('proactive_thinking', {}).get('enabled', False) else '❌ OPcional')
except:
    print('   ⚠️  Usando configuración por defecto')
    print('   🧠 Memoria persistente: ✅ SIEMPRE ACTIVA')
    print('   👁️  Monitor de actividad: ✅ OPcional')
    print('   💭 Pensamiento proactivo: ✅ OPcional')
"

echo ""
echo "⏳ Iniciando servidor (presiona Ctrl+C para detener)..."
echo "========================================"
echo ""

# Iniciar el servidor
python main.py

echo ""
echo "========================================"
echo "⏹️  Servidor detenido"
echo ""
echo "📝 Notas:"
echo "   - La memoria persistente se guarda en ~/.config/sylix/"
echo "   - Para habilitar/deshabilitar características:"
echo "     Editar advanced_config.json"
echo "   - Para ver estado: curl http://localhost:8000/api/advanced/status"
echo ""
echo "✅ Sylix OS Core Assistant cerrado"