"""
tools.py — Sylix OS Core Assistant
Módulo integrado: Chronos (Bash/Ciberseguridad) + JCySharp (Desktop Automation)
"""

import asyncio
import os
import subprocess
import shlex
import logging
import re
import shutil
import datetime
from typing import Any

# ─── Detección de entorno de escritorio (X11 vs Wayland) ──────────────────────
SESSION_TYPE = os.environ.get("XDG_SESSION_TYPE", "unknown").lower()

# ─── Registro en memoria de tareas en segundo plano ──────────────────────────
BACKGROUND_JOBS: dict[int, dict[str, Any]] = {}

# ─── Imports opcionales con fallback ─────────────────────────────────────────
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    PYAUTOGUI_AVAILABLE = True
except BaseException as e:
    PYAUTOGUI_AVAILABLE = False
    logging.warning(f"[tools] pyautogui no disponible ({e}). Automatización de escritorio en modo seguro.")

# ─── Logging ─────────────────────────────────────────────────────────────────
logger = logging.getLogger("sylix.tools")
if SESSION_TYPE == "wayland":
    logger.info("[tools] Sesión Wayland detectada. Herramientas X11 (xdotool, wmctrl) pueden tener restricciones.")


# ═══════════════════════════════════════════════════════════════════════════════
#  ESQUEMAS DE HERRAMIENTAS ANTHROPIC (Tool Calling)
# ═══════════════════════════════════════════════════════════════════════════════

ANTHROPIC_TOOLS = [
    # ── 1. MÓDULO BASH / CHRONOS ──────────────────────────────────────────────
    {
        "name": "execute_bash",
        "description": (
            "Ejecuta un comando Bash en el sistema operativo del usuario (Linux/Pop!_OS). "
            "Úsalo para: diagnóstico de red (ping, ip, ifconfig), escaneo de puertos (nmap), "
            "monitoreo de sockets (ss, netstat), inspección de procesos (ps, top, htop), "
            "gestión de servicios (systemctl), operaciones de sistema de archivos y cualquier "
            "comando de terminal. Devuelve stdout + stderr."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "El comando Bash completo a ejecutar. Puede incluir pipes (|), "
                        "redirecciones (>) y operadores lógicos (&&, ||). "
                        "Ejemplo: 'nmap -sV -p 80,443 192.168.1.1'"
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": "Tiempo máximo de espera en segundos (por defecto 30).",
                    "default": 30,
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "Si es true, el comando se lanza en segundo plano y retorna "
                        "inmediatamente con el PID del proceso. Útil para procesos largos."
                    ),
                    "default": False,
                },
            },
            "required": ["command"],
        },
    },

    # ── 2. MÓDULO DESKTOP AUTOMATION / JCYSHARP ───────────────────────────────
    {
        "name": "desktop_automation",
        "description": (
            "Controla la interfaz gráfica del escritorio Linux. Permite: mover el cursor a "
            "coordenadas exactas, hacer clic (izquierdo/derecho/doble), arrastrar elementos, "
            "simular combinaciones de teclado, abrir aplicaciones o carpetas en el gestor de "
            "archivos, y reorganizar ventanas en mosaico. Devuelve el resultado de la acción."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "move_mouse",
                        "click",
                        "double_click",
                        "right_click",
                        "drag",
                        "type_text",
                        "hotkey",
                        "key_press",
                        "open_folder",
                        "open_application",
                        "tile_windows",
                        "screenshot",
                        "scroll",
                        "get_screen_size",
                    ],
                    "description": "La acción de automatización a ejecutar.",
                },
                "x": {
                    "type": "integer",
                    "description": "Coordenada X en píxeles (para acciones de ratón).",
                },
                "y": {
                    "type": "integer",
                    "description": "Coordenada Y en píxeles (para acciones de ratón).",
                },
                "x2": {
                    "type": "integer",
                    "description": "Coordenada X destino para arrastre (drag).",
                },
                "y2": {
                    "type": "integer",
                    "description": "Coordenada Y destino para arrastre (drag).",
                },
                "text": {
                    "type": "string",
                    "description": "Texto a escribir (para type_text) o nombre de la app/carpeta.",
                },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Lista de teclas para hotkey o key_press. "
                        "Ejemplo: ['ctrl', 'c'] para copiar. "
                        "Nombres válidos: ctrl, alt, shift, super, tab, enter, escape, F1-F12, etc."
                    ),
                },
                "duration": {
                    "type": "number",
                    "description": "Duración del movimiento de ratón en segundos (por defecto 0.3).",
                    "default": 0.3,
                },
                "clicks": {
                    "type": "integer",
                    "description": "Número de clics (para scroll: positivo=arriba, negativo=abajo).",
                    "default": 1,
                },
                "tile_layout": {
                    "type": "string",
                    "enum": ["horizontal", "vertical", "grid", "maximize"],
                    "description": "Disposición para tile_windows.",
                    "default": "horizontal",
                },
                "path": {
                    "type": "string",
                    "description": "Ruta de carpeta para open_folder.",
                },
            },
            "required": ["action"],
        },
    },

    # ── 3. MÓDULO GESTIÓN DE ARCHIVOS ─────────────────────────────────────────
    {
        "name": "file_manager",
        "description": (
            "Gestiona el sistema de archivos: crear carpetas, mover/copiar/eliminar archivos, "
            "listar directorios, leer contenido de archivos de texto y escribir archivos. "
            "Todas las operaciones son asíncronas y seguras."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "create_dir",
                        "list_dir",
                        "move",
                        "copy",
                        "delete",
                        "read_file",
                        "write_file",
                        "get_size",
                        "find_files",
                    ],
                    "description": "Operación de sistema de archivos a realizar.",
                },
                "path": {
                    "type": "string",
                    "description": "Ruta principal del archivo o directorio.",
                },
                "destination": {
                    "type": "string",
                    "description": "Ruta destino para operaciones de movimiento/copia.",
                },
                "content": {
                    "type": "string",
                    "description": "Contenido a escribir en el archivo (para write_file).",
                },
                "pattern": {
                    "type": "string",
                    "description": "Patrón de búsqueda para find_files (e.g., '*.py', '*.log').",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Si es true, la operación es recursiva.",
                    "default": False,
                },
                "offset": {
                    "type": "integer",
                    "description": "Desplazamiento inicial en caracteres para read_file (por defecto 0).",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Cantidad máxima de caracteres a leer en read_file (por defecto 50000).",
                    "default": 50000,
                },
            },
            "required": ["operation", "path"],
        },
    },

    # ── 4. MÓDULO MONITOREO DEL SISTEMA ───────────────────────────────────────
    {
        "name": "system_monitor",
        "description": (
            "Obtiene métricas del sistema en tiempo real: uso de CPU, RAM, disco, "
            "temperatura, procesos activos, conexiones de red, batería y estado de servicios."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": [
                        "cpu",
                        "memory",
                        "disk",
                        "network",
                        "processes",
                        "temperature",
                        "battery",
                        "services",
                        "background_jobs",
                        "full_report",
                    ],
                    "description": "Métrica del sistema a consultar.",
                },
                "process_name": {
                    "type": "string",
                    "description": "Nombre del proceso o servicio a filtrar.",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Número de procesos más consumidores a listar (para processes).",
                    "default": 10,
                },
            },
            "required": ["metric"],
        },
    },
]

