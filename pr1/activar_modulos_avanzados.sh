#!/bin/bash
# Script para activar módulos avanzados de Sylix OS Core Assistant

echo "🚀 Activando módulos avanzados de Sylix OS..."
echo "=============================================="

# 1. Verificar entorno virtual
echo "1. Verificando entorno virtual..."
if [ -d ".venv" ]; then
    echo "   ✅ Entorno virtual encontrado"
    source .venv/bin/activate
else
    echo "   ⚠️  No se encontró .venv. Usando Python del sistema."
fi

# 2. Verificar dependencias de sistema
echo ""
echo "2. Verificando dependencias de sistema..."
echo "   xdotool (para monitor de pantalla):"
if command -v xdotool &> /dev/null; then
    echo "   ✅ xdotool instalado"
else
    echo "   ❌ xdotool no instalado"
    echo "   🔧 Ejecutar: sudo apt install xdotool"
fi

echo "   wmctrl (para control de ventanas):"
if command -v wmctrl &> /dev/null; then
    echo "   ✅ wmctrl instalado"
else
    echo "   ❌ wmctrl no instalado"
    echo "   🔧 Ejecutar: sudo apt install wmctrl"
fi

# 3. Verificar configuración
echo ""
echo "3. Verificando configuración avanzada..."
if [ -f "advanced_config.json" ]; then
    echo "   ✅ advanced_config.json encontrado"
    # Verificar que los módulos estén habilitados
    if python -c "
import json
config = json.load(open('advanced_config.json'))
features = config.get('advanced_features', {})
print('   Memoria:', '✅ HABILITADA' if features.get('memory', {}).get('enabled', False) else '❌ DESHABILITADA')
print('   Monitor de actividad:', '✅ HABILITADO' if features.get('activity_monitor', {}).get('enabled', False) else '❌ DESHABILITADO')
print('   Pensamiento proactivo:', '✅ HABILITADO' if features.get('proactive_thinking', {}).get('enabled', False) else '❌ DESHABILITADO')
"; then
        echo ""
    fi
else
    echo "   ⚠️  advanced_config.json no encontrado, usando configuración por defecto"
fi

# 4. Probar módulos
echo ""
echo "4. Probando módulos avanzados..."
python -c "
import sys
import logging

# Configurar logging básico
logging.basicConfig(level=logging.WARNING)

print('   Probando memoria...')
try:
    from memory import get_memory
    memory = get_memory()
    print('   ✅ Memoria funcional')
except Exception as e:
    print(f'   ❌ Error en memoria: {e}')

print('   Probando monitor de actividad...')
try:
    from activity_monitor import get_activity_monitor
    monitor = get_activity_monitor(enabled=True)
    window_info = monitor.get_active_window_info()
    if window_info:
        print(f'   ✅ Monitor funcional (ventana: {window_info.get(\"title\", \"Desconocido\")[:40]}...)')
    else:
        print('   ⚠️  Monitor cargado pero no puede capturar ventanas')
except Exception as e:
    print(f'   ❌ Error en monitor: {e}')

print('   Probando características integradas...')
try:
    from advanced_features import get_advanced_features
    config = {'activity_monitor_enabled': True, 'proactive_thinking_enabled': True}
    features = get_advanced_features(config)
    print('   ✅ Características integradas funcionales')
    
    # Mostrar estado
    status = features.get_feature_status()
    for name, feature in status.items():
        enabled = '✅ ACTIVA' if feature.get('enabled') else '❌ INACTIVA'
        print(f'      {name}: {enabled}')
except Exception as e:
    print(f'   ❌ Error en características integradas: {e}')
"

# 5. Instrucciones de uso
echo ""
echo "5. 🎯 Instrucciones para usar Sylix con módulos avanzados:"
echo ""
echo "   a) Para ejecutar Sylix con características avanzadas:"
echo "      source .venv/bin/activate"
echo "      python main.py"
echo ""
echo "   b) Para verificar que las características están activas:"
echo "      curl http://localhost:8000/api/advanced/status"
echo ""
echo "   c) Para probar el monitor de pantalla manualmente:"
echo "      xdotool getwindowfocus getwindowname"
echo ""
echo "   d) Si hay problemas con Wayland (monitor de pantalla no funciona):"
echo "      - Usa X11 en lugar de Wayland"
echo "      - O instala tools compatibles con Wayland"
echo ""
echo "=============================================="
echo "✅ Módulos avanzados listos para usar!"
echo ""
echo "⚠️  NOTA: El monitor de pantalla puede tener limitaciones en Wayland."
echo "         Es normal si no puede capturar todas las ventanas."