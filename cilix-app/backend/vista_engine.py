#!/usr/bin/env python3
"""
Módulo de Percepción de Cilix — VistaEngine
===========================================
Percepción del entorno de escritorio en Linux (Pop!_OS):

· Ventana activa : título, clase WM_CLASS y geometría vía `xdotool` / `wmctrl`
                   (nativo de X11/Wayland-XWayland), sin librerías pesadas.
· Captura de pantalla : opcional, vía `gnome-screenshot`/`maim`/`import`.
· Presence/motion (opcional) : si OpenCV y una cámara están disponibles.

Diseñado para CONSUMO MÍNIMO: el monitoreo de ventana es barato; la cámara y
la captura están desactivadas por defecto para proteger los 8 GB de RAM.
"""

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import cv2  # opcional: solo para presencia por cámara
    CV2_AVAILABLE = True
except Exception:  # noqa: BLE001
    CV2_AVAILABLE = False


@dataclass
class VisionConfig:
    """Parámetros del motor de visión."""
    window_check_interval: float = 2.0
    window_title_max_length: int = 80
    camera_index: int = 0
    camera_resolution: tuple = (320, 240)
    camera_fps: int = 2                 # muy bajo: ahorro de CPU/RAM
    motion_threshold: float = 10.0
    presence_enabled: bool = False      # OFF por defecto (RAM)