# ─── ESQUEMA COMPACTO ("SLIM TOOLS") PARA MODELOS LOCALES / OLLAMA ───────────
ANTHROPIC_SLIM_TOOLS = [
    {
        "name": "execute_bash",
        "description": "Ejecuta comandos de terminal Bash (diagnósticos, red, procesos, paquetes). Devuelve stdout y stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Comando Bash a ejecutar."},
                "timeout": {"type": "integer", "description": "Segundos máximos de espera.", "default": 30},
                "background": {"type": "boolean", "description": "Lanzar en segundo plano.", "default": False},
            },
            "required": ["command"],
        },
    },
    {
        "name": "desktop_automation",
        "description": "Controla ratón, teclado y aplicaciones en Linux.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "move_mouse", "click", "double_click", "right_click",
                        "type_text", "hotkey", "screenshot", "open_application",
                        "open_folder", "tile_windows"
                    ],
                    "description": "Acción a realizar.",
                },
                "x": {"type": "integer", "description": "Coordenada X."},
                "y": {"type": "integer", "description": "Coordenada Y."},
                "text": {"type": "string", "description": "Texto a escribir o app/carpeta a abrir."},
                "keys": {"type": "array", "items": {"type": "string"}, "description": "Teclas (ej: ['ctrl', 'c'])."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "file_manager",
        "description": "Operaciones de archivos y carpetas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["create_dir", "list_dir", "move", "copy", "delete", "read_file", "write_file", "find_files"],
                    "description": "Operación de archivo.",
                },
                "path": {"type": "string", "description": "Ruta del archivo o carpeta."},
                "destination": {"type": "string", "description": "Destino para move/copy."},
                "content": {"type": "string", "description": "Contenido para write_file."},
                "offset": {"type": "integer", "description": "Offset inicial para read_file.", "default": 0},
                "limit": {"type": "integer", "description": "Límite de caracteres.", "default": 10000},
            },
            "required": ["operation", "path"],
        },
    },
    {
        "name": "system_monitor",
        "description": "Consulta métricas del sistema en tiempo real.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": ["cpu", "memory", "disk", "network", "processes", "temperature", "battery", "services", "background_jobs", "full_report"],
                    "description": "Métrica a consultar.",
                },
                "process_name": {"type": "string", "description": "Nombre de proceso o servicio."},
            },
            "required": ["metric"],
        },
    },
]



# ═══════════════════════════════════════════════════════════════════════════════
#  MÓDULO 1: BASH / CHRONOS
# ═══════════════════════════════════════════════════════════════════════════════

