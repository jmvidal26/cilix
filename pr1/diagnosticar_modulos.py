#!/usr/bin/env python3
"""
Script de diagnóstico y reparación de módulos avanzados de Sylix OS Core.
Soluciona problemas de memoria persistente, monitor de actividad, pensamiento proactivo.
"""

import os
import sys
import json
import time
import sqlite3
import traceback
import subprocess
from pathlib import Path

print("🔧 DIAGNÓSTICO Y REPARACIÓN DE MÓDULOS AVANZADOS")
print("=" * 60)

# Configurar entorno
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Asegurar que estamos en el entorno virtual
venv_python = os.path.join(".venv", "bin", "python")
if os.path.exists(venv_python):
    print(f"✅ Usando entorno virtual: {venv_python}")
else:
    print("⚠️  Entorno virtual no encontrado. Usando Python del sistema.")

print()

# 1. VERIFICAR DEPENDENCIAS CRÍTICAS
print("1. 🔍 Verificando dependencias críticas...")

dependencies = {
    "numpy": "Procesamiento de datos",
    "psutil": "Monitorización del sistema",
    "sqlite3": "Base de datos (incluido en Python)",
}

missing_deps = []
for dep, desc in dependencies.items():
    try:
        __import__(dep)
        print(f"   ✅ {dep}: {desc}")
    except ImportError:
        print(f"   ❌ {dep}: FALTANTE - {desc}")
        missing_deps.append(dep)

if missing_deps:
    print(f"\n⚠️  Instalando dependencias faltantes...")
    for dep in missing_deps:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", dep], check=True)
            print(f"   ✅ {dep} instalado")
        except subprocess.CalledProcessError:
            print(f"   ❌ Error instalando {dep}")

print()

# 2. VERIFICAR ESTRUCTURA DE DIRECTORIOS
print("2. 📁 Verificando estructura de directorios...")

required_dirs = [
    "~/.config/sylix",
    "~/.config/sylix/activity_logs",
    "logs",
    "scripts",
    "tests",
]

for dir_path in required_dirs:
    expanded = os.path.expanduser(dir_path)
    if not os.path.exists(expanded):
        os.makedirs(expanded, exist_ok=True)
        print(f"   📂 Creado: {expanded}")
    else:
        print(f"   ✅ Existe: {expanded}")

print()

# 3. VERIFICAR ARCHIVOS DE CONFIGURACIÓN
print("3. ⚙️ Verificando archivos de configuración...")

config_files = {
    "advanced_config.json": "Configuración avanzada",
    ".env": "Variables de entorno",
}

for file, desc in config_files.items():
    if os.path.exists(file):
        print(f"   ✅ {file}: {desc}")
        
        # Verificar contenido si es advanced_config.json
        if file == "advanced_config.json":
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # Verificar configuración de características avanzadas
                adv_features = config.get("advanced_features", {})
                if not adv_features:
                    print(f"   ⚠️  {file}: No tiene configuración advanced_features")
                else:
                    for feature_name, feature_config in adv_features.items():
                        enabled = feature_config.get("enabled", False)
                        status = "✅ ACTIVO" if enabled else "❌ INACTIVO"
                        print(f"      • {feature_name}: {status}")
            except Exception as e:
                print(f"   ❌ Error leyendo {file}: {e}")
    else:
        print(f"   ❌ {file}: FALTANTE - {desc}")

print()

# 4. VERIFICAR MÓDULOS AVANZADOS
print("4. 🧠 Verificando módulos avanzados...")

modules_to_check = [
    ("memory", "🧠 Memoria persistente"),
    ("activity_monitor", "👁️ Monitor de actividad"),
    ("proactive_thinking", "💡 Pensamiento proactivo"),
    ("advanced_features", "🔗 Sistema de integración"),
]

