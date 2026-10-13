"""ClipboardSentinel · vigila el portapapeles y avisa cuando copias errores.

Hilo asínculo ultraligero: sondea el portapapeles cada pocos segundos (X11
vía `xclip`, Wayland vía `wl-paste`; si no hay ninguno, se desactiva solo).
Cuando el contenido NUEVO parece un traceback/error de compilación, llama al
callback (main.py lo conecta al motor proactivo de Ri para ofrecer ayuda).

Coste: un subproceso corto cada 2.5 s comparando un hash; <10 MB. No sube
RAM ni toca el pipeline de IA salvo cuando dispara (con limita de rate).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import time
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("cilix.clipboard")

# Patrones de "esto es un error que merece ayuda" (baratos, sobre texto ya en memoria)
ERROR_PATTERNS = re.compile(
    r"traceback \(most recent call last\)"
    r"|(?:moduleNotFoundError|importerror|syntaxerror|typeerror|valueerror|indexerror|keyerror|attributeerror)"
    r"|undefined reference|segmentation fault|core dumped"
    r"|compilation (?:failed|error)|error: [^\n]{4,}"
    r"|npm ERR|yarn (?:error|EXDEV)"
    r"|E: (?:Could not|Unable)|dpkg: error"
    r"|(?:panic|fatal): [^\n]{4,}"
    r"|non-zero exit status|command not found"
    r"|(?:failed to|cannot open|no such file)[^\n]{4,}",
    re.I,
)

MAX_CLIP_BYTES = 64 * 1024   # no procesar portapapeles enormes (imágenes, CSVs…)
POLL_SECONDS = 2.5
MIN_GAP_SECONDS = 120.0      # como máximo un aviso cada 2 min (no ser pesada)


class ClipboardSentinel:
    def __init__(self, on_error: Callable[[str], Awaitable[None]],
                 poll: float = POLL_SECONDS) -> None:
        self.on_error = on_error
        self.poll = poll
        self._last_hash = ""
        self._last_fire = 0.0
        self._tool: Optional[list] = self._pick_tool()

    @staticmethod
    def _pick_tool() -> Optional[list]:
        """Comando de lectura de portapapeles según el entorno del usuario."""
        if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
            return ["wl-paste", "-n", "--no-newline"]
        if os.environ.get("DISPLAY") and shutil.which("xclip"):
            return ["xclip", "-selection", "clipboard", "-o"]
        if os.environ.get("DISPLAY") and shutil.which("xsel"):
            return ["xsel", "-b", "-o"]
        return None

    async def run(self) -> None:
        """Bucle principal (lanzar con _spawn). Silencioso si no hay tool."""
        if self._tool is None:
            logger.info("📋 ClipboardSentinel sin xclip/wl-paste → desactivado")
            return
        logger.info("📋 ClipboardSentinel activo (%s)", " ".join(self._tool))
        # Arranca con el contenido actual: no re-avisar lo ya copiado
        self._last_hash = hashlib.sha1(
            (await self._read() or "").encode("utf-8", "ignore")).hexdigest()
        while True:
            try:
                await asyncio.sleep(self.poll)
                text = await self._read()
                if text is None:
                    continue
                h = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()
                if h == self._last_hash:
                    continue                      # sin cambios
                self._last_hash = h
                if len(text) > MAX_CLIP_BYTES:
                    continue
                now = time.time()
                if now - self._last_fire < MIN_GAP_SECONDS:
                    continue                      # rate-limit de pesadez
                if ERROR_PATTERNS.search(text):
                    self._last_fire = now
                    snippet = text[:400]
                    logger.info("📋 Error detectado en portapapeles → Ri ofrece ayuda")
                    await self.on_error(snippet)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug("clipboard sentinel: %r", exc)
                await asyncio.sleep(10)

    async def _read(self) -> Optional[str]:
        """Lectura no bloqueante del portapapeles (subprocess en thread)."""
        if self._tool is None:
            return None
        loop = asyncio.get_running_loop()

        def _run() -> Optional[str]:
            try:
                r = subprocess_run(self._tool)
                return r
            except Exception:  # noqa: BLE000
                return None

        return await loop.run_in_executor(None, _run)


def subprocess_run(cmd: list) -> Optional[str]:
    """Ejecuta la lectura con timeout corto y devuelve texto o None."""
    import subprocess
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=3, text=True)
        if out.returncode == 0:
            return out.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None
