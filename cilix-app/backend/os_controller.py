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
import json
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
            "lspci": CommandSafety.SAFE, "lsblk": CommandSafety.SAFE,
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

    # Cache de apps Flatpak instaladas (evita invocar `flatpak list` en cada lance).
    _flatpak_cache: tuple = (0.0, [])          # (ts, [(appid, nombre)])

    async def _flatpak_app_id(self, name: str) -> Optional[str]:
        """Busca una app Flatpak por id o nombre ('leocad' → org.leocad.LeoCAD)."""
        cls = type(self)
        if time.time() - cls._flatpak_cache[0] > 300:      # refresca cada 5 min
            apps = []
            try:
                proc = await asyncio.create_subprocess_exec(
                    "flatpak", "list", "--app", "--columns=application,name",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL)
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
                for line in out.decode(errors="ignore").splitlines():
                    appid, _, appname = line.partition("\t")
                    if appid.strip():
                        apps.append((appid.strip(), appname.strip()))
            except Exception as exc:  # noqa: BLE001
                logger.debug("flatpak list falló: %r", exc)
                return None
            cls._flatpak_cache = (time.time(), apps)
        needle = name.lower().replace(" ", "").replace("-", "")
        for appid, appname in cls._flatpak_cache[1]:
            parts = [p for p in appid.lower().split(".") if p]
            if (needle in parts or needle == appid.lower()
                    or needle == appname.lower().replace(" ", "").replace("-", "")):
                return appid
        return None

    async def mount_usb(self, hint: str = "") -> CommandResult:
        """Monta (si hace falta) un USB/pendrive y lo abre en el gestor de
        archivos. `hint` es una pista de etiqueta ('ventoy'). Sin privilegios:
        usa udisksctl, que monta como el usuario de sesión."""
        start = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                "lsblk", "-J", "-o", "NAME,LABEL,MOUNTPOINT,FSTYPE,TYPE,RM",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
            devices = json.loads(out.decode(errors="ignore")).get("blockdevices", [])
        except Exception as exc:  # noqa: BLE001
            return CommandResult(False, "", f"No pude inspeccionar los discos: {exc}",
                                 1, time.time() - start, "lsblk")

        # Candidatos: particiones/medas extraíbles con etiqueta o sistema de archivos
        parts = []
        for d in devices:
            for p in (d.get("children") or []) + [d]:
                if p.get("type") not in ("part", "disk"):
                    continue
                fst = (p.get("fstype") or "").strip()
                lbl = (p.get("label") or "").strip()
                if fst == "swap" or (not lbl and not fst):
                    continue
                if str(p.get("rm")) == "1" or lbl or fst in ("vfat", "exfat", "ntfs", "udf", "iso9660"):
                    parts.append(p)
        if hint:
            pref = [p for p in parts
                    if hint.lower() in ((p.get("label") or "") + (p.get("name") or "")).lower()]
            parts = pref or parts
        if not parts:
            return CommandResult(False, "",
                                 "No encontré ningún USB/pendrive conectado",
                                 1, time.time() - start, "lsblk")

        target = next((p for p in parts if not p.get("mountpoint")), parts[0])
        mountpoint = target.get("mountpoint")
        name = target.get("name") or ""
        label = (target.get("label") or name).strip()

        if not mountpoint:                                  # desmontado → montar
            try:
                proc = await asyncio.create_subprocess_exec(
                    "udisksctl", "mount", "-b", f"/dev/{name}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT)
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
                text = out.decode(errors="ignore")
                m = re.search(r"Mounted at (\S+)", text)
                if m:
                    mountpoint = m.group(1)
                else:
                    # El escritorio (GNOME/udisks) pudo montarlo casi a la vez:
                    # udisksctl responde AlreadyMounted → lo consideramos éxito.
                    m = re.search(r"already mounted at `([^']+)`", text)
                    if m:
                        mountpoint = m.group(1)
            except Exception as exc:  # noqa: BLE001
                logger.warning("udisksctl mount falló: %r", exc)
            if not mountpoint:
                return CommandResult(False, "",
                                     f"No pude montar /dev/{name} (¿protección de escritura?)",
                                     1, time.time() - start, "udisksctl")

        # Abrirlo en el gestor de archivos con el entorno de la sesión gráfica
        launcher = f"setsid xdg-open {shlex.quote(mountpoint)} </dev/null >/dev/null 2>&1 &"
        try:
            await asyncio.create_subprocess_shell(
                launcher, env=self._session_env(), start_new_session=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("xdg-open usb falló: %r", exc)

        return CommandResult(True, f"«{label}» está montado en {mountpoint}", "",
                             0, time.time() - start, "udisksctl")

    # Plantillas de arranque para "crea un archivo X.html" (Ri las escribe sin
    # pasar por el shell; el LLM no necesita generar cientos de líneas).
    _CODE_TEMPLATES = {
        "html": """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>%TITLE%</title>
  <style>
    :root { --acento: #2dd4bf; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #0f172a;
           color: #e2e8f0; display: grid; place-items: center; min-height: 100vh; }
    .tarjeta { background: #1e293b; padding: 2rem 3rem; border-radius: 1rem;
               box-shadow: 0 10px 30px rgba(0,0,0,.4); text-align: center; }
    button { margin-top: 1rem; padding: .6rem 1.4rem; border: 0; border-radius: .6rem;
             background: var(--acento); color: #04222b; font-weight: 700; cursor: pointer; }
  </style>
</head>
<body>
  <main class="tarjeta">
    <h1>%TITLE%</h1>
    <p style="margin-top:.5rem">Página inicial creada por Ri</p>
    <button onclick="saludar()">Púlsame</button>
  </main>
  <script>
    function saludar() {
      alert('¡Hola desde %TITLE%!');
    }
  </script>
</body>
</html>
""",
        "py": '"""%TITLE% · creado por Ri."""\n\n\ndef main():\n    print("Hola desde %TITLE%")\n\n\nif __name__ == "__main__":\n    main()\n',
        "js": "// %TITLE% · creado por Ri\n'use strict';\n\nfunction main() {\n  console.log('Hola desde %TITLE%');\n}\n\nmain();\n",
        "css": "/* %TITLE% · creado por Ri */\n:root {\n  --acento: #2dd4bf;\n}\n\n* { box-sizing: border-box; margin: 0; padding: 0; }\n\nbody {\n  font-family: system-ui, sans-serif;\n}\n",
        "json": '{\n  "nombre": "%TITLE%",\n  "elementos": []\n}\n',
        "md": "# %TITLE%\n\nCreado por Ri.\n",
        "sh": "#!/usr/bin/env bash\n# %TITLE% · creado por Ri\nset -euo pipefail\n\necho \"Hola desde %TITLE%\"\n",
    }

    async def create_code_file(self, name: str, lines: int = 0) -> CommandResult:
        """Crea un archivo de código con plantilla en ~/Documents/cilix y lo abre.
        Si `lines` supera la plantilla, la rellena con bloques de comentario
        válidos para el lenguaje (así "que tenga 300 líneas" es literal)."""
        start = time.time()
        safe = re.sub(r"[^A-Za-z0-9._-]", "", (name or "").strip())
        if "." not in safe or safe.startswith("."):
            return CommandResult(False, "", "Nombre de archivo no válido", 1,
                                 time.time() - start, name)
        stem, _, ext = safe.rpartition(".")
        ext = ext.lower()
        base = os.path.expanduser("~/Documents/cilix")
        try:
            os.makedirs(base, exist_ok=True)
            path = os.path.join(base, f"{stem}.{ext}")
            n = 1
            while os.path.exists(path):              # nunca sobrescribir
                n += 1
                path = os.path.join(base, f"{stem}-{n}.{ext}")
            plantilla = self._CODE_TEMPLATES.get(ext) or "// %TITLE% · creado por Ri\n"
            contenido = plantilla.replace("%TITLE%", stem)
            # Rellenar hasta el número de líneas pedido (tope 500, no saturar RAM).
            target = max(0, min(int(lines or 0), 500))
            if ext not in ("json", "") and target > contenido.count("\n") + 1:
                if ext in ("py", "sh"):
                    _fmt = "# Bloque {i} de {t} · añade aquí tu código\n"
                elif ext in ("html", "md"):
                    _fmt = "<!-- Bloque {i} de {t} · añade aquí tu contenido -->\n"
                elif ext == "txt":
                    _fmt = "Bloque {i} de {t}\n"
                else:
                    _fmt = "// Bloque {i} de {t} · añade aquí tu código\n"
                while contenido.count("\n") + 1 < target:
                    contenido += _fmt.format(i=contenido.count("\n") + 1, t=target)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(contenido)
            lineas = contenido.count("\n") + (0 if contenido.endswith("\n") else 1)
            # Abrirlo con la app por defecto (navegador/editor) de la sesión gráfica
            launcher = f"setsid xdg-open {shlex.quote(path)} </dev/null >/dev/null 2>&1 &"
            try:
                await asyncio.create_subprocess_shell(
                    launcher, env=self._session_env(), start_new_session=True)
            except Exception as exc:  # noqa: BLE001
                logger.debug("xdg-open archivo falló: %r", exc)
            return CommandResult(True,
                                 f"{path} · {lineas} líneas (plantilla lista para editar)",
                                 "", 0, time.time() - start, "writefile")
        except Exception as exc:  # noqa: BLE001
            return CommandResult(False, "", f"No pude escribir el archivo: {exc}",
                                 1, time.time() - start, "writefile")

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

    # Emuladores de terminal conocidos, en orden de preferencia. El sistema
    # puede no tener gnome-terminal (Pop!_OS/Debian/Arch varían), así que
    # 'abre la terminal' resuelve el primero que realmente esté instalado.
    TERMINAL_CANDIDATES = (
        "gnome-terminal", "konsole", "xfce4-terminal", "tilix", "terminator",
        "alacritty", "kitty", "deepin-terminal", "mate-terminal", "lxterminal",
        "xterm",
    )
    _TERMINAL_ALIASES = ("terminal", "consola", "x-terminal-emulator", "shell")

    def _resolve_terminal(self, app_name: str) -> str:
        """Devuelve el primer emulador de terminal disponible si piden 'la
        terminal' (o un terminal concreto que no está instalado)."""
        low = (app_name or "").lower()
        is_terminal = low in self._TERMINAL_ALIASES or low in self.TERMINAL_CANDIDATES
        if not is_terminal:
            return app_name
        # Si pidieron un terminal concreto y SÍ existe, respetarlo.
        if low not in self._TERMINAL_ALIASES and shutil.which(app_name):
            return app_name
        for cand in self.TERMINAL_CANDIDATES:
            if shutil.which(cand):
                logger.info("🖥️ terminal → usando %s", cand)
                return cand
        return app_name  # ninguno disponible: deja el mensaje de error original

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

        # Resolver 'la terminal' al emulador realmente instalado en el sistema.
        app_name = self._resolve_terminal(app_name)

        binary = shutil.which(app_name)
        if binary:
            cmd = " ".join([shlex.quote(binary)] + [shlex.quote(a) for a in args])
        elif self._desktop_exists(app_name):
            cmd = f"gtk-launch {shlex.quote(app_name)}" + (
                " " + " ".join(shlex.quote(a) for a in args) if args else "")
        else:
            # 3er intento: app Flatpak (ej. 'leocad' → org.leocad.LeoCAD); no
            # están en PATH y su .desktop vive en exports, así que se busca
            # por id o nombre entre las apps instaladas.
            flat_id = await self._flatpak_app_id(app_name)
            if flat_id:
                cmd = f"flatpak run {shlex.quote(flat_id)}" + (
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