async def execute_bash(
    command: str,
    timeout: int = 30,
    background: bool = False,
) -> dict[str, Any]:
    """
    Ejecuta un comando Bash de forma asíncrona y no bloqueante.
    
    Args:
        command: Comando Bash completo a ejecutar.
        timeout: Tiempo máximo de espera en segundos.
        background: Si True, lanza el proceso en segundo plano.
    
    Returns:
        dict con stdout, stderr, returncode y pid.
    """
    logger.info(f"[Chronos] Ejecutando: {command!r} | background={background}")

    # Sanitización básica (previene los caracteres más peligrosos en modo interactivo)
    # El agente tiene acceso autorizado al sistema; esto es solo un log de auditoría.
    audit_log = f"CMD: {command}"
    logger.debug(audit_log)

    if background:
        # Lanzar en segundo plano, no esperar
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            BACKGROUND_JOBS[proc.pid] = {
                "command": command,
                "started_at": now_str,
            }
            return {
                "status": "launched_background",
                "pid": proc.pid,
                "command": command,
                "message": f"Proceso lanzado en segundo plano con PID {proc.pid}.",
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "command": command}

    user_home = os.path.expanduser("~")
    cmd_to_run = command

    # Manejo de privilegios de superusuario (sudo / pkexec)
    if re.search(r'\bsudo\b', command):
        has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        if shutil.which("pkexec") and has_display:
            # En entornos con escritorio, pkexec muestra el cuadro de diálogo gráfico nativo de Pop!_OS/GNOME
            cmd_to_run = re.sub(r'\bsudo\b', 'pkexec', command)
        else:
            # En entornos sin GUI, forzar -n para fallar inmediatamente si requiere password en lugar de bloquearse
            if not re.search(r'\bsudo\s+-n\b', cmd_to_run):
                cmd_to_run = re.sub(r'\bsudo\b', 'sudo -n', cmd_to_run)

    # Ejecución normal con captura de salida
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd_to_run,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=user_home,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=float(timeout)
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {
                "status": "timeout",
                "command": command,
                "timeout_seconds": timeout,
                "message": f"El comando superó el límite de {timeout}s y fue terminado.",
            }

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        returncode = proc.returncode

        if returncode != 0 and stderr and ("a password is required" in stderr.lower() or "contraseña" in stderr.lower()):
            stderr += "\n[Aviso: El comando requiere privilegios sudo y no puede solicitar contraseña interactivamente sin TTY]"

        result = {
            "status": "success" if returncode == 0 else "error",
            "returncode": returncode,
            "stdout": stdout[:8000] if stdout else "",   # Límite de 8k caracteres
            "stderr": stderr[:2000] if stderr else "",   # Límite de 2k caracteres
            "command": command,
        }

        if stdout:
            logger.debug(f"[Chronos] stdout: {stdout[:200]}...")
        if stderr and returncode != 0:
            logger.warning(f"[Chronos] stderr: {stderr[:200]}")

        return result

    except FileNotFoundError as e:
        return {"status": "error", "error": f"Comando no encontrado: {e}", "command": command}
    except PermissionError as e:
        return {"status": "error", "error": f"Permiso denegado: {e}", "command": command}
    except Exception as e:
        logger.exception(f"[Chronos] Error inesperado ejecutando: {command!r}")
        return {"status": "error", "error": str(e), "command": command}


# ═══════════════════════════════════════════════════════════════════════════════
#  MÓDULO 2: DESKTOP AUTOMATION / JCYSHARP
# ═══════════════════════════════════════════════════════════════════════════════

async def desktop_automation(
    action: str,
    x: int | None = None,
    y: int | None = None,
    x2: int | None = None,
    y2: int | None = None,
    text: str | None = None,
    keys: list[str] | None = None,
    duration: float = 0.3,
    clicks: int = 1,
    tile_layout: str = "horizontal",
    path: str | None = None,
) -> dict[str, Any]:
    """
    Controla la interfaz gráfica del escritorio de forma asíncrona.
    Usa un executor para correr pyautogui/xdotool en un thread separado
    y no bloquear el event loop de asyncio.
    """
    loop = asyncio.get_event_loop()

    def _run_automation() -> dict[str, Any]:
        """Función sincrónica que corre en el executor."""
        return _execute_desktop_action(
            action=action, x=x, y=y, x2=x2, y2=y2,
            text=text, keys=keys, duration=duration,
            clicks=clicks, tile_layout=tile_layout, path=path,
        )

    try:
        result = await loop.run_in_executor(None, _run_automation)
        return result
    except Exception as e:
        logger.exception(f"[JCySharp] Error en desktop_automation: {action!r}")
        return {"status": "error", "action": action, "error": str(e)}


