#!/usr/bin/env python3
"""
Servidor Principal de Cilix — FastAPI + WebSockets
==================================================
Orquesta los cuatro subsistemas y sirve la interfaz del avatar:

  · CoreIA       → Cerebro Dual (Ri residente / Re bajo demanda) sobre Ollama.
  · AudioEngine  → STT (faster-whisper) + TTS (Piper) + lip-sync.
  · VistaEngine  → percepción del escritorio Linux (ventana activa).
  · OSController → ejecución segura de comandos locales.

El frontend (Electron transparente flotante) se sirve desde aquí y se comunica
por WebSocket en `ws://<host>:<port>/ws`. Todo 100% local, sin APIs de pago.

Protocolo WebSocket (resumen):
  Entrada  : {type: chat|stt|switch_mode|command|window_info|toggle_voice|ping}
  Salida   : {type: connected|status|state|response|speak|stt_result|
              mode_switched|command_result|window_info|error}
"""

import asyncio
import base64
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import psutil
import uvicorn

from audio_engine import AudioEngine
from command_interpreter import CommandInterpreter
from config import FRONTEND_DIR, MODELS_DIR, STATIC_DIR, log_startup_summary, settings
from core_ia import CoreIA
from memory import MemoryStore
from os_controller import OSController
from vista_engine import VistaEngine

# ── Logging robusto ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.dev_mode else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s · %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("cilix_server.log")],
)
logger = logging.getLogger("cilix.main")


# ══════════════════════════════════════════════════════════════════════════
#  GESTOR DE CONEXIONES WEBSOCKET
# ══════════════════════════════════════════════════════════════════════════
class ConnectionManager:
    """Registra clientes WebSocket y gestiona envíos individuales/difusión."""

    def __init__(self) -> None:
        self.active: Dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket) -> str:
        await ws.accept()
        cid = str(uuid.uuid4())
        self.active[cid] = ws
        logger.info("🔌 Conectado %s (total %d)", cid[:8], len(self.active))
        return cid

    def disconnect(self, cid: str) -> None:
        self.active.pop(cid, None)
        logger.info("🔌 Desconectado %s (restantes %d)", cid[:8], len(self.active))

    async def send(self, cid: str, payload: Dict[str, Any]) -> None:
        ws = self.active.get(cid)
        if not ws:
            return
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Fallo envío a %s: %s", cid[:8], exc)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        for cid in list(self.active):
            await self.send(cid, payload)


