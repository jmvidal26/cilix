#!/usr/bin/env python3
"""
Controlador Seguro del Sistema Operativo para Cilix
===================================================
Ejecuta comandos locales en Linux con una capa de seguridad estricta:

· Lista BLANCA de comandos seguros y lista NEGRA de comandos destructivos.
· Detección de patrones peligrosos (rm -rf, fork bombs, pipes a bash...).
· Límites de longitud, salida, tiempo de ejecución y variables de entorno.
· Entorno de ejecución saneado (PATH/HOME/USER/LANG controlados).

Nada de privilegios (sudo/su bloqueados). El objetivo es que la IA jamás
pueda tumbar el sistema ni escapar de los límites de recursos.
"""

import asyncio
import logging
import os
import platform
import re
import shlex
import shutil
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CommandSafety(Enum):
    """Nivel de seguridad clasificado para un comando."""
    SAFE = "safe"
    RESTRICTED = "restricted"
    BLOCKED = "blocked"


@dataclass
class CommandResult:
    """Resultado estandarizado de la ejecución de un comando."""
    success: bool
    output: str
    error: str
    exit_code: int
    duration: float
    command: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code,
            "duration": round(self.duration, 3),
            "command": self.command,
        }


class OSController:
    """Ejecución validada y acotada de comandos del sistema."""

    def __init__(self, allowed_paths: Optional[List[str]] = None):
        self.allowed_paths = allowed_paths or [str(Path.home()), "/tmp", "/var/tmp"]

        # Lista blanca (primer token del comando)
        self.allowed_commands: Dict[str, CommandSafety] = {
            "ls": CommandSafety.SAFE, "cat": CommandSafety.SAFE,
            "file": CommandSafety.SAFE, "stat": CommandSafety.SAFE,
            "grep": CommandSafety.SAFE, "wc": CommandSafety.SAFE, "head": CommandSafety.SAFE,
            "tail": CommandSafety.SAFE, "find": CommandSafety.RESTRICTED,
            "date": CommandSafety.SAFE, "uptime": CommandSafety.SAFE,
            "whoami": CommandSafety.SAFE, "uname": CommandSafety.SAFE,
            "df": CommandSafety.SAFE, "free": CommandSafety.SAFE,
            "hostname": CommandSafety.SAFE, "which": CommandSafety.SAFE,
            "top": CommandSafety.SAFE, "ps": CommandSafety.SAFE,
            "xdg-open": CommandSafety.SAFE, "nautilus": CommandSafety.SAFE,
            "gedit": CommandSafety.SAFE, "firefox": CommandSafety.SAFE,
            "chromium": CommandSafety.SAFE, "code": CommandSafety.SAFE,
            "python3": CommandSafety.RESTRICTED, "node": CommandSafety.RESTRICTED,
        }

        # Lista negra: comandos destructivos o privilegiados
        self.blocked_commands = {
            "rm", "rmdir", "del", "format", "dd", "mkfs", "shred",
            "sudo", "su", "chmod", "chown", "passwd", "useradd", "userdel",
            "shutdown", "reboot", "halt", "poweroff", "ifconfig", "iptables",
            "bash", "sh", "zsh", "perl", "eval",
        }

        # Patrones peligrosos (regex)
        self.dangerous_patterns = [
            r"rm\s+-[rf]", r":\(\)\s*\{.*\};\s*:",       # rm -rf / fork bomb
            r">\s*/dev/", r"\|\s*(bash|sh)\b",           # redirección / pipe a shell
            r"\$\(", r"`", r";\s*rm", r"&&\s*rm",
        ]

        self.limits = {
            "max_command_length": 1000,
            "max_output_bytes": 1024 * 1024,   # 1 MB
            "max_execution_time": 30,          # s
        }

        self.stats: Dict[str, Any] = {
            "commands_executed": 0, "commands_blocked": 0,
            "safe_commands": 0, "restricted_commands": 0,
            "total_execution_time": 0.0,
        }
        self._apps_cache: Optional[Dict[str, Any]] = None
        logger.info("🛡️ OSController inicializado")

    # ── Clasificación y saneado ────────────────────────────────────────────
    def classify(self, command: str) -> Tuple[CommandSafety, str]:
        """Determina si un comando es seguro, restringido o bloqueado."""
        clean = command.strip()
        if len(clean) > self.limits["max_command_length"]:
            return CommandSafety.BLOCKED, "Comando demasiado largo"

        for pat in self.dangerous_patterns:
            if re.search(pat, clean, re.IGNORECASE):
                return CommandSafety.BLOCKED, f"Patrón peligroso: {pat}"

        try:
            parts = shlex.split(clean)
        except ValueError:
            return CommandSafety.BLOCKED, "Sintaxis inválida"
        if not parts:
            return CommandSafety.BLOCKED, "Comando vacío"

        base = Path(parts[0]).name.lower()
        if base in self.blocked_commands:
            return CommandSafety.BLOCKED, f"Comando bloqueado: {base}"
        if base in self.allowed_commands:
            return self.allowed_commands[base], f"Permitido: {base}"
        return CommandSafety.RESTRICTED, f"Desconocido: {base}"

    @staticmethod
    def _sanitize(command: str) -> str:
        """Elimina metacaracteres de shell en comandos restringidos."""
        dangerous = [";", "&", "|", "`", "$", "(", ")", "{", "}", "<", ">"]
        out = command
        for ch in dangerous:
            out = out.replace(ch, "")
        return out.strip()

    def _is_path_allowed(self, path: str) -> bool:
        try:
            abs_path = os.path.abspath(path)
            return any(
                abs_path.startswith(os.path.abspath(ap)) for ap in self.allowed_paths
            )
        except Exception:  # noqa: BLE001
            return False

    def _safe_env(self) -> Dict[str, str]:
        """Entorno mínimo y controlado para el comando hijo."""
        return {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(Path.home()),
            "USER": os.environ.get("USER", "user"),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        }

    def _session_env(self) -> Dict[str, str]:
        """
        Entorno con la SESIÓN GRÁFICA heredada (DISPLAY, Wayland, D-Bus…).

        Sin estas variables las aplicaciones GUI se ejecutan pero no aparecen
        en pantalla (por eso 'abre firefox' devolvía un pid sin ventana).
        """
        env = self._safe_env()
        env["PATH"] = os.environ.get(
            "PATH", "/usr/bin:/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/sbin"
        )
        for var in (
            "DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY", "XDG_DATA_DIRS",
            "GSETTINGS_SCHEMA_DIR", "XDG_CURRENT_DESKTOP",
        ):
            val = os.environ.get(var)
            if val:
                env[var] = val
        env.setdefault("DISPLAY", ":0")
        return env

    @staticmethod
    def _desktop_exists(name: str) -> bool:
        """¿Hay un .desktop instalable con ese nombre (para gtk-launch)?"""
        dirs = ("/usr/share/applications", "/var/lib/flatpak/exports/share/applications",
                os.path.expanduser("~/.local/share/applications"))
        return any(os.path.exists(os.path.join(d, name + ".desktop")) for d in dirs)

    # ── Ejecución principal ────────────────────────────────────────────────
    async def execute_safe_command(
        self, command: str, cwd: Optional[str] = None
    ) -> CommandResult:
        """Valida, sanitiza y ejecuta un comando con límites de recursos."""
        start = time.time()
        safety, reason = self.classify(command)

        if safety == CommandSafety.BLOCKED:
            self.stats["commands_blocked"] += 1
            logger.warning("🚫 Bloqueado (%s): %s", reason, command)
            return CommandResult(False, "", f"Bloqueado por seguridad: {reason}",
                                 1, time.time() - start, command)

        if safety == CommandSafety.RESTRICTED:
            command = self._sanitize(command)
            self.stats["restricted_commands"] += 1
            logger.info("⚠️ Restringido/sanitizado: %s", command)
        else:
            self.stats["safe_commands"] += 1

        if cwd and not self._is_path_allowed(cwd):
            cwd = None

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=self._safe_env(),
            )
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(), timeout=self.limits["max_execution_time"]
                )
            except asyncio.TimeoutError:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                return CommandResult(False, "", "Timeout: ejecución demasiado larga",
                                     -2, time.time() - start, command)

            output = (out or b"").decode("utf-8", "ignore")[: self.limits["max_output_bytes"]]
            error = (err or b"").decode("utf-8", "ignore")[: self.limits["max_output_bytes"]]

            self.stats["commands_executed"] += 1
            duration = time.time() - start
            self.stats["total_execution_time"] += duration

            logger.info("✅ Comando (%.2fs, exit %s)", duration, proc.returncode)
            return CommandResult(proc.returncode == 0, output.strip(), error.strip(),
                                 proc.returncode, duration, command)

        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error ejecutando comando: %s", exc)
            return CommandResult(False, "", f"Error interno: {exc}", -1,
                                 time.time() - start, command)

    # ── Aplicaciones instaladas (con caché) ────────────────────────────────
    async def get_installed_applications(self) -> List[str]:
        now = time.time()
        if self._apps_cache and now - self._apps_cache["ts"] < 300:
            return self._apps_cache["apps"]

        candidates = [
            "nautilus", "gedit", "firefox", "chromium", "code", "vlc", "gimp",
            "libreoffice", "thunderbird", "gnome-terminal", "konsole", "xterm",
        ]
        installed: List[str] = []
        for app in candidates:
            res = await self.execute_safe_command(f"which {app}")
            if res.success and res.output:
                installed.append(app)

        self._apps_cache = {"apps": installed, "ts": now}
        logger.info("📦 Aplicaciones detectadas: %d", len(installed))
        return installed

    async def launch_application(self, app_name: str,
                                 arguments: Optional[List[str]] = None) -> CommandResult:
        """
        Lanza una aplicación GUI de forma DESPRENDIDA (como un `run` en terminal).

        Estrategia:
        1. Si hay un ejecutable en el PATH → se ejecuta directamente.
        2. Si no, pero existe un .desktop → se usa `gtk-launch`.
        3. Se lanza con `setsid` y la sesión gráfica heredada para que la
           ventana sobreviva y se vea realmente.
        """
        app_name = (app_name or "").strip()
        if not app_name:
            return CommandResult(False, "", "Sin nombre de aplicación", 1, 0.0, "")
        args = [self._sanitize(a) for a in (arguments or [])]
        start = time.time()

        binary = shutil.which(app_name)
        if binary:
            cmd = " ".join([shlex.quote(binary)] + [shlex.quote(a) for a in args])
        elif self._desktop_exists(app_name):
            cmd = f"gtk-launch {shlex.quote(app_name)}" + (
                " " + " ".join(shlex.quote(a) for a in args) if args else "")
        else:
            return CommandResult(False, "",
                                 f"Aplicación no encontrada: {app_name}",
                                 1, time.time() - start, app_name)

        # `setsid … &` desacopla el proceso del backend (no muere al terminar).
        launcher = f"setsid {cmd} </dev/null >/dev/null 2>&1 &"
        try:
            proc = await asyncio.create_subprocess_shell(
                launcher, env=self._session_env(), start_new_session=True,
            )
            logger.info("🚀 Lanzada app %s → %s (wrapper pid %s)", app_name, cmd, proc.pid)
            return CommandResult(True, f"Lanzado: {app_name}", "", 0,
                                 time.time() - start, cmd)
        except Exception as exc:  # noqa: BLE001
            return CommandResult(False, "", f"Error lanzando: {exc}", -1,
                                 time.time() - start, cmd)

    # ── Información del sistema ────────────────────────────────────────────
    async def get_system_info(self) -> Dict[str, Any]:
        """Recopila datos básicos del equipo usando comandos seguros."""
        hostname = (await self.execute_safe_command("hostname")).output
        username = (await self.execute_safe_command("whoami")).output
        return {
            "os_name": platform.system(),
            "os_version": platform.release(),
            "architecture": platform.machine(),
            "cpu_count": os.cpu_count() or 1,
            "username": username,
            "hostname": hostname,
        }

    def get_stats(self) -> Dict[str, Any]:
        return dict(self.stats)

    def cleanup(self) -> None:
        self._apps_cache = None
        logger.info("🧹 OSController limpiado")