class VistaEngine:
    """Percepción del escritorio: ventana activa + captura + presencia."""

    def __init__(self, config: Optional[VisionConfig] = None):
        self.config = config or VisionConfig()
        self.is_active = False
        self.camera: Optional[Any] = None
        self.face_cascade: Optional[Any] = None
        self.last_frame = None
        self.active_window_info: Dict[str, Any] = {}
        self.background_tasks: set = set()

        # Herramientas de sistema disponibles
        self.has_xdotool = shutil.which("xdotool") is not None
        self.has_wmctrl = shutil.which("wmctrl") is not None

        logger.info(
            "👁️ VistaEngine (xdotool=%s, wmctrl=%s, cv2=%s)",
            self.has_xdotool, self.has_wmctrl, CV2_AVAILABLE,
        )

    async def initialize(self) -> bool:
        """Prepara los componentes de percepción disponibles."""
        try:
            window_ok = self.has_xdotool or self.has_wmctrl
            if not window_ok:
                logger.warning(
                    "⚠️ Instala xdotool/wmctrl para detección de ventana: "
                    "sudo apt install xdotool wmctrl"
                )
            if self.config.presence_enabled and CV2_AVAILABLE:
                await self._init_camera()

            self.is_active = window_ok or (self.camera is not None)
            if self.is_active:
                logger.info("✅ VistaEngine activo")
            else:
                logger.info("ℹ️ VistaEngine en modo limitado (sin percepción)")
            return self.is_active
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error inicializando VistaEngine: %s", exc)
            return False

    # ── Ventana activa (Linux nativo) ──────────────────────────────────────
    async def get_active_window(self) -> Dict[str, Any]:
        """
        Devuelve información de la ventana activa usando herramientas de X11.

        Estrategia: `xdotool getactivewindow getwindowname` para el título y
        `xprop`/`wmctrl -d`/`xdotool getwindowgeometry` para clase y tamaño.
        """
        info: Dict[str, Any] = {
            "title": "", "app": "", "geometry": {}, "timestamp": time.time(),
        }
        try:
            wid = await self._run("xdotool getactivewindow") if self.has_xdotool else ""
            if wid:
                title = await self._run("xdotool getactivewindow getwindowname")
                info["title"] = (title or "")[: self.config.window_title_max_length]
                geom = await self._run(
                    f"xdotool getwindowgeometry --shell {wid}"
                )
                info["geometry"] = self._parse_geometry(geom)
                cls = await self._run(
                    f"xprop -id {wid} WM_CLASS"
                )
                info["app"] = self._parse_wm_class(cls) or self._guess_app(info["title"])
            elif self.has_wmctrl:
                # Fallback: lista de ventanas y marcar la activa por posición
                lines = await self._run("wmctrl -l -p -x")
                active = await self._run(
                    "xdotool getactivewindow"
                ) if self.has_xdotool else ""
                for line in (lines or "").splitlines():
                    if active and line.split("\t")[0].strip().startswith(active):
                        info["title"] = line[: self.config.window_title_max_length]
                        break

            if info["title"] or info["app"]:
                self.active_window_info = info
            return info
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error obteniendo ventana activa: %s", exc)
            return self.active_window_info

    @staticmethod
    def _parse_geometry(shell_output: str) -> Dict[str, int]:
        """Parsea la salida de `xdotool getwindowgeometry --shell`."""
        out: Dict[str, int] = {}
        for line in (shell_output or "").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                if k in ("X", "Y", "WIDTH", "HEIGHT"):
                    try:
                        out[k.lower()] = int(v)
                    except ValueError:
                        pass
        return out

    @staticmethod
    def _parse_wm_class(xprop_output: str) -> str:
        """Extrae la segunda cadena de `WM_CLASS(...)` como nombre de app."""
        if not xprop_output or "WM_CLASS" not in xprop_output:
            return ""
        import re
        found = re.findall(r'"([^"]+)"', xprop_output)
        return found[-1] if found else ""

    @staticmethod
    def _guess_app(title: str) -> str:
        """Infere la aplicación desde el título cuando no hay WM_CLASS."""
        patterns = {
            "vscode": ["visual studio code", "vscode"],
            "firefox": ["mozilla firefox", "firefox"],
            "chrome": ["google chrome", "chromium"],
            "terminal": ["terminal", "gnome-terminal", "konsole", "xterm"],
            "nautilus": ["files", "nautilus", "archivador"],
            "libreoffice": ["libreoffice", "writer", "calc", "impress"],
        }
        low = (title or "").lower()
        for app, keys in patterns.items():
            if any(k in low for k in keys):
                return app
        return ""

    # ── Captura de pantalla (opcional y ligera) ────────────────────────────
    async def capture_screenshot(self) -> Optional[bytes]:
        """Captura la pantalla si hay una herramienta disponible. Coste alto."""
        for cmd in ("gnome-screenshot -f /tmp/cilix_shot.png",
                    "maim /tmp/cilix_shot.png",
                    "import -window root /tmp/cilix_shot.png"):
            tool = cmd.split()[0]
            if shutil.which(tool):
                await self._run(cmd)
                try:
                    with open("/tmp/cilix_shot.png", "rb") as fh:
                        data = fh.read()
                    return data
                except Exception as exc:  # noqa: BLE001
                    logger.error("❌ Error leyendo captura: %s", exc)
                    return None
        logger.warning("⚠️ Sin herramienta de captura (gnome-screenshot/maim/imagemagick)")
        return None

    # ── Presencia por cámara (opcional) ────────────────────────────────────
    async def _init_camera(self) -> None:
        if not CV2_AVAILABLE:
            return
        try:
            self.camera = cv2.VideoCapture(self.config.camera_index)
            if not self.camera.isOpened():
                self.camera = None
                return
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera_resolution[0])
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera_resolution[1])
            cascade = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.face_cascade = cv2.CascadeClassifier(cascade)
            logger.info("📷 Cámara de presencia activada")
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error init cámara: %s", exc)
            self.camera = None

    def check_user_presence(self) -> bool:
        """Estimación barata de presencia usando la cámara si está activa."""
        if not self.camera or not CV2_AVAILABLE:
            return True  # sin cámara, asumimos presente
        try:
            ret, frame = self.camera.read()
            if not ret:
                return False
            import cv2 as _cv2
            gray = _cv2.cvtColor(frame, _cv2.COLOR_BGR2GRAY)
            if self.last_frame is not None:
                diff = _cv2.absdiff(self.last_frame, gray)
                changed = float(_cv2.countNonZero(diff > 25)) / diff.size
                self.last_frame = gray
                return changed * 100 > self.config.motion_threshold
            self.last_frame = gray
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error presencia: %s", exc)
            return False

    # ── Utilidades async ───────────────────────────────────────────────────
    @staticmethod
    async def _run(cmd: str) -> str:
        """Ejecuta un comando ligero y devuelve stdout (texto)."""
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            return out.decode("utf-8", errors="ignore").strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Comando '%s' falló: %s", cmd, exc)
            return ""

    def get_system_status(self) -> Dict[str, Any]:
        return {
            "active": self.is_active,
            "xdotool": self.has_xdotool,
            "wmctrl": self.has_wmctrl,
            "cv2": CV2_AVAILABLE,
            "presence_enabled": self.config.presence_enabled,
            "camera": self.camera is not None,
            "active_window": self.active_window_info,
        }

    def cleanup(self) -> None:
        """Libera cámara y tareas."""
        try:
            self.is_active = False
            for t in self.background_tasks:
                t.cancel()
            if self.camera is not None and CV2_AVAILABLE:
                self.camera.release()
                self.camera = None
            logger.info("🧹 VistaEngine limpiado")
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error limpiando VistaEngine: %s", exc)
