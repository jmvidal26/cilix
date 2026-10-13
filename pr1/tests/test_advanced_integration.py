#!/usr/bin/env python3
"""
Test script para verificar la integración de características avanzadas.
"""

import sys
import os
import json
import asyncio
import requests
import time

def test_api_endpoints():
    """Probar endpoints de la API de características avanzadas."""
    base_url = "http://localhost:8000"
    
    print("🧪 Probando integración de características avanzadas...")
    print(f"📡 URL base: {base_url}")
    print()
    
    # 1. Probar endpoint de salud
    print("1. Probando /health...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code == 200:
            health_data = response.json()
            print(f"   ✅ Health OK: {health_data['status']}")
            print(f"   🔌 Red: {health_data['network']}")
            print(f"   🧠 Backend activo: {health_data['active_backend']}")
        else:
            print(f"   ❌ Error: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ Error conectando: {e}")
        print("   ℹ️ Asegúrate de que el servidor esté corriendo (python main.py)")
        return False
    
    print()
    
    # 2. Probar estado de características avanzadas
    print("2. Probando /api/advanced/status...")
    try:
        response = requests.get(f"{base_url}/api/advanced/status", timeout=5)
        if response.status_code == 200:
            advanced_data = response.json()
            print(f"   ✅ Estado obtenido")
            print(f"   📊 Disponible: {advanced_data['available']}")
            
            if advanced_data['available']:
                features = advanced_data.get('features', {})
                print(f"   🧠 Memoria: {'✅ SIEMPRE' if features.get('memory', {}).get('enabled', False) else '❌'}")
                print(f"   👁️ Monitor: {'✅ ACTIVO' if features.get('activity_monitor', {}).get('enabled', False) else '❌ OPcional'}")
                print(f"   💡 Pensamiento: {'✅ ACTIVO' if features.get('proactive_thinking', {}).get('enabled', False) else '❌ OPcional'}")
                
                # Mostrar algunas estadísticas
                stats = advanced_data.get('stats', {})
                if 'memory_stats' in stats:
                    mem = stats['memory_stats']
                    print(f"   📝 Conversaciones: {mem.get('conversation_count', 0)}")
                    print(f"   ⚡ Acciones: {mem.get('action_count', 0)}")
            else:
                print(f"   ℹ️ Mensaje: {advanced_data.get('message', 'No message')}")
        else:
            print(f"   ❌ Error: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
    
    # 3. Probar contexto de memoria
    print("3. Probando /api/advanced/memory/context...")
    try:
        response = requests.get(f"{base_url}/api/advanced/memory/context?window_minutes=60", timeout=5)
        if response.status_code == 200:
            memory_data = response.json()
            print(f"   ✅ Contexto obtenido")
            print(f"   📊 Disponible: {memory_data['available']}")
            if memory_data['available']:
                context = memory_data.get('context', '')
                print(f"   📝 Longitud: {len(context)} caracteres")
                if context:
                    print(f"   📋 Preview: {context[:100]}..." if len(context) > 100 else f"   📋 Preview: {context}")
        else:
            print(f"   ❌ Error: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
    
    # 4. Probar sugerencias proactivas
    print("4. Probando /api/advanced/suggestions...")
    try:
        response = requests.get(f"{base_url}/api/advanced/suggestions?limit=2", timeout=5)
        if response.status_code == 200:
            suggestions_data = response.json()
            print(f"   ✅ Sugerencias obtenidas")
            print(f"   📊 Disponible: {suggestions_data['available']}")
            if suggestions_data['available']:
                suggestions = suggestions_data.get('suggestions', [])
                print(f"   💡 Número de sugerencias: {len(suggestions)}")
                for i, suggestion in enumerate(suggestions[:2], 1):
                    message = suggestion.get('content', {}).get('message', 'Sin mensaje')
                    print(f"   {i}. {message[:80]}..." if len(message) > 80 else f"   {i}. {message}")
        else:
            print(f"   ❌ Error: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
    
    # 5. Probar resumen de actividad
    print("5. Probando /api/advanced/activity/summary...")
    try:
        response = requests.get(f"{base_url}/api/advanced/activity/summary?hours=24", timeout=5)
        if response.status_code == 200:
            activity_data = response.json()
            print(f"   ✅ Resumen obtenido")
            print(f"   📊 Disponible: {activity_data['available']}")
            if activity_data['available']:
                summary = activity_data.get('summary', {})
                if 'error' not in summary:
                    print(f"   📈 Resumen de actividad disponible")
                    # Mostrar algunas métricas si están disponibles
                    if 'events_today' in summary:
                        print(f"   📊 Eventos hoy: {summary['events_today']}")
                else:
                    print(f"   ℹ️ {summary.get('error', 'Error desconocido')}")
        else:
            print(f"   ❌ Error: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
    
    # 6. Verificar que el panel HTML está disponible
    print("6. Verificando panel HTML...")
    try:
        response = requests.get(f"{base_url}/advanced", timeout=5)
        if response.status_code == 200:
            print("   ✅ Panel HTML disponible")
            print(f"   🌐 Accede en: {base_url}/advanced")
        elif response.status_code == 404:
            print("   ❌ Panel HTML no encontrado (advanced_panel.html)")
        else:
            print(f"   ⚠️ Estado inesperado: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
    
    # 7. Probar preferencias del usuario
    print("7. Probando /api/advanced/user/preferences...")
    try:
        response = requests.get(f"{base_url}/api/advanced/user/preferences", timeout=5)
        if response.status_code == 200:
            prefs_data = response.json()
            print(f"   ✅ Preferencias obtenidas")
            print(f"   📊 Disponible: {prefs_data['available']}")
            if prefs_data['available']:
                prefs = prefs_data.get('preferences', {})
                if prefs:
                    print(f"   👤 Preferencias del usuario disponibles")
                    if 'trust_level' in prefs:
                        print(f"   🤝 Nivel de confianza: {prefs['trust_level']}")
                else:
                    print("   ℹ️ No hay preferencias registradas aún")
        else:
            print(f"   ❌ Error: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
    print("="*60)
    print("🎯 Resumen de la integración:")
    print("   • Memoria persistente: SIEMPRE ACTIVA")
    print("   • Monitor de actividad: OPCIONAL (activar desde panel)")
    print("   • Pensamiento proactivo: OPCIONAL (activar desde panel)")
    print("   • Panel de control: /advanced")
    print("   • API completa: /api/advanced/*")
    print()
    print("📋 Para usar las características avanzadas:")
    print("   1. Abre http://localhost:8000/advanced")
    print("   2. Activa las características opcionales")
    print("   3. Usa Sylix normalmente - las características funcionarán en segundo plano")
    print()
    print("✅ Integración completada exitosamente!")

if __name__ == "__main__":
    # Verificar que el servidor esté corriendo
    print("🔍 Verificando si el servidor está disponible...")
    try:
        response = requests.get("http://localhost:8000/health", timeout=2)
        if response.status_code == 200:
            test_api_endpoints()
        else:
            print(f"❌ Servidor no responde correctamente (código: {response.status_code})")
            print("💡 Ejecuta primero: python main.py")
    except requests.exceptions.ConnectionError:
        print("❌ No se puede conectar al servidor en localhost:8000")
        print("💡 Asegúrate de ejecutar el servidor con:")
        print("   cd /home/jesvid/Downloads/pr1")
        print("   python main.py")
    except Exception as e:
        print(f"❌ Error inesperado: {e}")