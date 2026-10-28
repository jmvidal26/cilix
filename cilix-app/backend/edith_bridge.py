#!/usr/bin/env python3
"""
Puente Cilix ↔ E.D.I.T.H (Le'fil)
=================================
Permite que Cilix ejecute el módulo E.D.I.T.H del repositorio Le'fil sin
cargarlo en su propio proceso: lanza `scripts/edith_bridge.py` como
subproceso, recibe un JSON y lo convierte en una frase hablada.

Ventajas de hacerlo así:
· RAM: E.D.I.T.H (y su analizador) viven en el subproceso, que muere al
  terminar. Cilix no importa numpy/opencv ni modelos extra.
· Aislamiento: un fallo de E.D.I.T.H no tumba el backend de Cilix.
· Seguridad: el subproceso solo expone acciones concretas (status, devices,
  scan, pentest), nunca una shell libre.

Configuración:
    CILIX_EDITH_DIR      ruta del repo Le'fil (por defecto ~/partes/Le-fil)
    CILIX_EDITH_TIMEOUT  segundos máximos por acción (por defecto 180)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

DEFAULT_TIMEOUT = float(os.getenv("CILIX_EDITH_TIMEOUT", "180"))

IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EDITH_RE = re.compile(r"\bedith\b|\be\.d\.i\.t\.h\b")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _python_for_edith() -> str:
    """Intérprete para el puente de E.D.I.T.H.

    El venv de Cilix no trae `requests` (lo importa la cadena de E.D.I.T.H),
    así que se prefiere el Python del sistema, que es con el que corre Le'fil.
    """
    explicit = os.getenv("CILIX_EDITH_PYTHON")
    if explicit and Path(explicit).is_file():
        return explicit
    system_python = Path("/usr/bin/python3")
    # Dentro de un venv, sys.executable apunta al enlace del venv (sin los
    # paquetes del sistema): se usa el Python base, que sí tiene `requests`.
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if system_python.is_file() and in_venv:
        return str(system_python)
    return sys.executable


def _find_repo() -> Optional[Path]:
    candidates = []
    env = os.getenv("CILIX_EDITH_DIR")
    if env:
        candidates.append(Path(env).expanduser())
    candidates += [
        Path.home() / "partes" / "Le-fil",
        Path.home() / "Le-fil",
        Path.home() / "le-fil",
        Path.home() / "Documents" / "Le-fil",
    ]
    for candidate in candidates:
        try:
            if (candidate / "scripts" / "edith_bridge.py").is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


class EdithBridge:
    """Cliente local de E.D.I.T.H para Cilix."""

    def __init__(self) -> None:
        self.repo = _find_repo()
        self.script = (self.repo / "scripts" / "edith_bridge.py") if self.repo else None
        self.timeout = DEFAULT_TIMEOUT
        self.python = _python_for_edith()
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self.script is not None and self.script.is_file()

    # ── detección de intención ──────────────────────────────────────────
    @staticmethod
    def interpret(text: str) -> Optional[Tuple[str, Optional[str]]]:
        """Devuelve (acción, objetivo) si el mensaje va dirigido a E.D.I.T.H."""
        raw = (text or "").strip()
        if not raw:
            return None
        low = _norm(raw)
        ip_match = IP_RE.search(raw)
        ip = ip_match.group(0) if ip_match else None
        speaks_edith = bool(EDITH_RE.search(low))

        # Pentest: exige la palabra explícita (es la acción más intrusiva).
        if re.search(r"\bpentest\b|\bprueba de penetracion\b|\bpenetracion\b", low):
            return ("pentest", ip)

        if speaks_edith:
            if re.search(r"\b(estado|status|esta lista|funciona|como va|salud)\b", low):
                return ("status", None)
            if re.search(r"\b(dispositivo|dispositivos|equipos|quien|arp|conectad)\w*", low):
                return ("devices", None)
            if re.search(r"\b(escanea|escanear|escaneo|barrido|scan|analiza la red)\b", low):
                return ("scan", None)
            return ("status", None)

        # Sin la palabra "edith", solo frases inequívocas de red.
        if re.search(r"\b(escanea|escanear|escaneo|barrido)\b", low) and \
           re.search(r"\b(red|red local|lan|subred)\b", low):
            return ("scan", None)
        if re.search(r"\bquien(es)? (esta|estan|hay)\b", low) and "red" in low:
            return ("devices", None)
        return None

    # ── ejecución ──────────────────────────────────────────────────────
    async def run(self, action: str, target: Optional[str] = None,
                  timeout: Optional[float] = None) -> Dict[str, Any]:
        if not self.available:
            return {"ok": False, "action": action,
                    "error": "No encuentro el repo Le'fil (scripts/edith_bridge.py)."}
        if action == "pentest" and not target:
            return {"ok": False, "action": action,
                    "error": "Dime la IP privada del objetivo (p. ej. 192.168.1.10)."}

        cmd = [self.python, str(self.script), action]
        if action == "pentest" and target:
            cmd.append(target)

        limit = self.timeout if timeout is None else timeout
        async with self._lock:  # una acción de E.D.I.T.H a la vez
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.repo),
                )
                try:
                    out, err = await asyncio.wait_for(proc.communicate(), timeout=limit)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    return {"ok": False, "action": action,
                            "error": f"E.D.I.T.H tardó más de {int(limit)} s."}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "action": action,
                        "error": f"No pude lanzar E.D.I.T.H: {exc}"}

        text = (out or b"").decode("utf-8", "replace").strip()
        if not text:
            detail = (err or b"").decode("utf-8", "replace").strip()[:200]
            return {"ok": False, "action": action,
                    "error": detail or "E.D.I.T.H no devolvió nada."}
        try:
            return json.loads(text.splitlines()[-1])
        except json.JSONDecodeError:
            return {"ok": False, "action": action,
                    "error": f"Respuesta ilegible de E.D.I.T.H: {text[:160]}"}

    # ── formato hablado ────────────────────────────────────────────────
    @staticmethod
    def _label(dev: Dict[str, Any]) -> str:
        ip = str(dev.get("ip") or "").strip()
        host = str(dev.get("hostname") or "").strip()
        os_name = str(dev.get("os") or "").strip()
        if host and host != ip:
            return host
        if os_name and os_name.lower() not in ("unknown", "desconocido"):
            return os_name
        return "sin identificar"
    @staticmethod
    def format_reply(action: str, data: Dict[str, Any]) -> str:
        if not data.get("ok"):
            return f"E.D.I.T.H no pudo hacerlo: {data.get('error', 'error desconocido')}"

        if action == "status":
            nets = ", ".join(data.get("subnets") or []) or "sin subredes"
            ollama = "con Ollama conectado" if data.get("ollama") else "sin Ollama"
            return (f"E.D.I.T.H está operativa, {ollama}. "
                    f"Conozco {data.get('devices_known', 0)} dispositivo(s) en {nets}. "
                    f"Último informe: {Path(data.get('last_report') or 'ninguno').name}.")

        if action == "devices":
            items = data.get("devices") or []
            if not items:
                return "E.D.I.T.H no ve dispositivos en la tabla ARP ahora mismo."
            parts = []
            for dev in items[:4]:
                label = EdithBridge._label(dev)
                parts.append(f"{dev.get('ip')} ({label})")
            extra = "" if len(items) <= 4 else f" y {len(items) - 4} más"
            return f"E.D.I.T.H ve {len(items)} dispositivo(s): " + ", ".join(parts) + extra + "."

        if action == "scan":
            items = data.get("devices") or []
            secs = data.get("seconds", "?")
            if not items:
                return f"Barrido terminado en {secs} s sin dispositivos nuevos."
            parts = [f"{d.get('ip')} ({EdithBridge._label(d)})" for d in items[:4]]
            extra = "" if len(items) <= 4 else f" y {len(items) - 4} más"
            return (f"Barrido terminado en {secs} s: {data.get('total', len(items))} "
                    f"dispositivo(s). " + ", ".join(parts) + extra + ".")

        if action == "pentest":
            report = Path(data.get("report") or "").name or "sin informe"
            brain = "con analizador" if data.get("analyzer") else "sin analizador"
            return (f"Pentest a {data.get('target')} terminado en {data.get('seconds')} s "
                    f"({brain}). Informe: {report}.")

        return "E.D.I.T.H terminó la tarea."


bridge = EdithBridge()