def _execute_desktop_action(
    action: str,
    x: int | None,
    y: int | None,
    x2: int | None,
    y2: int | None,
    text: str | None,
    keys: list[str] | None,
    duration: float,
    clicks: int,
    tile_layout: str,
    path: str | None,
) -> dict[str, Any]:
    """Lógica sincrónica de automatización de escritorio."""

    logger.info(f"[JCySharp] Acción: {action!r} | x={x}, y={y}, text={text!r}")

    # ── OBTENER TAMAÑO DE PANTALLA ────────────────────────────────────────────
    if action == "get_screen_size":
        if PYAUTOGUI_AVAILABLE:
            width, height = pyautogui.size()
            return {"status": "success", "action": action, "width": width, "height": height}
        else:
            # Fallback con xdotool
            result = subprocess.run(
                ["xdotool", "getdisplaygeometry"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                return {"status": "success", "action": action,
                        "width": int(parts[0]), "height": int(parts[1])}
            return {"status": "error", "action": action, "error": "xdotool no disponible"}

    # ── CAPTURA DE PANTALLA ───────────────────────────────────────────────────
    if action == "screenshot":
        screenshot_path = os.path.expanduser("~/sylix_screenshot.png")
        if PYAUTOGUI_AVAILABLE:
            screenshot = pyautogui.screenshot()
            screenshot.save(screenshot_path)
        else:
            subprocess.run(["scrot", screenshot_path], timeout=5)
        return {"status": "success", "action": action, "saved_to": screenshot_path}

    # ── MOVER RATÓN ───────────────────────────────────────────────────────────
    if action == "move_mouse":
        if x is None or y is None:
            return {"status": "error", "action": action, "error": "Se requieren x e y."}
        if PYAUTOGUI_AVAILABLE:
            pyautogui.moveTo(x, y, duration=duration)
        else:
            subprocess.run(["xdotool", "mousemove", str(x), str(y)], timeout=5)
        return {"status": "success", "action": action, "moved_to": {"x": x, "y": y}}

    # ── CLIC SIMPLE ───────────────────────────────────────────────────────────
    if action == "click":
        if x is not None and y is not None:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.click(x, y, clicks=clicks, duration=duration)
            else:
                subprocess.run(
                    ["xdotool", "mousemove", str(x), str(y), "click", "1"],
                    timeout=5,
                )
        else:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.click(clicks=clicks)
            else:
                subprocess.run(["xdotool", "click", "1"], timeout=5)
        return {"status": "success", "action": action, "position": {"x": x, "y": y}}

    # ── DOBLE CLIC ────────────────────────────────────────────────────────────
    if action == "double_click":
        if x is not None and y is not None:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.doubleClick(x, y, duration=duration)
            else:
                subprocess.run(
                    ["xdotool", "mousemove", str(x), str(y), "click", "--repeat", "2", "1"],
                    timeout=5,
                )
        else:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.doubleClick()
        return {"status": "success", "action": action, "position": {"x": x, "y": y}}

    # ── CLIC DERECHO ──────────────────────────────────────────────────────────
    if action == "right_click":
        if x is not None and y is not None:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.rightClick(x, y, duration=duration)
            else:
                subprocess.run(
                    ["xdotool", "mousemove", str(x), str(y), "click", "3"],
                    timeout=5,
                )
        else:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.rightClick()
        return {"status": "success", "action": action, "position": {"x": x, "y": y}}

    # ── ARRASTRE ─────────────────────────────────────────────────────────────
    if action == "drag":
        if x is None or y is None or x2 is None or y2 is None:
            return {"status": "error", "action": action, "error": "Se requieren x, y, x2, y2."}
        if PYAUTOGUI_AVAILABLE:
            pyautogui.moveTo(x, y, duration=0.1)
            pyautogui.dragTo(x2, y2, duration=duration, button="left")
        else:
            subprocess.run(
                ["xdotool", "mousemove", str(x), str(y),
                 "mousedown", "1", "mousemove", str(x2), str(y2), "mouseup", "1"],
                timeout=10,
            )
        return {
            "status": "success", "action": action,
            "from": {"x": x, "y": y}, "to": {"x": x2, "y": y2},
        }

    # ── ESCRIBIR TEXTO ────────────────────────────────────────────────────────
    if action == "type_text":
        if not text:
            return {"status": "error", "action": action, "error": "Se requiere 'text'."}
        if PYAUTOGUI_AVAILABLE:
            pyautogui.write(text, interval=0.02)
        else:
            subprocess.run(["xdotool", "type", "--clearmodifiers", text], timeout=30)
        return {"status": "success", "action": action, "typed": text}

    # ── HOTKEY / COMBINACIÓN DE TECLAS ───────────────────────────────────────
    if action == "hotkey":
        if not keys:
            return {"status": "error", "action": action, "error": "Se requieren 'keys'."}
        if PYAUTOGUI_AVAILABLE:
            pyautogui.hotkey(*keys)
        else:
            xdotool_key = "+".join(keys)
            subprocess.run(["xdotool", "key", xdotool_key], timeout=5)
        return {"status": "success", "action": action, "hotkey": keys}

    # ── TECLA INDIVIDUAL ──────────────────────────────────────────────────────
    if action == "key_press":
        if not keys:
            return {"status": "error", "action": action, "error": "Se requieren 'keys'."}
        for key in keys:
            if PYAUTOGUI_AVAILABLE:
                pyautogui.press(key)
            else:
                subprocess.run(["xdotool", "key", key], timeout=5)
        return {"status": "success", "action": action, "keys_pressed": keys}

    # ── SCROLL ────────────────────────────────────────────────────────────────
    if action == "scroll":
        scroll_amount = clicks if clicks else 3
        if PYAUTOGUI_AVAILABLE:
            if x is not None and y is not None:
                pyautogui.scroll(scroll_amount, x=x, y=y)
            else:
                pyautogui.scroll(scroll_amount)
        else:
            button = "4" if scroll_amount > 0 else "5"
            for _ in range(abs(scroll_amount)):
                subprocess.run(["xdotool", "click", button], timeout=5)
        return {"status": "success", "action": action, "scroll_amount": scroll_amount}

    # ── ABRIR CARPETA ─────────────────────────────────────────────────────────
    if action == "open_folder":
        folder_path = path or os.path.expanduser("~")
        folder_path = os.path.expanduser(folder_path)
        if not os.path.exists(folder_path):
            os.makedirs(folder_path, exist_ok=True)
        # Detectar gestor de archivos disponible
        file_managers = ["nautilus", "nemo", "thunar", "dolphin", "xdg-open"]
        for fm in file_managers:
            try:
                subprocess.Popen([fm, folder_path])
                return {"status": "success", "action": action, "opened": folder_path, "manager": fm}
            except FileNotFoundError:
                continue
        return {"status": "error", "action": action, "error": "No se encontró gestor de archivos."}

    # ── ABRIR APLICACIÓN ──────────────────────────────────────────────────────
    if action == "open_application":
        if not text:
            return {"status": "error", "action": action, "error": "Se requiere 'text' con el nombre."}
        try:
            proc = subprocess.Popen(
                shlex.split(text),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {
                "status": "success", "action": action,
                "application": text, "pid": proc.pid,
            }
        except FileNotFoundError:
            # Intentar con xdg-open
            try:
                subprocess.Popen(["xdg-open", text], start_new_session=True)
                return {"status": "success", "action": action, "application": text}
            except Exception as e:
                return {"status": "error", "action": action, "error": str(e)}

    # ── MOSAICO DE VENTANAS ───────────────────────────────────────────────────
    if action == "tile_windows":
        return _tile_windows(layout=tile_layout)

    return {"status": "error", "action": action, "error": f"Acción desconocida: {action!r}"}


def _tile_windows(layout: str = "horizontal") -> dict[str, Any]:
    """
    Organiza las ventanas abiertas en diferentes disposiciones usando wmctrl/xdotool.
    """
    # Obtener resolución de pantalla
    try:
        result = subprocess.run(
            ["xdotool", "getdisplaygeometry"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            screen_w, screen_h = int(parts[0]), int(parts[1])
        else:
            screen_w, screen_h = 1920, 1080
    except Exception:
        screen_w, screen_h = 1920, 1080

    # Obtener lista de ventanas con wmctrl
    try:
        result = subprocess.run(
            ["wmctrl", "-l"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return {"status": "error", "action": "tile_windows", "error": "wmctrl no disponible."}

        windows = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split(None, 3)
            if len(parts) >= 2:
                wid = parts[0]
                desktop_id = parts[1]
                title = parts[3].strip() if len(parts) >= 4 else ""
                # Ignorar ventanas sticky/paneles (-1), escritorios y elementos del sistema
                if desktop_id == "-1" or title.lower() in ("desktop", "gnome-shell", ""):
                    continue
                windows.append(wid)

        if not windows:
            return {"status": "success", "action": "tile_windows", "message": "No hay ventanas abiertas."}

        count = len(windows)
        arranged = []

        if layout == "maximize":
            for wid in windows:
                subprocess.run(["wmctrl", "-ir", wid, "-b", "add,maximized_vert,maximized_horz"])
                arranged.append(wid)

        elif layout == "horizontal" and count >= 2:
            w = screen_w // count
            for i, wid in enumerate(windows):
                # Desmaximizar primero
                subprocess.run(["wmctrl", "-ir", wid, "-b", "remove,maximized_vert,maximized_horz"])
                x_pos = i * w
                geom = f"0,{x_pos},{0},{w},{screen_h}"
                subprocess.run(["wmctrl", "-ir", wid, "-e", geom])
                arranged.append(wid)

        elif layout == "vertical" and count >= 2:
            h = screen_h // count
            for i, wid in enumerate(windows):
                subprocess.run(["wmctrl", "-ir", wid, "-b", "remove,maximized_vert,maximized_horz"])
                y_pos = i * h
                geom = f"0,{0},{y_pos},{screen_w},{h}"
                subprocess.run(["wmctrl", "-ir", wid, "-e", geom])
                arranged.append(wid)

        elif layout == "grid" and count >= 2:
            import math
            cols = math.ceil(math.sqrt(count))
            rows = math.ceil(count / cols)
            w = screen_w // cols
            h = screen_h // rows
            for i, wid in enumerate(windows):
                subprocess.run(["wmctrl", "-ir", wid, "-b", "remove,maximized_vert,maximized_horz"])
                col = i % cols
                row = i // cols
                geom = f"0,{col * w},{row * h},{w},{h}"
                subprocess.run(["wmctrl", "-ir", wid, "-e", geom])
                arranged.append(wid)

        return {
            "status": "success",
            "action": "tile_windows",
            "layout": layout,
            "windows_arranged": len(arranged),
            "screen": {"width": screen_w, "height": screen_h},
        }

    except FileNotFoundError:
        return {"status": "error", "action": "tile_windows", "error": "wmctrl no encontrado. Instalar con: sudo apt install wmctrl"}
    except Exception as e:
        return {"status": "error", "action": "tile_windows", "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
#  MÓDULO 3: GESTIÓN DE ARCHIVOS
# ═══════════════════════════════════════════════════════════════════════════════

# Directorios críticos del sistema protegidos contra eliminación accidental
PROTECTED_SYSTEM_PATHS = {
    "/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib32", "/lib64",
    "/media", "/mnt", "/opt", "/proc", "/root", "/run", "/sbin", "/srv",
    "/sys", "/tmp", "/usr", "/var"
}

async def file_manager(
    operation: str,
    path: str,
    destination: str | None = None,
    content: str | None = None,
    pattern: str | None = None,
    recursive: bool = False,
    offset: int = 0,
    limit: int = 50000,
) -> dict[str, Any]:
    """
    Operaciones asíncronas sobre el sistema de archivos.
    """
    loop = asyncio.get_event_loop()

    def _run():
        return _execute_file_operation(
            operation=operation, path=path, destination=destination,
            content=content, pattern=pattern, recursive=recursive,
            offset=offset, limit=limit,
        )

    try:
        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.exception(f"[FileManager] Error en operación: {operation!r}")
        return {"status": "error", "operation": operation, "error": str(e)}


def _execute_file_operation(
    operation: str,
    path: str,
    destination: str | None,
    content: str | None,
    pattern: str | None,
    recursive: bool,
    offset: int = 0,
    limit: int = 50000,
) -> dict[str, Any]:
    """Lógica sincrónica de gestión de archivos."""
    import glob
    import shutil

    path = os.path.expanduser(path.strip())
    if not os.path.isabs(path):
        path = os.path.join(os.path.expanduser("~"), path)

    if operation == "create_dir":
        os.makedirs(path, exist_ok=True)
        return {"status": "success", "operation": operation, "created": path}

    if operation == "list_dir":
        if not os.path.exists(path):
            return {"status": "error", "operation": operation, "error": f"No existe: {path}"}
        if recursive:
            items = []
            for root, dirs, files in os.walk(path):
                for f in files:
                    items.append(os.path.join(root, f))
            return {"status": "success", "operation": operation, "items": items[:500]}
        else:
            items = os.listdir(path)
            return {"status": "success", "operation": operation, "path": path, "items": items}

    if operation == "move":
        if not destination:
            return {"status": "error", "operation": operation, "error": "Se requiere 'destination'."}
        destination = os.path.expanduser(destination)
        shutil.move(path, destination)
        return {"status": "success", "operation": operation, "moved": {"from": path, "to": destination}}

    if operation == "copy":
        if not destination:
            return {"status": "error", "operation": operation, "error": "Se requiere 'destination'."}
        destination = os.path.expanduser(destination)
        if os.path.isdir(path):
            shutil.copytree(path, destination)
        else:
            shutil.copy2(path, destination)
        return {"status": "success", "operation": operation, "copied": {"from": path, "to": destination}}

    if operation == "delete":
        real_path = os.path.realpath(path)
        user_home = os.path.realpath(os.path.expanduser("~"))

        if not path or path.strip() in ("", "."):
            return {"status": "error", "operation": operation, "error": "Ruta inválida para eliminación."}

        # Salvaguarda: bloquear eliminación de directorios raíz y carpetas críticas del sistema
        if real_path in PROTECTED_SYSTEM_PATHS or real_path == user_home or path.strip() == "/":
            return {
                "status": "error",
                "operation": operation,
                "error": f"Operación denegada por seguridad: '{path}' es una ruta protegida del sistema o el directorio raíz del usuario.",
            }

        if not os.path.exists(path):
            return {"status": "error", "operation": operation, "error": f"No existe: {path}"}

        if os.path.isdir(path):
            if recursive:
                shutil.rmtree(path)
            else:
                os.rmdir(path)
        else:
            os.remove(path)
        return {"status": "success", "operation": operation, "deleted": path}

    if operation == "read_file":
        if not os.path.isfile(path):
            return {"status": "error", "operation": operation, "error": f"No es archivo: {path}"}

        offset_val = max(0, int(offset or 0))
        limit_val = max(1, min(int(limit or 50000), 100000))
        total_size = os.path.getsize(path)

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            if offset_val > 0:
                f.seek(offset_val)
            file_content = f.read(limit_val)

        has_more = (offset_val + len(file_content.encode("utf-8", errors="replace"))) < total_size
        return {
            "status": "success",
            "operation": operation,
            "path": path,
            "content": file_content,
            "offset": offset_val,
            "limit": limit_val,
            "total_size_bytes": total_size,
            "has_more": has_more,
        }

    if operation == "write_file":
        if content is None:
            return {"status": "error", "operation": operation, "error": "Se requiere 'content'."}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "success", "operation": operation, "written": path, "bytes": len(content)}

    if operation == "get_size":
        if os.path.isfile(path):
            size = os.path.getsize(path)
        elif os.path.isdir(path):
            size = sum(
                os.path.getsize(os.path.join(root, f))
                for root, _, files in os.walk(path)
                for f in files
            )
        else:
            return {"status": "error", "operation": operation, "error": f"No existe: {path}"}
        return {"status": "success", "operation": operation, "path": path, "size_bytes": size,
                "size_mb": round(size / 1024 / 1024, 2)}

    if operation == "find_files":
        search_pattern = os.path.join(path, "**", pattern or "*") if recursive else os.path.join(path, pattern or "*")
        matches = glob.glob(search_pattern, recursive=recursive)
        return {"status": "success", "operation": operation, "pattern": pattern,
                "matches": matches[:200], "total": len(matches)}

    return {"status": "error", "operation": operation, "error": f"Operación desconocida: {operation!r}"}


# ═══════════════════════════════════════════════════════════════════════════════
#  MÓDULO 4: MONITOREO DEL SISTEMA
# ═══════════════════════════════════════════════════════════════════════════════

async def system_monitor(
    metric: str,
    process_name: str | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    """
    Recopila métricas del sistema usando comandos del sistema y psutil (si disponible).
    """
    loop = asyncio.get_event_loop()

    def _run():
        return _get_system_metric(metric=metric, process_name=process_name, top_n=top_n)

    try:
        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.exception(f"[SysMonitor] Error obteniendo métrica: {metric!r}")
        return {"status": "error", "metric": metric, "error": str(e)}


def _get_system_metric(
    metric: str,
    process_name: str | None,
    top_n: int,
) -> dict[str, Any]:
    """Obtiene métricas del sistema."""
    results = {}

    def _run_cmd(cmd: str) -> str:
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return r.stdout.strip()
        except Exception:
            return ""

    if metric in ("cpu", "full_report"):
        cpu_output = _run_cmd("grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$3+$4+$5)} END {printf \"%.1f\", usage}'")
        cpu_count = _run_cmd("nproc")
        load_avg = _run_cmd("cat /proc/loadavg | awk '{print $1, $2, $3}'")
        results["cpu"] = {
            "usage_percent": cpu_output,
            "core_count": cpu_count,
            "load_avg_1m_5m_15m": load_avg,
        }
        if metric == "cpu":
            return {"status": "success", "metric": metric, **results}

    if metric in ("memory", "full_report"):
        mem_output = _run_cmd("free -h | awk 'NR==2{print \"total=\"$2\",used=\"$3\",free=\"$4\",available=\"$7}'")
        results["memory"] = {"summary": mem_output}
        if metric == "memory":
            return {"status": "success", "metric": metric, **results}

    if metric in ("disk", "full_report"):
        disk_output = _run_cmd("df -h --output=source,size,used,avail,pcent,target | tail -n +2")
        results["disk"] = {"filesystems": disk_output}
        if metric == "disk":
            return {"status": "success", "metric": metric, **results}

    if metric in ("network", "full_report"):
        interfaces = _run_cmd("ip -brief addr show")
        connections = _run_cmd("ss -tuln | head -30")
        results["network"] = {"interfaces": interfaces, "listening_sockets": connections}
        if metric == "network":
            return {"status": "success", "metric": metric, **results}

    if metric in ("processes", "full_report"):
        if process_name:
            ps_output = _run_cmd(f"ps aux | grep -i {shlex.quote(process_name)} | grep -v grep")
        else:
            ps_output = _run_cmd(f"ps aux --sort=-%cpu | head -n {top_n + 1}")
        results["processes"] = {"output": ps_output}
        if metric == "processes":
            return {"status": "success", "metric": metric, **results}

    if metric in ("temperature", "full_report"):
        temp_output = _run_cmd("cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | awk '{printf \"%.1f°C \", $1/1000}'")
        sensors_output = _run_cmd("sensors 2>/dev/null | grep -E 'Core|Temp|temp' | head -15")
        results["temperature"] = {
            "thermal_zones": temp_output,
            "sensors": sensors_output,
        }
        if metric == "temperature":
            return {"status": "success", "metric": metric, **results}

    if metric in ("battery", "full_report"):
        battery_output = _run_cmd("cat /sys/class/power_supply/BAT*/capacity 2>/dev/null")
        battery_status = _run_cmd("cat /sys/class/power_supply/BAT*/status 2>/dev/null")
        results["battery"] = {"capacity": battery_output, "status": battery_status}
        if metric == "battery":
            return {"status": "success", "metric": metric, **results}

    if metric in ("services", "full_report"):
        if process_name:
            svc_output = _run_cmd(f"systemctl status {shlex.quote(process_name)} 2>&1 | head -20")
        else:
            svc_output = _run_cmd("systemctl list-units --type=service --state=running --no-pager | head -25")
        results["services"] = {"output": svc_output}
        if metric == "services":
            return {"status": "success", "metric": metric, **results}

    if metric in ("background_jobs", "full_report"):
        jobs_list = []
        for pid, job in list(BACKGROUND_JOBS.items()):
            is_alive = False
            try:
                os.kill(pid, 0)
                is_alive = True
            except (OSError, ProcessLookupError):
                is_alive = False
            jobs_list.append({
                "pid": pid,
                "command": job.get("command"),
                "started_at": job.get("started_at"),
                "status": "running" if is_alive else "terminated",
            })
        results["background_jobs"] = jobs_list
        if metric == "background_jobs":
            return {"status": "success", "metric": metric, "jobs": jobs_list}

    if metric == "full_report":
        return {"status": "success", "metric": "full_report", **results}

    return {"status": "error", "metric": metric, "error": f"Métrica desconocida: {metric!r}"}


# ═══════════════════════════════════════════════════════════════════════════════
#  DISPATCHER CENTRAL DE HERRAMIENTAS
# ═══════════════════════════════════════════════════════════════════════════════

class ToolResult(str):
    """
    Cadena JSON que además implementa la interfaz de dict (.get(), [] e 'in')
    para compatibilidad bidireccional:
      1. Clientes LLM (Anthropic/OpenAI) que consumen el resultado como str.
      2. Enrutadores internos de la app (ej. main.py) que acceden con result.get("status").
    """
    data: dict[str, Any]

    def __new__(cls, content: str, data: dict[str, Any]):
        obj = super().__new__(cls, content)
        obj.data = data
        return obj

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            return self.data[key]
        return super().__getitem__(key)

    def __contains__(self, key: Any) -> bool:
        if isinstance(key, str):
            return key in self.data
        return super().__contains__(key)


async def dispatch_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    client_id: str | None = None,
    *args: Any,
    **kwargs: Any,
) -> ToolResult:
    """
    Función central que despacha las llamadas a herramientas del agente Anthropic.
    
    Args:
        tool_name: Nombre de la herramienta según el esquema ANTHROPIC_TOOLS.
        tool_input: Parámetros de entrada validados por el modelo.
        client_id: Identificador opcional del cliente (usado por main.py para telemetría).
    
    Returns:
        ToolResult (híbrido str / dict) serializado como string para el modelo.
    """
    import json

    logger.info(f"[Dispatcher] Tool: {tool_name!r} | Client: {client_id} | Input: {tool_input}")

    try:
        if tool_name == "execute_bash":
            result = await execute_bash(
                command=tool_input["command"],
                timeout=tool_input.get("timeout", 30),
                background=tool_input.get("background", False),
            )

        elif tool_name == "desktop_automation":
            result = await desktop_automation(
                action=tool_input["action"],
                x=tool_input.get("x"),
                y=tool_input.get("y"),
                x2=tool_input.get("x2"),
                y2=tool_input.get("y2"),
                text=tool_input.get("text"),
                keys=tool_input.get("keys"),
                duration=tool_input.get("duration", 0.3),
                clicks=tool_input.get("clicks", 1),
                tile_layout=tool_input.get("tile_layout", "horizontal"),
                path=tool_input.get("path"),
            )

        elif tool_name == "file_manager":
            result = await file_manager(
                operation=tool_input["operation"],
                path=tool_input["path"],
                destination=tool_input.get("destination"),
                content=tool_input.get("content"),
                pattern=tool_input.get("pattern"),
                recursive=tool_input.get("recursive", False),
                offset=tool_input.get("offset", 0),
                limit=tool_input.get("limit", 50000),
            )

        elif tool_name == "system_monitor":
            result = await system_monitor(
                metric=tool_input["metric"],
                process_name=tool_input.get("process_name"),
                top_n=tool_input.get("top_n", 10),
            )

        else:
            result = {
                "status": "error",
                "error": f"Herramienta desconocida: {tool_name!r}",
            }

    except KeyError as e:
        result = {
            "status": "error",
            "tool": tool_name,
            "error": f"Parámetro requerido faltante: {e}",
        }
    except Exception as e:
        logger.exception(f"[Dispatcher] Error inesperado en {tool_name!r}")
        result = {
            "status": "error",
            "tool": tool_name,
            "error": str(e),
        }

    raw_json = json.dumps(result, ensure_ascii=False, indent=2)
    return ToolResult(raw_json, result)
