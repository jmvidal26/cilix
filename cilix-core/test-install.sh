#!/bin/bash

# Script de prueba para instalación de Cilix
# Prueba solo las dependencias críticas

set -e

echo "=== PRUEBA DE INSTALACIÓN CILIX ==="
echo ""

# 1. Verificar Python
echo "1. Verificando Python..."
python3 --version
python3 -c "import sys; print(f'Python {sys.version_info.major}.{sys.version_info.minor} OK')"

# 2. Crear entorno virtual
echo ""
echo "2. Creando entorno virtual..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "✅ Entorno virtual creado"
else
    echo "✅ Entorno virtual ya existe"
fi

# 3. Activar entorno virtual
source .venv/bin/activate
echo "✅ Entorno virtual activado"

# 4. Instalar dependencias básicas (sin torch pesado)
echo ""
echo "3. Instalando dependencias básicas..."
pip install --upgrade pip

# Dependencias ligeras para prueba
pip install fastapi==0.115.0
pip install uvicorn==0.31.0
pip install websockets==13.1
pip install httpx==0.27.0
pip install pydantic==2.8.0
pip install simpleaudio==1.0.4
pip install sounddevice==0.5.2
pip install soundfile==0.12.1

# 5. Verificar instalación
echo ""
echo "4. Verificando instalación..."
python3 -c "
import fastapi
import uvicorn
import websockets
import httpx
import pydantic
import simpleaudio
import sounddevice
import soundfile

print('✅ Todas las dependencias básicas funcionan')
print(f'FastAPI: {fastapi.__version__}')
print(f'SimpleAudio: 1.0.4')  # Versión instalada
print(f'SoundDevice: {sounddevice.__version__}')
"

# 6. Probar audio
echo ""
echo "5. Probando módulos de audio..."
python3 -c "
try:
    import sounddevice as sd
    devices = sd.query_devices()
    print(f'✅ Dispositivos de audio encontrados: {len(devices)}')
except Exception as e:
    print(f'⚠️  Advertencia audio: {e}')
"

# 7. Verificar estructura
echo ""
echo "6. Verificando estructura del proyecto..."
if [ -f "backend/main.py" ] && [ -f "frontend/index.html" ] && [ -f "electron/main.js" ]; then
    echo "✅ Estructura de archivos OK"
else
    echo "⚠️  Faltan algunos archivos"
fi

echo ""
echo "=== PRUEBA COMPLETADA ==="
echo ""
echo "🎯 Pasos siguientes:"
echo "  1. Para instalación completa: ./cilix-launcher.sh --setup"
echo "  2. Para modo interactivo: ./cilix-launcher.sh"
echo "  3. Para solo dependencias: ./cilix-launcher.sh --install"