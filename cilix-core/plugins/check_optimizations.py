#!/usr/bin/env python3
"""
Script para verificar optimizaciones del modo local (Ollama/Offline).
"""

import os
import sys
import asyncio
import json
import platform
import multiprocessing

def check_system_resources():
    """Verifica recursos del sistema para optimizaciones."""
    print("🔍 Verificando recursos del sistema...")
    print("=" * 60)
    
    # CPU
    cpu_count = multiprocessing.cpu_count()
    print(f"🧠 CPUs: {cpu_count} núcleos")
    
    # Memoria
    try:
        import psutil
        mem = psutil.virtual_memory()
        print(f"💾 RAM: {mem.total / (1024**3):.1f} GB total")
        print(f"     Disponible: {mem.available / (1024**3):.1f} GB ({mem.percent}% usado)")
        
        # Swap
        swap = psutil.swap_memory()
        if swap.total > 0:
            print(f"💿 Swap: {swap.total / (1024**3):.1f} GB ({swap.percent}% usado)")
    except ImportError:
        print("⚠️  psutil no instalado (pip install psutil)")
    
    # Sistema operativo
    print(f"💻 OS: {platform.system()} {platform.release()}")
    print(f"🐍 Python: {platform.python_version()}")
    print()

def check_ollama_optimizations():
    """Verifica configuraciones optimizadas para Ollama."""
    print("🤖 Verificando optimizaciones Ollama...")
    print("=" * 60)
    
    # Leer configuración
    config_path = "advanced_config.json"
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        perf_config = config.get("performance", {}).get("local_mode_optimization", {})
        
        if perf_config.get("enabled", False):
            print("✅ Optimizaciones locales activadas")
            print(f"   • Hilos Ollama: {perf_config.get('ollama_threads', 'auto')}")
            print(f"   • Tiempo keep-alive: {perf_config.get('keep_alive_minutes', 15)} min")
            print(f"   • Cache de respuestas: {'✅' if perf_config.get('response_cache', True) else '❌'}")
            print(f"   • Timeout tool calls: {perf_config.get('tool_call_timeout', 10)}s")
        else:
            print("⚠️  Optimizaciones locales desactivadas")
    else:
        print("❌ Configuración avanzada no encontrada")
    
    # Verificar modelos Ollama recomendados
    print()
    print("📦 Modelos recomendados para modo local:")
    print("   • qwen2.5:1.5b (~900 MB) - Buen balance velocidad/calidad")
    print("   • llama3.2:3b (~1.8 GB) - Alta calidad con tool calling")
    print("   • gemma2:2b (~1.6 GB) - Excelente para tareas complejas")
    print("   • mistral:7b (~4.1 GB) - Muy potente (requiere más RAM)")
    print()

def check_tts_optimizations():
    """Verifica optimizaciones de TTS."""
    print("🔊 Verificando optimizaciones TTS...")
    print("=" * 60)
    
    # Verificar backends disponibles
    tts_backends = []
    
    # Edge-TTS
    try:
        import edge_tts
        tts_backends.append("✅ Edge-TTS (online)")
    except ImportError:
        tts_backends.append("❌ Edge-TTS no instalado")
    
    # Piper
    piper_path = os.path.join("models", "piper", "es_ES-sharvard-medium.onnx")
    if os.path.exists(piper_path):
        tts_backends.append(f"✅ Piper TTS ({os.path.getsize(piper_path) / (1024**2):.1f} MB)")
    else:
        tts_backends.append("❌ Piper TTS no encontrado")
    
    # Kokoro
    kokoro_path = os.path.join("models", "kokoro", "kokoro-v1.0.onnx")
    if os.path.exists(kokoro_path):
        tts_backends.append(f"✅ Kokoro TTS ({os.path.getsize(kokoro_path) / (1024**2):.1f} MB)")
    else:
        tts_backends.append("❌ Kokoro TTS no encontrado")
    
    # pyttsx3
    try:
        import pyttsx3
        tts_backends.append("✅ pyttsx3 (fallback)")
    except ImportError:
        tts_backends.append("❌ pyttsx3 no instalado")
    
    for backend in tts_backends:
        print(f"   {backend}")
    
    print()
    print("🎯 Optimizaciones TTS implementadas:")
    print("   • Procesamiento por fragmentos para latencia reducida")
    print("   • Generación por oraciones en Piper")
    print("   • Reproducción asíncrona con subprocess")
    print()