# ══════════════════════════════════════════════════════════════════════════
#  NÚCLEO DE LA APLICACIÓN
# ══════════════════════════════════════════════════════════════════════════
class CilixServer:
    """Une cerebro, voz, visión y control tras un único canal WebSocket."""

    def __init__(self) -> None:
        self.manager = ConnectionManager()
        self.ai = CoreIA(dev_mode=settings.dev_mode, ram_guard=self._ram_percent)
        self.audio: Optional[AudioEngine] = None
        self.vista: Optional[VistaEngine] = None
        self.osc = OSController()
        self.memory = MemoryStore()
        self.interp = CommandInterpreter()   # lenguaje natural → acciones del SO

        self.settings = {
            "voice_enabled": settings.voice_enabled,
            "vision_enabled": settings.vision_enabled,
        }
        self.status: Dict[str, Any] = {
            "ram_percent": self._ram_percent(),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "mode": "Ri", "ri_loaded": False, "re_loaded": False,
        }
        self._bg_tasks: set = set()
        logger.info("🚀 CilixServer construido")

    # ── Guardas de memoria ─────────────────────────────────────────────────
    def _ram_percent(self) -> float:
        """% de RAM en uso (medida única barata, cacheada por psutil)."""
        try:
            return psutil.virtual_memory().percent
        except Exception:  # noqa: BLE001
            return 0.0

    def _memory_critical(self) -> bool:
        return self._ram_percent() >= settings.ram_critical_percent

    # ── Arranque / apagado ─────────────────────────────────────────────────
    async def startup(self) -> None:
        log_startup_summary()
        # Cerebro: deja a Ri residente (no bloquea el arranque si Ollama falla)
        try:
            await self.ai.initialize()
        except Exception as exc:  # noqa: BLE001
            logger.warning("⚠️ CoreIA no fully inicializado: %s", exc)

        # Voz: carga diferida del motor (Piper se carga, Whisper bajo demanda)
        if self.settings["voice_enabled"]:
            self.audio = AudioEngine()
            await self.audio.initialize()

        # Visión: solo si está habilitada (por defecto OFF para ahorrar RAM)
        if self.settings["vision_enabled"]:
            self.vista = VistaEngine()
            await self.vista.initialize()

        # Tarea periódica de estado + autoprotección de RAM
        self._spawn(self._status_loop())

    async def shutdown(self) -> None:
        logger.info("🧹 Apagando Cilix...")
        for t in self._bg_tasks:
            t.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        if self.audio:
            self.audio.cleanup()
        if self.vista:
            self.vista.cleanup()
        self.osc.cleanup()
        await self.ai.cleanup()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _status_loop(self) -> None:
        """Difunde estado cada 3 s y descarga Re si la RAM se dispara."""
        while True:
            try:
                await asyncio.sleep(3)
                ram = self._ram_percent()
                self.status.update({
                    "ram_percent": ram,
                    "cpu_percent": psutil.cpu_percent(interval=None),
                    "mode": self.ai.active_mode.value,
                    "ri_loaded": self.ai.ri_loaded,
                    "re_loaded": self.ai.re_loaded,
                })
                # Autoprotección: liberar Re si el sistema sufre
                if self.ai.re_loaded and self._memory_critical():
                    logger.warning("🛡️ RAM crítica (%.1f%%) → descargando Re",
                                   self.status["ram_percent"])
                    await self.ai.unload_re_model()
                # EMERGENCIA: liberar también Ri (se recarga sola al next mensaje)
                if (self.ai.ri_loaded and not self.ai.dev_mode and
                        ram >= settings.ram_emergency_percent):
                    logger.warning("🚨 RAM en emergencia (%.1f%%) → descargando Ri",
                                   ram)
                    await self.ai.unload_ri_model()
                await self.manager.broadcast({"type": "status", **self.status})
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("❌ status_loop: %s", exc)
                await asyncio.sleep(5)

    # ── Despacho de mensajes WebSocket ─────────────────────────────────────
    async def handle(self, cid: str, data: Dict[str, Any]) -> None:
        mtype = data.get("type", "chat")
        try:
            if mtype == "chat":
                await self._handle_chat(cid, data)
            elif mtype == "stt":
                await self._handle_stt(cid, data)
            elif mtype == "switch_mode":
                await self._handle_switch_mode(cid, data)
            elif mtype == "command":
                await self._handle_command(cid, data)
            elif mtype == "window_info":
                await self._handle_window_info(cid)
            elif mtype == "toggle_voice":
                self.settings["voice_enabled"] = bool(data.get("enabled"))
                await self.manager.send(cid, {
                    "type": "settings_updated", "voice_enabled":
                        self.settings["voice_enabled"]})
            elif mtype == "ping":
                await self.manager.send(cid, {"type": "pong", "ts": time.time()})
            else:
                await self.manager.send(cid, {
                    "type": "error", "message": f"Tipo desconocido: {mtype}"})
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ handle(%s): %s", mtype, exc)
            await self.manager.send(cid, {
                "type": "error", "message": f"Error interno: {exc}"})

    # ── Chat (cerebro dual) + voz ──────────────────────────────────────────
    async def _handle_chat(self, cid: str, data: Dict[str, Any]) -> None:
        text = (data.get("text") or "").strip()
        mode = data.get("mode") or self.ai.active_mode.value
        if not text:
            await self.manager.send(cid, {"type": "error", "message": "Mensaje vacío"})
            return

        await self.manager.send(cid, {"type": "state", "state": "thinking"})
        self.memory.add_message(cid, "user", text, mode)

        # ¿Es una acción del sistema (lanzar app / comando / consultar estado)?
        # Se ejecuta de inmediato sin pasar por el cerebro.
        intent = self.interp.interpret(text)
        if intent is not None:
            await self._run_intent(cid, text, intent, mode)
            return

        resp = await self.ai.process_message(text, mode)
        answer = resp.get("response", "")
        emotion = resp.get("emotion", "neutral")
        used_mode = resp.get("mode", mode)
        self.memory.add_message(cid, "assistant", answer, used_mode, emotion)

        # Respuesta textual + emoción para el avatar
        await self.manager.send(cid, {
            "type": "response", "text": answer, "emotion": emotion,
            "mode": used_mode, "duration": resp.get("duration", 0),
        })

        # Hablar si el modo voz está activo
        if self.settings["voice_enabled"] and self.audio:
            await self._speak(cid, answer)

        await self.manager.send(cid, {"type": "state", "state": "idle"})

    async def _run_intent(self, cid: str, text: str, intent, mode: str) -> None:
        """Ejecuta una intención detectada (app o comando) y responde con el resultado."""
        await self.manager.send(cid, {"type": "state", "state": "executing"})
        if intent.kind == "launch":
            result = await self.osc.launch_application(intent.app, intent.args)
        else:
            result = await self.osc.execute_safe_command(intent.command)
        await self.manager.send(cid, {"type": "command_result", **result.to_dict()})

        if result.success:
            detalle = (result.output or "").strip()[:800]
            answer = intent.reply_hint or "Listo."
            if detalle:
                answer += "\n\n" + detalle
            emotion = "feliz"
        else:
            answer = f"No pude completar la acción: {result.error or 'el comando falló'}"
            emotion = "triste"

        self.memory.add_message(cid, "assistant", answer, mode, emotion)
        await self.manager.send(cid, {
            "type": "response", "text": answer, "emotion": emotion,
            "mode": mode, "duration": round(result.duration, 3),
        })
        # Hablar solo el resumen (no el volcado de terminal)
        if self.settings["voice_enabled"] and self.audio:
            await self._speak(cid, intent.reply_hint or "Listo.")
        await self.manager.send(cid, {"type": "state", "state": "idle"})

    async def _speak(self, cid: str, text: str) -> None:
        """Sintetiza voz y envía audio + frames de lip-sync al cliente."""
        await self.manager.send(cid, {"type": "state", "state": "talking"})
        speech = await self.audio.synthesize(text)
        if not speech:
            return
        await self.manager.send(cid, {
            "type": "speak",
            "audio": speech.wav_b64,
            "duration": speech.duration,
            "volume_frames": speech.volume_frames,
            "sample_rate": speech.sample_rate,
        })

    # ── STT (audio → texto → chat) ─────────────────────────────────────────
    async def _handle_stt(self, cid: str, data: Dict[str, Any]) -> None:
        if not self.audio:
            await self.manager.send(cid, {
                "type": "error", "message": "Motor de voz no disponible"})
            return
        audio_b64 = data.get("audio")
        if not audio_b64:
            return
        try:
            wav = base64.b64decode(audio_b64)
        except Exception:  # noqa: BLE001
            await self.manager.send(cid, {
                "type": "error", "message": "Audio inválido"})
            return

        await self.manager.send(cid, {"type": "state", "state": "thinking"})
        transcript = await self.audio.transcribe(wav)
        if not transcript:
            await self.manager.send(cid, {
                "type": "stt_result", "text": "", "error": "No se detectó voz"})
            await self.manager.send(cid, {"type": "state", "state": "idle"})
            return

        await self.manager.send(cid, {"type": "stt_result", "text": transcript})
        # Reutilizamos el flujo de chat con lo transcrito
        await self._handle_chat(cid, {"text": transcript, "mode": data.get("mode")})

    # ── Cambio de modo Ri/Re ───────────────────────────────────────────────
    async def _handle_switch_mode(self, cid: str, data: Dict[str, Any]) -> None:
        # Cerebro único: Re no está disponible; siempre se responde con Ri.
        if not settings.dual_brain:
            self.status["mode"] = self.ai.active_mode.value
            await self.manager.send(cid, {"type": "mode_switched", "mode": "Ri"})
            return
        mode = (data.get("mode") or "Ri").capitalize()
        if mode == "Re":
            ok = await self.ai.load_re_model()
            if not ok:
                await self.manager.send(cid, {
                    "type": "error",
                    "message": "No se pudo cargar Re (RAM insuficiente o modelo ausente)"})
                mode = "Ri"
        else:
            await self.ai.unload_re_model()
        self.status["mode"] = self.ai.active_mode.value
        await self.manager.send(cid, {"type": "mode_switched", "mode": mode})

    # ── Comando de sistema seguro ──────────────────────────────────────────
    async def _handle_command(self, cid: str, data: Dict[str, Any]) -> None:
        command = (data.get("command") or "").strip()
        if not command:
            return
        await self.manager.send(cid, {"type": "state", "state": "executing"})
        result = await self.osc.execute_safe_command(command)
        await self.manager.send(cid, {"type": "command_result", **result.to_dict()})
        await self.manager.send(cid, {"type": "state", "state": "idle"})

    # ── Ventana activa (Linux) ─────────────────────────────────────────────
    async def _handle_window_info(self, cid: str) -> None:
        if not self.vista:
            self.vista = VistaEngine()
            await self.vista.initialize()
        info = await self.vista.get_active_window()
        await self.manager.send(cid, {"type": "window_info", **info})


