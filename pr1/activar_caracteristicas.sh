#!/bin/bash
# Script de activación automática para características avanzadas de Sylix OS Core

echo "🚀 Activando características avanzadas de Sylix OS Core..."
echo "📁 Directorio: $(pwd)"
echo ""

# Activar entorno virtual si existe
if [ -d ".venv" ]; then
    echo "✅ Activando entorno virtual..."
    source .venv/bin/activate
fi

# Ejecutar script de diagnóstico y activación
python3 diagnosticar_modulos.py

echo ""
echo "🎯 Para usar las características avanzadas:"
echo "   1. Inicia el servidor: ./start_sylix.sh"
echo "   2. Accede al panel: http://localhost:8000/advanced"
echo "   3. Activa características desde el panel web"
echo ""
echo "✅ Activación completada!"