def check_ai_backend_optimizations():
    """Verifica optimizaciones en los backends de IA."""
    print("🧠 Verificando optimizaciones IA...")
    print("=" * 60)
    
    # Verificar importaciones
    imports_ok = []
    
    try:
        import httpx
        imports_ok.append("✅ httpx (HTTP client persistente)")
    except ImportError:
        imports_ok.append("❌ httpx no instalado")
    
    try:
        import numpy
        imports_ok.append("✅ numpy (procesamiento TTS)")
    except ImportError:
        imports_ok.append("❌ numpy no instalado")
    
    for imp in imports_ok:
        print(f"   {imp}")
    
    print()
    print("⚡ Optimizaciones implementadas:")
    print("   • HTTP client persistente con connection pool")
    print("   • Keep-Alive de 15 minutos para modelos Ollama")
    print("   • Tool calling nativo para modelos compatibles")
    print("   • Slim Tools para reducir tokens de entrada")
    print("   • Fallback automático entre backends")
    print()

async def test_ollama_connection():
    """Prueba la conexión a Ollama."""
    print("🌐 Probando conexión Ollama...")
    print("=" * 60)
    
    try:
        import httpx
        import asyncio
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get("http://localhost:11434/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    if models:
                        print("✅ Ollama está corriendo")
                        print(f"📦 Modelos disponibles:")
                        for model in models[:5]:  # Mostrar primeros 5
                            print(f"   • {model.get('name', 'unknown')}")
                        if len(models) > 5:
                            print(f"   ... y {len(models) - 5} más")
                        
                        # Verificar modelos con tool calling
                        tool_calling_models = []
                        for model in models:
                            name = model.get('name', '').lower()
                            if any(keyword in name for keyword in ['qwen2.5', 'llama3', 'gemma3', 'mistral']):
                                tool_calling_models.append(name)
                        
                        if tool_calling_models:
                            print(f"🔧 Modelos con tool calling: {', '.join(tool_calling_models[:3])}")
                        else:
                            print("⚠️  No se encontraron modelos con tool calling nativo")
                    else:
                        print("⚠️  Ollama corriendo pero sin modelos instalados")
                        print("💡 Ejecuta: ollama pull qwen2.5:1.5b")
                else:
                    print(f"❌ Ollama responde con error: {response.status_code}")
            except (httpx.ConnectError, asyncio.TimeoutError):
                print("❌ Ollama no está corriendo en localhost:11434")
                print("💡 Instala Ollama: curl -fsSL https://ollama.com/install.sh | sh")
                print("💡 Luego inicia: ollama serve")
    except ImportError:
        print("❌ httpx no instalado")
    
    print()

def main():
    """Función principal."""
    print("🚀 Verificador de Optimizaciones - Sylix OS Core")
    print("=" * 60)
    print()
    
    check_system_resources()
    check_ollama_optimizations()
    check_tts_optimizations()
    check_ai_backend_optimizations()
    
    # Prueba asíncrona de Ollama
    try:
        asyncio.run(test_ollama_connection())
    except Exception as e:
        print(f"❌ Error probando Ollama: {e}")
    
    print("=" * 60)
    print("🎯 Resumen de Recomendaciones:")
    print()
    
    cpu_count = multiprocessing.cpu_count()
    if cpu_count >= 4:
        print("✅ Sistema adecuado para modo local (4+ núcleos)")
    else:
        print("⚠️  Sistema con recursos limitados. Considera modelos más ligeros.")
    
    print("💡 Para mejor rendimiento en modo local:")
    print("   1. Usa modelos con tool calling nativo (qwen2.5, llama3.2)")
    print("   2. Mantén Ollama corriendo en segundo plano")
    print("   3. Activa características avanzadas gradualmente")
    print("   4. Usa TTS offline (Piper) para latencia consistente")
    print()
    print("🔧 Comandos útiles:")
    print("   • ollama pull qwen2.5:1.5b      # Instalar modelo ligero")
    print("   • ollama list                   # Ver modelos instalados")
    print("   • ./start_sylix.sh             # Inicio optimizado")
    print("   • python scripts/check_optimizations.py  # Este script")
    print()

if __name__ == "__main__":
    main()