# ══════════════════════════════════════════════════════════════════════════
#  FASTAPI: HTTP (interfaz) + WebSocket (canal en tiempo real)
# ══════════════════════════════════════════════════════════════════════════
server = CilixServer()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await server.startup()
    yield
    await server.shutdown()


app = FastAPI(
    title="Cilix Server",
    description="Asistente de escritorio VTuber · Cerebro Dual local (Ollama)",
    version="2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montaje de estáticos: librerías Live2D, assets del frontend y modelos
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR)), name="app")
if MODELS_DIR.exists():
    app.mount("/models", StaticFiles(directory=str(MODELS_DIR)), name="models")


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> HTMLResponse:
    """Sirve la interfaz flotante del avatar."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Cilix · frontend no encontrado</h1>", status_code=404)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "healthy",
        "service": "Cilix Server",
        "version": "2.0",
        "local_only": True,
        "timestamp": time.time(),
        "ram_percent": server._ram_percent(),
        "connections": len(server.manager.active),
    })


@app.get("/status")
async def status() -> JSONResponse:
    """Estado detallado del sistema y los subsistemas."""
    return JSONResponse({
        "system": server.status,
        "ai": server.ai.get_stats(),
        "settings": {**server.settings, **settings.as_public_dict()},
        "os": server.osc.get_stats(),
    })


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Canal principal en tiempo real para la interfaz."""
    cid = await server.manager.connect(ws)
    await server.manager.send(cid, {
        "type": "connected", "client_id": cid, "state": "idle",
        "config": {**settings.as_public_dict(), **server.settings},
        "status": server.status,
        "message": "Cilix conectada 💕",
    })
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"type": "chat", "text": raw}
            await server.handle(cid, data)
    except WebSocketDisconnect:
        server.manager.disconnect(cid)
    except Exception as exc:  # noqa: BLE001
        logger.error("❌ WS %s: %s", cid[:8], exc)
        server.manager.disconnect(cid)


if __name__ == "__main__":
    dev = "--dev" in sys.argv
    logger.info("🌐 Iniciando Cilix en http://%s:%d", settings.host, settings.port)
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=dev,
        log_level="info" if dev else "warning",
    )
