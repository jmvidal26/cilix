#!/usr/bin/env python3
"""
pop_os_command_runner.py — Modelo / Template para ejecución de comandos en Pop!_OS.

Este archivo ("tf" / template file) sirve como modelo de referencia para:
1. Crear carpetas de forma segura en Pop!_OS (~/Desktop, ~/Documentos, ~/ruta_personalizada).
2. Ejecutar comandos Bash estándar con captura de stdout/stderr.
3. Ejecutar comandos que requieren privilegios de superusuario (sudo):
   - Modo 1: 'sudo -n' (para comandos configurados sin contraseña en sudoers).
   - Modo 2: 'pkexec' (abre la ventana gráfica nativa de autenticación de Pop!_OS).
   - Modo 3: 'terminal' (abre cosmic-term o x-terminal-emulator para ingresar contraseña interactivamente).
"""

import os
import sys
import shutil
import subprocess
import asyncio
from typing import Dict, Any, Optional

USER_HOME = os.path.expanduser("~")

def expand_user_path(path: str) -> str:
    """Expande ~ y rutas relativas al directorio HOME del usuario."""
    path = os.path.expanduser(path.strip())
    if not os.path.isabs(path):
        path = os.path.join(USER_HOME, path)
    return os.path.abspath(path)

# ─────────────────────────────────────────────────────────────────────────────
# 1. CREACIÓN DE CARPETAS EN POP!_OS
# ─────────────────────────────────────────────────────────────────────────────
def create_folder(folder_path: str) -> Dict[str, Any]:
    """
    Crea una carpeta en el sistema operativo Pop!_OS con permisos del usuario.
    
    Ejemplos:
      create_folder("~/Escritorio/NuevaCarpeta")
      create_folder("/home/jesvid/proyectos/mi_app")
    """
    abs_path = expand_user_path(folder_path)
    try:
        os.makedirs(abs_path, exist_ok=True)
        return {
            "status": "success",
            "path": abs_path,
            "message": f"Carpeta creada exitosamente en: {abs_path}"
        }
    except PermissionError:
        return {
            "status": "permission_denied",
            "path": abs_path,
            "message": f"Permiso denegado al crear {abs_path}. Se requieren privilegios de superusuario."
        }
    except Exception as e:
        return {
            "status": "error",
            "path": abs_path,
            "error": str(e)
        }

# ─────────────────────────────────────────────────────────────────────────────
# 2. EJECUCIÓN DE COMANDOS BASH ESTÁNDAR
# ─────────────────────────────────────────────────────────────────────────────
async def run_bash_command(command: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Ejecuta un comando bash asíncrono y devuelve stdout, stderr y código de salida.
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=USER_HOME
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        stdout = stdout_b.decode("utf-8", errors="replace").strip()
        stderr = stderr_b.decode("utf-8", errors="replace").strip()
        
        return {
            "status": "success" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "command": command
        }
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "error": f"El comando superó el límite de {timeout} segundos.",
            "command": command
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "command": command
        }

# ─────────────────────────────────────────────────────────────────────────────
# 3. EJECUCIÓN CON SUDO EN POP!_OS
# ─────────────────────────────────────────────────────────────────────────────
def run_sudo_command(command: str, method: str = "pkexec") -> Dict[str, Any]:
    """
    Ejecuta un comando que requiere permisos de superusuario en Pop!_OS.
    
    Métodos disponibles:
    - 'pkexec': Abre el popup gráfico de Pop!_OS pidiendo contraseña al usuario.
    - 'terminal': Abre una terminal emergente (cosmic-term / x-terminal-emulator) con sudo.
    - 'non_interactive': Ejecuta 'sudo -n' (solo funciona si no requiere contraseña en sudoers).
    """
    # Limpiar sudo inicial si ya viene incluido en el string
    cmd_clean = command.strip()
    if cmd_clean.startswith("sudo "):
        cmd_clean = cmd_clean[5:].strip()

    if method == "non_interactive":
        cmd = f"sudo -n {cmd_clean}"
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            return {
                "status": "success" if res.returncode == 0 else "error",
                "returncode": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip()
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    elif method == "pkexec":
        # Usar la interfaz gráfica de autenticación de Pop!_OS (PolicyKit)
        pkexec_bin = shutil.which("pkexec")
        if not pkexec_bin:
            return {"status": "error", "error": "pkexec no está disponible en el sistema"}

        # Envolver en bash -c para comandos complejos con pipes
        full_cmd = ["pkexec", "bash", "-c", cmd_clean]
        try:
            res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=60)
            return {
                "status": "success" if res.returncode == 0 else "error",
                "returncode": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "method": "pkexec"
            }
        except subprocess.TimeoutError:
            return {"status": "timeout", "error": "Autenticación gráfica cancelada o tiempo agotado"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    elif method == "terminal":
        # Detectar la terminal nativa de Pop!_OS
        term_bin = shutil.which("cosmic-term") or shutil.which("x-terminal-emulator") or shutil.which("gnome-terminal")
        if not term_bin:
            return {"status": "error", "error": "No se encontró emulador de terminal"}

        # Script temporal que ejecuta el comando y pide pulsar enter antes de cerrar
        wrapped_script = f"sudo {cmd_clean}; echo ''; read -p 'Presione ENTER para cerrar la terminal...' dummy"
        try:
            if "cosmic-term" in term_bin:
                proc = subprocess.Popen([term_bin, "--", "bash", "-c", wrapped_script])
            else:
                proc = subprocess.Popen([term_bin, "-e", f"bash -c \"{wrapped_script}\""])

            return {
                "status": "launched_in_terminal",
                "terminal": term_bin,
                "pid": proc.pid,
                "message": f"Comando lanzado en terminal gráfica ({os.path.basename(term_bin)})."
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    else:
        return {"status": "error", "error": f"Método desconocido: {method}"}


# ─────────────────────────────────────────────────────────────────────────────
# PRUEBAS Y DEMOSTRACIÓN DIRECTA
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  MODELO DE CONTROL DE TERMINAL Y CARPETAS PARA POP!_OS")
    print("=" * 60)

    # 1. Probar crear carpeta en Pop!_OS
    test_path = "~/test_sylix_pop_os/subcarpeta"
    print(f"\n1. Creando carpeta: {test_path}")
    res_folder = create_folder(test_path)
    print("   Resultado:", res_folder)

    # 2. Probar comando bash asíncrono
    print("\n2. Ejecutando comando bash (ls y uname):")
    cmd = f"ls -la {expand_user_path('~/test_sylix_pop_os')} && uname -a"
    res_bash = asyncio.run(run_bash_command(cmd))
    print("   Resultado:")
    print("   STDOUT:\n", res_bash.get("stdout"))

    # 3. Probar verificación de sudo
    print("\n3. Verificando estado de sudo:")
    res_sudo_check = asyncio.run(run_bash_command("sudo -n true 2>&1 || echo 'SUDO_REQUIRES_PASSWORD'"))
    print("   Estado sudo sin password:", res_sudo_check.get("stdout"))

    print("\n✓ Modelo de ejecución listo.")