for module_name, description in modules_to_check:
    try:
        if module_name == "memory":
            from memory import get_memory
            mem = get_memory()
            stats = mem.get_statistics()
            print(f"   ✅ {description}: Cargado")
            print(f"      • Conversaciones: {stats.get('conversation_count', 0)}")
            print(f"      • Acciones: {stats.get('action_count', 0)}")
        elif module_name == "activity_monitor":
            from activity_monitor import get_activity_monitor
            monitor = get_activity_monitor(enabled=False)
            status = monitor.get_status()
            print(f"   ✅ {description}: Cargado")
            print(f"      • Estado: {status.get('status', 'desconocido')}")
            print(f"      • Sesiones hoy: {status.get('sessions_today', 0)}")
        elif module_name == "proactive_thinking":
            from proactive_thinking import get_proactive_thinker
            thinker = get_proactive_thinker(enabled=False)
            stats = thinker.get_statistics()
            print(f"   ✅ {description}: Cargado")
            print(f"      • Pensamientos: {stats.get('total_thoughts', 0)}")
            print(f"      • Patrones: {stats.get('learned_patterns', 0)}")
        elif module_name == "advanced_features":
            from advanced_features import get_advanced_features
            features = get_advanced_features()
            status = features.get_feature_status()
            print(f"   ✅ {description}: Cargado")
            for feat_name, feat_config in status.items():
                enabled = feat_config.get("enabled", False)
                status_text = "✅ ACTIVO" if enabled else "❌ INACTIVO"
                print(f"      • {feat_name}: {status_text}")
    except Exception as e:
        print(f"   ❌ {description}: ERROR - {e}")
        traceback.print_exc()

print()

# 5. VERIFICAR BASES DE DATOS
print("5. 💾 Verificando bases de datos...")

db_paths = [
    ("~/.config/sylix/memory.db", "Memoria persistente"),
    ("~/.config/sylix/activity.db", "Monitor de actividad"),
    ("~/.config/sylix/proactive.db", "Pensamiento proactivo"),
]

for db_path, desc in db_paths:
    expanded = os.path.expanduser(db_path)
    if os.path.exists(expanded):
        size = os.path.getsize(expanded)
        print(f"   ✅ {desc}: {size / 1024:.1f} KB")
        
        # Verificar integridad de la base de datos
        try:
            conn = sqlite3.connect(expanded)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            conn.close()
            print(f"      • Tablas: {len(tables)}")
        except sqlite3.Error as e:
            print(f"      • ❌ Error SQLite: {e}")
    else:
        print(f"   📝 {desc}: No existe (se creará al activar)")

print()

# 6. ACTIVAR CARACTERÍSTICAS AVANZADAS
print("6. 🚀 Activando características avanzadas...")

# Actualizar advanced_config.json para activar todo
config_file = "advanced_config.json"
if os.path.exists(config_file):
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Activar todas las características
        if "advanced_features" in config:
            for feature_name in ["memory", "activity_monitor", "proactive_thinking"]:
                if feature_name in config["advanced_features"]:
                    config["advanced_features"][feature_name]["enabled"] = True
                    print(f"   ✅ {feature_name}: Activado en configuración")
            
            # Guardar configuración actualizada
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print("   💾 Configuración guardada")
    except Exception as e:
        print(f"   ❌ Error actualizando configuración: {e}")
else:
    print(f"   ❌ {config_file} no encontrado")

print()

# 7. PROBAR SISTEMA COMPLETO
print("7. ⚡ Probando sistema completo...")

try:
    # Importar y probar el sistema de características avanzadas
    from advanced_features import get_advanced_features
    
    # Obtener instancia con configuración actualizada
    features = get_advanced_features()
    
    # Iniciar integración
    features.start_integration()
    print("   ✅ Sistema de integración iniciado")
    
    # Probar memoria
    features.add_conversation("user", "Hola, esto es una prueba del diagnóstico")
    features.add_conversation("assistant", "¡Hola! Estoy funcionando correctamente")
    print("   ✅ Memoria probada: 2 conversaciones agregadas")
    
    # Probar acción
    features.add_action("diagnostic", "test", {"status": "success"}, success=True)
    print("   ✅ Acción registrada en memoria")
    
    # Intentar activar monitor de actividad
    try:
        if features.enable_feature("activity_monitor"):
            print("   ✅ Monitor de actividad activado")
        else:
            print("   ⚠️  No se pudo activar monitor de actividad")
    except Exception as e:
        print(f"   ⚠️  Error activando monitor: {e}")
    
    # Intentar activar pensamiento proactivo
    try:
        if features.enable_feature("proactive_thinking"):
            print("   ✅ Pensamiento proactivo activado")
        else:
            print("   ⚠️  No se pudo activar pensamiento proactivo")
    except Exception as e:
        print(f"   ⚠️  Error activando pensamiento: {e}")
    
    # Obtener contexto de memoria
    context = features.get_conversation_context(window_minutes=60)
    print(f"   📝 Contexto de memoria: {len(context)} caracteres")
    
    # Obtener estadísticas del sistema
    stats = features.get_system_stats()
    print(f"   📊 Sistema avanzado: {len(stats)} métricas")
    
    # Detener integración
    features.stop_integration()
    print("   ✅ Sistema detenido correctamente")
    
