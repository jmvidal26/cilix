#!/bin/bash
# Script de inicio simplificado para Sylix OS Core
# Versión optimizada para desarrollo con características avanzadas

echo "╔═══════════════════════════════════════════════════════╗"
echo "║      SYLIX OS CORE - DESARROLLO AVANZADO v1.1.0      ║"
echo "║  Memoria persistente • Monitor actividad • Proactivo ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""
echo "📁 Directorio: $(pwd)"
echo ""

# Verificar entorno virtual
if [ -d ".venv" ]; then
    echo "✅ Activando entorno virtual..."
    source .venv/bin/activate
else
    echo "⚠️  Entorno virtual no encontrado. Ejecuta primero: ./run.sh"
    exit 1
fi

# Verificación rápida de dependencias
echo "🔍 Verificación rápida del sistema..."
if python -c "import fastapi, anthropic, google.generativeai" 2>/dev/null; then
    echo "✅ Dependencias principales OK"
else
    echo "⚠️  Algunas dependencias faltan. Ejecuta: ./run.sh --install"
fi

echo ""
echo "🌐 INICIANDO SERVIDOR..."
echo "─────────────────────────────────────────────────────"
echo ""
echo "📡 Endpoints que estarán disponibles:"
echo "   • Interfaz principal:  http://localhost:8000"
echo "   • Panel avanzado:     http://localhost:8000/advanced"
echo "   • API de salud:       http://localhost:8000/health"
echo "   • API avanzada:       http://localhost:8000/api/advanced/*"
echo ""
echo "🧠 Características activas:"
echo "   • Memoria persistente: SIEMPRE ACTIVA"
echo "   • Monitor de actividad: OPCIONAL (activa en panel)"
echo "   • Pensamiento proactivo: OPCIONAL (activa en panel)"
echo ""
echo "⚡ Para modo producción usa: ./run.sh"
echo "🔄 Presiona Ctrl+C para detener"
echo "─────────────────────────────────────────────────────"
echo ""

# Iniciar servidor con configuración de desarrollo
exec python main.py