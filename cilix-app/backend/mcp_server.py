#!/usr/bin/env python3
"""
Servidor MCP de Cilix — el "cuerpo" que maneja el agente
========================================================
MCP (Model Context Protocol) sirve para que un cliente de IA (OpenCode, Claude
Desktop, etc.) llame HERRAMIENTAS. No es un transporte de LLM. Por eso Cilix se
expone aquí como servidor MCP y el agente decide cuándo hablar por ella:

    Agente (OpenCode) ──MCP stdio──> este servidor ──HTTP──> Cilix (8765)

Herramientas expuestas:
  · cilix_say       → Cilix dice algo en voz alta (TTS + globo + emoción)
  · cilix_emotion   → cambia la cara del avatar sin hablar
  · cilix_ask       → turno de chat completo (devuelve la respuesta)
  · cilix_state     → RAM, ánimo, cerebro activo, conexiones
  · cilix_remember  → guarda un hecho del usuario en la memoria persistente
  · cilix_history   → últimos mensajes de la conversación
  · cilix_code      → delega una tarea de programación a Antigravity/Qoder

Arranque manual (para depurar):  ../.venv/bin/python mcp_server.py
Registro en OpenCode:            opencode mcp add cilix --global -- <ruta>/python <ruta>/mcp_server.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from mcp.server.mcpserver import MCPServer

# El backend de Cilix puede vivir en otro puerto (CILIX_PORT).
BASE_URL = os.getenv("CILIX_URL", "http://127.0.0.1:8765").rstrip("/")
TIMEOUT = float(os.getenv("CILIX_MCP_TIMEOUT", "180"))
PERSONA_PATH = Path(__file__).resolve().parent.parent / "config" / "persona.json"

server = MCPServer(
    name="cilix",
    title="Cilix — asistente VTuber de escritorio",
    instructions=(
        "Cilix es un avatar Live2D que vive en el escritorio del usuario: habla "
        "con TTS, pone caras y recuerda hechos. Usa `cilix_say` para que diga "
        "algo en voz alta, `cilix_emotion` para gesticular y `cilix_ask` cuando "
        "quieras que responda con su propia personalidad y memoria. El texto que "
        "le pases debe ser hablado (1-3 frases, sin markdown)."
    ),
    version="1.0.0",
)


def _err(exc: Exception) -> str:
    return (f"No pude contactar con Cilix en {BASE_URL}. "
            f"¿Está arrancado (./run.sh)? Detalle: {exc!r}")


async def _post(path: str, payload: Dict[str, Any],
                timeout: Optional[float] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout or TIMEOUT) as client:
        r = await client.post(f"{BASE_URL}{path}", json=payload)
        r.raise_for_status()
        return r.json()


async def _get(path: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{BASE_URL}{path}")
        r.raise_for_status()
        return r.json()


# ── Herramientas ───────────────────────────────────────────────────────────
@server.tool(description="Haz que Cilix diga un texto en voz alta, con emoción.")
async def cilix_say(text: str, emotion: str = "neutral",
                    speak: bool = True) -> str:
    """text: lo que dirá (hablado, sin markdown). emotion: neutral|feliz|triste|
    enfadado|sorprendido|concentrado. speak=False solo muestra el globo."""
    try:
        data = await _post("/api/say", {"text": text, "emotion": emotion,
                                        "speak": speak})
        if not data.get("ok"):
            return f"Cilix no pudo hablar: {data.get('error', 'error desconocido')}"
        return ("Cilix lo dijo en voz alta. " if data.get("spoken")
                else "Cilix lo mostró en pantalla (voz desactivada). ")
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(description="Cambia la expresión del avatar sin que hable.")
async def cilix_emotion(emotion: str) -> str:
    """emotion: neutral|feliz|triste|enfadado|sorprendido|concentrado."""
    try:
        data = await _post("/api/emotion", {"emotion": emotion})
        return f"Expresión cambiada a {data.get('emotion')}."
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(description="Turno de chat completo: Cilix responde con su cerebro.")
async def cilix_ask(text: str, speak: bool = False) -> str:
    """Devuelve la respuesta de Cilix (modo online = OpenCode; si no, Ollama)."""
    try:
        data = await _post("/api/ask", {"text": text, "speak": speak})
        return data.get("response", "(sin respuesta)")
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(description="Estado de Cilix: RAM, ánimo, cerebro y conexiones.")
async def cilix_state() -> str:
    try:
        data = await _get("/api/state")
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(description="Guarda un hecho del usuario en la memoria persistente.")
async def cilix_remember(key: str, value: str) -> str:
    """key: p.ej. user.name, user.likes, user.work. value: el dato."""
    try:
        data = await _post("/api/remember", {"key": key, "value": value})
        return f"Recordado: {data.get('key')} = {data.get('value')}"
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(description="Últimos mensajes de la conversación con Cilix.")
async def cilix_history(limit: int = 10) -> str:
    try:
        data = await _get(f"/history?limit={max(1, min(limit, 50))}")
        msgs = data.get("messages", [])
        if not msgs:
            return "(sin historial)"
        return "\n".join(
            f"[{(m.get('ts') or 0):.0f}] {m.get('role')}: "
            f"{(m.get('content') or '')[:200]}"
            for m in msgs
        )
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ── Herramientas E.D.I.T.H (Le'fil) ────────────────────────────────────────
_EDITH_ACTIONS = {"status", "devices", "scan", "pentest"}


@server.tool(description="E.D.I.T.H (Le'fil): estado, dispositivos, escaneo de red o pentest.")
async def edith(action: str = "status", target: str = "") -> str:
    """action: status | devices | scan | pentest. target: IP privada para pentest."""
    if action not in _EDITH_ACTIONS:
        return f"Acción no válida: {action}. Usa {', '.join(sorted(_EDITH_ACTIONS))}."
    try:
        from edith_bridge import bridge as _bridge
    except Exception as exc:  # noqa: BLE001
        return f"No pude cargar el puente de E.D.I.T.H: {exc}"
    data = await _bridge.run(action, target or None)
    return json.dumps(data, ensure_ascii=False, indent=2)


@server.tool(description="Delega una tarea de programación a Antigravity CLI o Qoder CLI.")
async def cilix_code(task: str, workspace: str = "", mode: str = "",
                     speak: bool = False) -> str:
    """task: qué programar. workspace: carpeta del proyecto (vacío = la de
    Cilix). mode: plan | accept-edits. Devuelve el resumen del agente."""
    timeout = float(os.getenv("CILIX_CODER_TIMEOUT", "600")) + 30
    try:
        data = await _post(
            "/api/coder",
            {"task": task, "workspace": workspace, "mode": mode,
             "speak": speak},
            timeout=timeout,
        )
        return data.get("reply", "(sin respuesta)")
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(description="Estado del puente de programación de Cilix.")
async def cilix_coder_status() -> str:
    try:
        data = await _get("/api/coder")
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@server.tool(description="Cilix curiosea: busca un tema random en la web y lo vuelve parte de su personalidad.")
async def cilix_curiosity(topic: str = "", speak: bool = False) -> str:
    """topic vacío = tema al azar. Devuelve el hallazgo y su nueva opinión."""
    try:
        data = await _post("/api/curiosity", {"topic": topic, "speak": speak})
        return data.get("reply", "(sin respuesta)")
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


# ── Recursos (lectura de contexto) ─────────────────────────────────────────
@server.resource("cilix://persona", description="Ficha de personalidad de Cilix")
def persona_resource() -> str:
    try:
        return PERSONA_PATH.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return "{}"


@server.resource("cilix://state", description="Estado en vivo de Cilix")
async def state_resource() -> str:
    return await cilix_state()


if __name__ == "__main__":
    server.run("stdio")
