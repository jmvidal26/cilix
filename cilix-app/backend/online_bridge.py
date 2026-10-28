#!/usr/bin/env python3
"""
Módulo OnlineBridge — Cilix en modo ONLINE contra OpenCode
==========================================================
Cilix deja de llamar a una API de IA externa y pasa a usar el **servidor local
de OpenCode** (`opencode serve`) como cerebro:

    Cilix (FastAPI) --HTTP local--> OpenCode (/api/session/.../generate)

Por qué así y no "MCP": MCP es un protocolo de HERRAMIENTAS (el cliente IA
llama a servidores MCP), no un transporte de LLM. El papel correcto es:
  · `mcp_server.py`  → Cilix se expone como servidor MCP (cuerpo/voz).
  · `online_bridge.py` → Cilix consume el cerebro de OpenCode por su API local.

Ventajas: no hay API de pago, no hay otro proveedor, se reutiliza el modelo y
la sesión que ya tienes abiertos en OpenCode, y la personalidad de Ri se sigue
inyectando desde `core_ia.py`.

Notas de implementación:
  · El servidor de OpenCode exige Basic auth: usuario `opencode` + el
    `password` que hay en ~/.config/opencode/service.json.
  · La URL se descubre con `opencode service status` (o CILIX_OPENCODE_URL).
  · El endpoint `/generate` es síncrono y NO ejecuta herramientas: devuelve
    solo texto. Es justo lo que necesita el path de voz (seguro por diseño).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Ruta del secreto del servicio local de OpenCode.
SERVICE_JSON = Path(
    os.getenv("OPENCODE_CONFIG", str(Path.home() / ".config" / "opencode"))
) / "service.json"


class OpenCodeUnavailable(RuntimeError):
    """El servidor de OpenCode no responde o no tiene sesión utilizable."""


class OpenCodeBridge:
    """Cliente mínimo del servidor local de OpenCode (API v2)."""

    def __init__(
        self,
        url: Optional[str] = None,
        password: Optional[str] = None,
        session_title: str = "Cilix · voz",
        timeout: float = 120.0,
        model: Optional[str] = None,
    ) -> None:
        self._url = (url or "").rstrip("/")
        self._password = password or ""
        self.session_title = session_title
        self.timeout = timeout
        self.model = model
        self.session_id: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        # Último error legible (para mostrarlo en /health y en la UI).
        self.last_error: str = ""

    # ── Descubrimiento ─────────────────────────────────────────────────────
    async def discover(self) -> bool:
        """Localiza URL + password del servicio. Devuelve True si hay ambos."""
        if not self._password:
            self._password = self._read_password()
        if not self._url:
            self._url = await self._discover_url()
        ok = bool(self._url and self._password)
        if not ok:
            self.last_error = (
                "OpenCode no está arrancado o falta ~/.config/opencode/service.json"
            )
            logger.warning("🌐 OnlineBridge sin servicio: %s", self.last_error)
        else:
            logger.info("🌐 OnlineBridge → %s", self._url)
        return ok

    @staticmethod
    def _read_password() -> str:
        """Lee el password del servicio desde service.json (0600)."""
        try:
            data = json.loads(SERVICE_JSON.read_text(encoding="utf-8"))
            return str(data.get("password") or "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo leer %s: %r", SERVICE_JSON, exc)
            return ""

    @staticmethod
    async def _discover_url() -> str:
        """Pregunta al CLI por la URL del servicio en segundo plano."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "opencode", "service", "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            for line in reversed((out or b"").decode(errors="ignore").splitlines()):
                line = line.strip()
                if line.startswith("http://") or line.startswith("https://"):
                    return line.rstrip("/")
        except Exception as exc:  # noqa: BLE001
            logger.debug("opencode service status falló: %r", exc)
        return ""

    # ── HTTP ───────────────────────────────────────────────────────────────
    def _auth(self) -> Dict[str, str]:
        token = base64.b64encode(f"opencode:{self._password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
                headers=self._auth(),
            )
        return self._client

    async def _get(self, path: str) -> Any:
        r = await self._http().get(f"{self._url}{path}")
        if r.status_code == 401:
            raise OpenCodeUnavailable("OpenCode rechazó la autenticación (password)")
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, payload: Dict[str, Any]) -> Any:
        r = await self._http().post(f"{self._url}{path}", json=payload)
        if r.status_code == 401:
            raise OpenCodeUnavailable("OpenCode rechazó la autenticación (password)")
        if r.status_code == 404:
            # Sesión borrada desde la TUI: se recrea en el siguiente intento.
            self.session_id = None
            raise OpenCodeUnavailable("La sesión de OpenCode ya no existe")
        if r.status_code >= 400:
            raise OpenCodeUnavailable(f"OpenCode {r.status_code}: {r.text[:200]}")
        return r.json()

    # ── Sesión ─────────────────────────────────────────────────────────────
    async def ensure_session(self) -> str:
        """Devuelve el id de la sesión dedicada de Cilix (la crea si falta)."""
        if self.session_id:
            return self.session_id
        # Si falta URL O password hay que descubrir (antes, con URL puesta y
        # password vacío, se llamaba a la API sin autenticación y fallaba 401).
        if not (self._url and self._password):
            if not await self.discover():
                raise OpenCodeUnavailable(self.last_error)

        data = await self._get("/api/session")
        sessions: List[Dict[str, Any]] = data.get("data", data) or []
        for s in sessions:
            if s.get("title") == self.session_title:
                self.session_id = s.get("id")
                logger.info("🌐 Sesión de OpenCode reutilizada: %s", self.session_id)
                return self.session_id

        payload: Dict[str, Any] = {"title": self.session_title}
        if self.model:
            provider, _, model_id = self.model.partition("/")
            if provider and model_id:
                payload["model"] = {"providerID": provider, "id": model_id}
        created = await self._post("/api/session", payload)
        self.session_id = (created.get("data") or {}).get("id")
        if not self.session_id:
            raise OpenCodeUnavailable("OpenCode no devolvió id de sesión")
        logger.info("🌐 Sesión de OpenCode creada: %s", self.session_id)
        return self.session_id

    # ── Inferencia ─────────────────────────────────────────────────────────
    async def generate(self, prompt: str) -> str:
        """Pide una respuesta al cerebro de OpenCode y devuelve el texto.

        Usa `/generate` (one-shot, SIN herramientas) a propósito: el texto va
        directo a TTS, así que no queremos que el modelo ejecute comandos por
        su cuenta desde el path de voz.
        """
        sid = await self.ensure_session()
        try:
            data = await self._post(f"/api/session/{sid}/generate", {"prompt": prompt})
        except OpenCodeUnavailable:
            # Un reintento: la sesión pudo borrarse y ensure_session la recrea.
            sid = await self.ensure_session()
            data = await self._post(f"/api/session/{sid}/generate", {"prompt": prompt})
        text = ((data or {}).get("data") or {}).get("text", "")
        if not text.strip():
            raise OpenCodeUnavailable("OpenCode devolvió una respuesta vacía")
        return text.strip()

    async def health(self) -> Dict[str, Any]:
        """Estado del puente para /health y para el indicador de la UI."""
        if not (self._url and self._password):
            await self.discover()
        if not (self._url and self._password):
            return {"online": False, "error": self.last_error, "url": self._url}
        try:
            info = await self._get("/api/info")
            return {
                "online": True,
                "url": self._url,
                "version": (info.get("data") or info or {}).get("version"),
                "session": self.session_id,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            return {"online": False, "url": self._url, "error": self.last_error}

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()


# ── Prueba manual: python online_bridge.py "hola" ──────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    prompt = " ".join(sys.argv[1:]) or "Preséntate en una frase."

    async def _main() -> None:
        bridge = OpenCodeBridge()
        print(await bridge.health())
        print("→", await bridge.generate(prompt))
        await bridge.close()

    asyncio.run(_main())
