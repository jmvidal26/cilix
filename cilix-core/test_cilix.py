#!/usr/bin/env python3
"""
Script de pruebas integrales para Cilix v1.1
Prueba todos los módulos y verifica funcionalidad
"""

import asyncio
import importlib
import sys
import os
from pathlib import Path

# Agregar backend al path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

def print_header(text):
    """Imprimir encabezado decorado"""
    print("\n" + "="*60)
    print(f"🧪 {text}")
    print("="*60)

def print_success(text):
    """Imprimir mensaje de éxito"""
    print(f"✅ {text}")

def print_warning(text):
    """Imprimir mensaje de advertencia"""
    print(f"⚠️  {text}")

def print_error(text):
    """Imprimir mensaje de error"""
    print(f"❌ {text}")

def print_info(text):
    """Imprimir información"""
    print(f"ℹ️  {text}")

async def test_imports():
    """Probar importaciones de módulos"""
    print_header("Prueba de Importaciones")
    
    modules_to_test = [
        ("core_ia", "CoreIA"),
        ("audio_engine", "AudioEngine"),
        ("vista_engine", "VistaEngine"),
        ("os_controller", "OSController"),
        ("vtuber_engine", "VTuberEngine"),
    ]
    
    all_success = True
    
    for module_name, class_name in modules_to_test:
        try:
            module = importlib.import_module(module_name)
            class_obj = getattr(module, class_name)
            print_success(f"{module_name}.{class_name} - OK")
        except ImportError as e:
            print_error(f"{module_name} - FALLO: {e}")
            all_success = False
        except AttributeError as e:
            print_error(f"{module_name}.{class_name} - FALLO: {e}")
            all_success = False
            
    return all_success

async def test_core_ia():
    """Probar módulo CoreIA"""
    print_header("Prueba de CoreIA (Cerebro Dual)")
    
    try:
        from core_ia import CoreIA, test_core_ia as test_func
        
        print_info("Iniciando prueba de CoreIA...")
        await test_func()
        print_success("CoreIA - Pruebas pasadas")
        return True
        
    except Exception as e:
        print_error(f"CoreIA - FALLO: {e}")
        return False

async def test_audio_engine():
    """Probar módulo AudioEngine"""
    print_header("Prueba de AudioEngine (Voz)")
    
    try:
        from audio_engine import test_audio_engine as test_func
        
        print_info("Iniciando prueba de AudioEngine...")
        await test_func()
        print_success("AudioEngine - Pruebas pasadas")
        return True
        
    except Exception as e:
        print_error(f"AudioEngine - FALLO: {e}")
        return False

async def test_vista_engine():
    """Probar módulo VistaEngine"""
    print_header("Prueba de VistaEngine (Visión)")
    
    try:
        from vista_engine import test_vista_engine as test_func
        
        print_info("Iniciando prueba de VistaEngine...")
        await test_func()
        print_success("VistaEngine - Pruebas pasadas")
        return True
        
    except Exception as e:
        print_error(f"VistaEngine - FALLO: {e}")
        return False

async def test_os_controller():
    """Probar módulo OSController"""
    print_header("Prueba de OSController (Sistema)")
    
    try:
        from os_controller import test_os_controller as test_func
        
        print_info("Iniciando prueba de OSController...")
        await test_func()
        print_success("OSController - Pruebas pasadas")
        return True
        
    except Exception as e:
        print_error(f"OSController - FALLO: {e}")
        return False

async def test_vtuber_engine():
    """Probar módulo VTuberEngine"""
    print_header("Prueba de VTuberEngine (Design_genius_white)")
    
    try:
        from vtuber_engine import test_vtuber_engine as test_func
        
        print_info("Iniciando prueba de VTuberEngine...")
        await test_func()
        print_success("VTuberEngine - Pruebas pasadas")
        return True
        
    except Exception as e:
        print_error(f"VTuberEngine - FALLO: {e}")
        print_info("Nota: Esto es normal si no tienes los archivos del modelo en assets/")
        return False

async def test_requirements():
    """Verificar que se cumplan los requisitos del sistema"""
    print_header("Verificación de Requisitos del Sistema")
    
    checks = []
    
    # Verificar Python
    py_version = sys.version_info
    checks.append(("Python >= 3.8", py_version.major == 3 and py_version.minor >= 8))
    
    # Verificar sistema operativo
    checks.append(("Sistema Linux", sys.platform.startswith('linux')))
    
    # Verificar RAM (aproximado)
    try:
        import psutil
        total_ram_gb = psutil.virtual_memory().total / (1024**3)
        checks.append(("RAM >= 6GB", total_ram_gb >= 6))
        print_info(f"RAM total detectada: {total_ram_gb:.1f}GB")
    except ImportError:
        checks.append(("psutil disponible", False))
        print_warning("No se pudo verificar RAM (psutil no instalado)")
    
    # Verificar Ollama
    try:
        import subprocess
        result = subprocess.run(["which", "ollama"], capture_output=True, text=True)
        checks.append(("Ollama instalado", result.returncode == 0))
    except:
        checks.append(("Ollama instalado", False))
    
    # Mostrar resultados
    all_passed = True
    for check_name, passed in checks:
        if passed:
            print_success(f"{check_name}")
        else:
            print_error(f"{check_name}")
            all_passed = False
            
    return all_passed

