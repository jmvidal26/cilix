#!/usr/bin/env python3
"""
Verificar dependencias para características avanzadas.
"""

import importlib
import sys

def check_module(module_name, pip_name=None):
    """Verificar si un módulo está disponible."""
    try:
        importlib.import_module(module_name)
        print(f"✅ {module_name}")
        return True
    except ImportError:
        pip_name = pip_name or module_name
        print(f"❌ {module_name} (pip install {pip_name})")
        return False

print("🔍 Verificando dependencias para características avanzadas...")
print()

# Módulos principales
modules_to_check = [
    ("sqlite3", None),  # Viene con Python
    ("threading", None),  # Viene con Python
    ("datetime", None),  # Viene con Python
    ("logging", None),  # Viene con Python
    ("heapq", None),  # Viene con Python
    ("collections", None),  # Viene con Python
]

print("📦 Módulos de Python estándar:")
all_ok = True
for module_name, pip_name in modules_to_check:
    if not check_module(module_name, pip_name):
        all_ok = False

print()

# Verificar módulos específicos de características avanzadas
print("🧠 Módulos de características avanzadas:")
advanced_modules = [
    ("memory", "memory.py"),
    ("activity_monitor", "activity_monitor.py"),
    ("proactive_thinking", "proactive_thinking.py"),
    ("advanced_features", "advanced_features.py"),
]

for module_name, file_name in advanced_modules:
    try:
        # Intentar importar desde el directorio actual
        import importlib.util
        spec = importlib.util.spec_from_file_location(module_name, file_name)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            print(f"✅ {module_name} ({file_name})")
        else:
            print(f"❌ {module_name} - Archivo {file_name} no encontrado")
            all_ok = False
    except Exception as e:
        print(f"❌ {module_name} - Error: {e}")
        all_ok = False

print()

# Verificar configuración
print("⚙️ Verificando configuración:")
config_files = [
    ("advanced_config.json", "Configuración avanzada"),
]

for file_name, description in config_files:
    import os
    if os.path.exists(file_name):
        print(f"✅ {description} ({file_name})")
    else:
        print(f"⚠️  {description} - Archivo {file_name} no encontrado")
        # Esto no es crítico, el sistema usará valores por defecto

print()

if all_ok:
    print("✅ Todas las dependencias están satisfechas!")
    print("📋 Las características avanzadas están listas para usar.")
else:
    print("⚠️  Algunas dependencias faltan o tienen errores.")
    print("💡 Asegúrate de que todos los archivos .py estén en el directorio actual.")

print()
print("📚 Resumen de características implementadas:")
print("   1. 🧠 Memoria persistente (siempre activa)")
print("   2. 👁️ Monitor de actividad (opcional)")
print("   3. 💡 Pensamiento proactivo (opcional)")
print("   4. 🔗 Sistema de integración completo")
print()
print("🌐 Para acceder al panel de control:")
print("   - Panel principal: http://localhost:8000")
print("   - Panel avanzado: http://localhost:8000/advanced")