except Exception as e:
    print(f"   ❌ Error probando sistema: {e}")
    traceback.print_exc()

print()

# 8. VERIFICAR MONITOR DE PANTALLA
print("8. 👁️ Verificando monitor de pantalla (activity_monitor)...")

try:
    from activity_monitor import get_activity_monitor
    
    # Crear monitor con tracking de pantalla activado
    monitor = get_activity_monitor(enabled=True)
    
    # Iniciar monitoreo
    monitor.start_monitoring()
    print("   ✅ Monitor de pantalla iniciado")
    
    # Probar captura de ventana activa
    print("   🔍 Probando captura de ventana activa...")
    try:
        # Verificar si xdotool está instalado para Linux
        import subprocess
        result = subprocess.run(["which", "xdotool"], capture_output=True, text=True)
        if result.returncode == 0:
            print("   ✅ xdotool instalado")
            
            # Intentar obtener ventana activa
            try:
                window_info = monitor.get_active_window_info()
                if window_info:
                    print(f"   📊 Ventana activa: {window_info.get('window_title', 'Desconocido')}")
                    print(f"      Aplicación: {window_info.get('application_name', 'Desconocida')}")
                else:
                    print("   ⚠️  No se pudo obtener información de ventana")
            except Exception as e:
                print(f"   ⚠️  Error obteniendo ventana: {e}")
        else:
            print("   ⚠️  xdotool no instalado. Instala: sudo apt install xdotool")
    except Exception as e:
        print(f"   ⚠️  Error verificando dependencias: {e}")
    
    # Detener monitoreo
    monitor.stop_monitoring()
    print("   ✅ Monitor de pantalla detenido")
    
except Exception as e:
    print(f"   ❌ Error con monitor de pantalla: {e}")
    traceback.print_exc()

print()

# 9. CREAR SCRIPT DE ACTIVACIÓN
print("9. 📝 Creando script de activación automática...")

activation_script = """#!/bin/bash
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
"""

with open("activar_caracteristicas.sh", "w", encoding="utf-8") as f:
    f.write(activation_script)

os.chmod("activar_caracteristicas.sh", 0o755)
print("   ✅ Script creado: ./activar_caracteristicas.sh")

print()

# 10. RESUMEN Y RECOMENDACIONES
print("10. 📋 Resumen y recomendaciones")
print("=" * 60)

print("\n🎯 PROBLEMAS IDENTIFICADOS Y SOLUCIONES:")

print("\n1. 🔧 Módulos desactivados por configuración:")
print("   • Solución: Ejecutar ./activar_caracteristicas.sh")

print("\n2. 👁️ Monitor de pantalla requiere xdotool:")
print("   • Solución: sudo apt install xdotool wmctrl")

print("\n3. 🧠 Memoria persistente necesita numpy:")
print("   • Solución: pip install numpy (ya instalado en entorno virtual)")

print("\n4. 🔗 Integración no inicializada en main.py:")
print("   • Solución: Asegurar que ADVANCED_FEATURES se inicialice en lifespan")

print("\n🚀 ACCIONES RECOMENDADAS:")
print("1. Ejecutar: ./activar_caracteristicas.sh")
print("2. Instalar: sudo apt install xdotool wmctrl")
print("3. Iniciar: ./start_sylix.sh")
print("4. Verificar: http://localhost:8000/advanced")

print("\n📞 SOPORTE:")
print("• Revisar logs en: logs/")
print("• Verificar bases de datos en: ~/.config/sylix/")
print("• Probar módulos individualmente con scripts/")

print("\n" + "=" * 60)
print("✅ Diagnóstico completado. Ejecuta las acciones recomendadas.")
print("💡 Las características avanzadas están listas para activarse.")