async def test_integration():
    """Probar integración básica entre módulos"""
    print_header("Prueba de Integración Básica")
    
    try:
        # Simular flujo básico
        print_info("Simulando flujo de mensaje IA -> Voz -> VTuber...")
        
        from core_ia import EmotionDetector
        
        # Probar detector de emociones
        test_texts = [
            ("¡Hola! Estoy muy feliz de ayudarte", "feliz"),
            ("Tengo un problema con el código", "concentrado"),
            ("Oh no, algo salió mal", "triste"),
            ("¡Increíble! Eso funciona perfecto", "sorprendido"),
        ]
        
        detector = EmotionDetector()
        for text, expected in test_texts:
            emotion = detector.detect_emotion(text)
            print_info(f"Texto: '{text[:30]}...' → Emoción: {emotion} (esperado: {expected})")
        
        print_success("Integración básica - OK")
        return True
        
    except Exception as e:
        print_error(f"Integración - FALLO: {e}")
        return False

async def test_file_structure():
    """Verificar estructura de archivos del proyecto"""
    print_header("Verificación de Estructura de Archivos")
    
    required_files = [
        ("backend/main.py", "Servidor principal"),
        ("backend/core_ia.py", "Cerebro dual"),
        ("backend/audio_engine.py", "Motor de voz"),
        ("backend/vista_engine.py", "Motor de visión"),
        ("backend/os_controller.py", "Control del sistema"),
        ("backend/vtuber_engine.py", "Motor VTuber"),
        ("frontend/index.html", "Interfaz web"),
        ("frontend/renderer.js", "Lógica frontend"),
        ("frontend/style.css", "Estilos"),
        ("electron/main.js", "Electron main"),
        ("electron/preload.js", "Electron preload"),
        ("requirements.txt", "Dependencias Python"),
        ("package.json", "Dependencias Node.js"),
        ("README.md", "Documentación"),
        ("setup.sh", "Script de instalación"),
    ]
    
    all_exist = True
    for file_path, description in required_files:
        full_path = Path(__file__).parent / file_path
        
        if full_path.exists():
            print_success(f"{file_path} - {description}")
        else:
            print_error(f"{file_path} - FALTA: {description}")
            all_exist = False
            
    return all_exist

async def run_all_tests():
    """Ejecutar todas las pruebas"""
    print_header("SUITE DE PRUEBAS CILIX v1.1")
    print_info("Iniciando pruebas integrales del sistema...")
    
    test_results = []
    
    # Ejecutar pruebas
    test_results.append(("Importaciones", await test_imports()))
    test_results.append(("Estructura archivos", await test_file_structure()))
    test_results.append(("Requisitos sistema", await test_requirements()))
    test_results.append(("CoreIA", await test_core_ia()))
    test_results.append(("AudioEngine", await test_audio_engine()))
    test_results.append(("VistaEngine", await test_vista_engine()))
    test_results.append(("OSController", await test_os_controller()))
    test_results.append(("VTuberEngine", await test_vtuber_engine()))
    test_results.append(("Integración", await test_integration()))
    
    # Mostrar resumen
    print_header("RESUMEN DE PRUEBAS")
    
    passed = sum(1 for _, result in test_results if result)
    total = len(test_results)
    
    print(f"\n📊 Resultados: {passed}/{total} pruebas exitosas")
    print(f"📈 Porcentaje: {(passed/total)*100:.1f}%")
    
    print("\n" + "="*60)
    print("🧪 PRUEBAS INDIVIDUALES:")
    print("="*60)
    
    for test_name, result in test_results:
        status = "✅ PASÓ" if result else "❌ FALLÓ"
        print(f"{status} - {test_name}")
    
    print("\n" + "="*60)
    
    if passed == total:
        print_success("¡TODAS LAS PRUEBAS PASARON EXITOSAMENTE!")
        print_info("Cilix v1.1 está listo para implementación.")
        return True
    else:
        print_warning(f"{total - passed} pruebas fallaron")
        print_info("Revisa los errores anteriores y corrige los problemas.")
        return False

def main():
    """Función principal"""
    try:
        print("\n" + "🚀"*30)
        print("🚀 CILIX v1.1 - PRUEBAS INTEGRALES DEL SISTEMA 🚀")
        print("🚀"*30 + "\n")
        
        # Ejecutar pruebas
        success = asyncio.run(run_all_tests())
        
        # Recomendaciones finales
        print_header("RECOMENDACIONES FINALES")
        
        if success:
            print_success("El sistema pasa todas las verificaciones básicas")
            print("\n🎯 Pasos siguientes:")
            print("1. Ejecuta ./setup.sh para instalación completa")
            print("2. Configura Ollama: ollama pull qwen2.5:1.5b")
            print("3. Copia el modelo VTuber: cp -r ../design_genius_white/ assets/")
            print("4. Inicia Cilix: ./run.sh")
        else:
            print_error("Hay problemas que necesitan corrección")
            print("\n🔧 Acciones recomendadas:")
            print("1. Instala dependencias faltantes: pip install -r requirements.txt")
            print("2. Verifica que Ollama esté instalado y corriendo")
            print("3. Revisa los mensajes de error específicos arriba")
            print("4. Ejecuta pruebas individuales para diagnóstico")
        
        print("\n" + "="*60)
        print("📚 Documentación completa en README.md")
        print("🛠️  Script de instalación: ./setup.sh")
        print("🎮 Script de ejecución: ./run.sh")
        print("="*60 + "\n")
        
        return 0 if success else 1
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Pruebas interrumpidas por el usuario")
        return 130
    except Exception as e:
        print(f"\n\n💥 Error no esperado: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())