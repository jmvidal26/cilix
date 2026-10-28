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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import psutil
import uvicorn

from audio_engine import AudioEngine
from clipboard_sentinel import ClipboardSentinel
from command_interpreter import CommandInterpreter, Intent
from companion import SilenceCompanion
from config import FRONTEND_DIR, MODELS_DIR, STATIC_DIR, log_startup_summary, settings
from core_ia import CoreIA
from curiosity import CuriosityEngine
from coding_bridge import CoderBridge, CoderRequest
from edith_bridge import bridge as edith_bridge
from memory import MemoryStore
from os_controller import OSController, CommandResult
from personality_engine import PersonalityEngine
from security import origin_allowed, path_within
from social_engine import SocialEngine
from vista_engine import VistaEngine

# Carpeta que puede abrir la tarjeta social (nada fuera de ella).
SOCIAL_ROOT = Path.home() / "Documents" / "cilix-social"

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
        self.edith = edith_bridge             # puente con E.D.I.T.H (Le'fil)
        self.coder = CoderBridge(             # puente con Antigravity/Qoder
            enabled=settings.coder_enabled,
            provider=settings.coder_provider,
            binary=settings.coder_bin,
            workspace=settings.coder_dir,
            roots=settings.coder_roots,
            mode=settings.coder_mode,
            model=settings.coder_model,
            sandbox=settings.coder_sandbox,
            auto_approve=settings.coder_auto_approve,
            timeout=settings.coder_timeout,
            max_turns=settings.coder_max_turns,
        )
        self.curiosity = CuriosityEngine(engine=settings.curiosity_engine)
        self.companion = SilenceCompanion(self.curiosity)
        # Conexión de la memoria persistente al cerebro + sesión estable: así el
        # historial y los recuerdos sobreviven a recargas (un solo usuario = un
        # hilo continuo de conversación).
        self.ai.attach_memory(self.memory)
        self.session_id = "cilix"
        # Motor de personalidad/ánimo: sesga el prompt y decide cuándo hablar sola.
        self.personality = PersonalityEngine(self.memory)
        self.ai.attach_personality(self.personality)
        # Curiosidades ya aprendidas de la web (persisten entre reinicios).
        self._apply_curiosities(warm=False)
        self._last_user_ts = time.time()      # última interacción real del usuario
        self._proactive_recent: List[float] = []  # ts de los últimos impulsos
        # Agente de contenido social (Ri redacta; el humano publica).
        self.social = SocialEngine(self.ai, lambda: self.audio)
        # Aprobaciones humanas pendientes de sudo: rid → Future(bool).
        self._sudo_pending: Dict[str, asyncio.Future] = {}
        # Vigilante del portapapeles (errores copiados → ayuda proactiva).
        self.clipboard = ClipboardSentinel(self._on_clip_error)

        self.settings = {
            "voice_enabled": settings.voice_enabled,
            "vision_enabled": settings.vision_enabled,
        }
        self.status: Dict[str, Any] = {
            "ram_percent": self._ram_percent(),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "mode": "Ri", "ri_loaded": False, "re_loaded": False,
            "mood": self.personality.mood.to_dict(),
            "proactive": settings.proactive_enabled,
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
        # Compañía en silencio: niveles por tiempo de inactividad. Si está
        # activa, sustituye al bucle proactivo clásico (evita hablar dos veces).
        if settings.companion_enabled:
            self._spawn(self._companion_loop())
        elif settings.proactive_enabled:
            self._spawn(self._proactive_loop())
        # Precalentar el prefijo estático del prompt (cache KV de prefijos de
        # Ollama): el primer prefill real ahorra ~la mitad del cómputo.
        self._spawn(self.ai.warm_prefix_cache())
        # Centinela del portapapeles: detecta errores copiados y Ri ofrece ayuda.
        self._spawn(self.clipboard.run())
        # Curiosidad autónoma: busca temas random y adopta gustos propios.
        if settings.curiosity_enabled:
            self._spawn(self._curiosity_loop())

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
                    "mood": self.personality.mood.to_dict(),
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

    # ── Pensamiento proactivo (Ri habla sola en idle) ─────────────────
    def _recent_topic(self) -> Optional[str]:
        """Último mensaje del usuario (truncado) como tema para un impulso."""
        try:
            rows = self.memory.recent_messages(self.session_id, limit=12)
            for r in reversed(rows):
                if r.get("role") == "user":
                    return (r.get("content") or "")[:60] or None
        except Exception:  # noqa: BLE001
            return None
        return None

    async def _speak_broadcast(self, text: str) -> None:
        """Sintetiza voz y la difunde a todos los clientes (sin cid concreto)."""
        if not self.audio:
            return
        speech = await self.audio.synthesize(text)
        if not speech:
            return
        await self.manager.broadcast({
            "type": "speak", "audio": speech.wav_b64, "duration": speech.duration,
            "volume_frames": speech.volume_frames, "sample_rate": speech.sample_rate,
        })

    async def _proactive_loop(self) -> None:
        """Cuando el usuario lleva idle, Ri puede comentar algo por su cuenta
        (texto + voz si procede). Respeta RAM, horas silencio y topes."""
        await asyncio.sleep(5)   # dejar arrancar tranquilo
        while True:
            try:
                await asyncio.sleep(10)
                now = time.time()
                self._proactive_recent = [
                    t for t in self._proactive_recent if now - t < 3600]
                if self._memory_critical():
                    continue
                seed = self.personality.should_speak(
                    now, self._last_user_ts, self._proactive_recent,
                    recent_topic=self._recent_topic())
                if not seed:
                    continue
                resp = await self.ai.proactive_turn(seed)
                answer = (resp.get("response") or "").strip()
                if not answer:
                    continue
                emotion = resp.get("emotion", "neutral")
                self._proactive_recent.append(now)
                self.memory.add_message(self.session_id, "assistant", answer, "Ri", emotion)
                await self.manager.broadcast({
                    "type": "proactive", "text": answer, "emotion": emotion,
                    "mode": "Ri", "mood": self.personality.mood.to_dict(),
                })
                if (settings.proactive_voice and self.settings["voice_enabled"]
                        and self.audio and not self._memory_critical()):
                    await self._speak_broadcast(answer)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("❌ proactive_loop: %s", exc)
                await asyncio.sleep(15)

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
            elif mtype == "history":
                await self._handle_history(cid)
            elif mtype == "new_chat":
                await self._handle_new_chat(cid)
            elif mtype == "sudo_approval":
                await self._handle_sudo_approval(data)
            elif mtype == "social_action":
                await self._handle_social_action(cid, data)
            elif mtype == "window_info":
                await self._handle_window_info(cid)
            elif mtype == "toggle_voice":
                self.settings["voice_enabled"] = bool(data.get("enabled"))
                await self.manager.send(cid, {
                    "type": "settings_updated", "voice_enabled":
                        self.settings["voice_enabled"]})
            elif mtype == "toggle_proactive":
                settings.proactive_enabled = bool(data.get("enabled"))
                self.status["proactive"] = settings.proactive_enabled
                await self.manager.send(cid, {
                    "type": "settings_updated",
                    "proactive_enabled": settings.proactive_enabled})
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

        self._last_user_ts = time.time()   # el usuario interactuó → reset idle
        await self.manager.send(cid, {"type": "state", "state": "thinking"})
        # Recuperar el contexto persistido (1er mensaje tras recargar) y aprender
        # hechos nuevos del usuario antes de responder.
        self.ai.load_history_from_memory(self.session_id)
        self.ai.extract_facts(text)
        self.memory.add_message(self.session_id, "user", text, mode)

        # ¿Pide silencio o que vuelva a hablar? Se resuelve sin LLM.
        companion_req = self.companion.interpret(text)
        if companion_req:
            await self._run_companion_control(cid, text, companion_req, mode)
            return

        # ¿Pide curiosear / recordar lo aprendido? Se resuelve sin LLM.
        curiosity_req = self.curiosity.interpret(text)
        if curiosity_req is not None:
            await self._run_curiosity(cid, text, curiosity_req, mode)
            return

        # ¿Va dirigido a E.D.I.T.H (Le'fil)? Se resuelve antes que las
        # acciones del SO y sin pasar por el cerebro (ahorra tokens y RAM).
        edith_req = self.edith.interpret(text)
        if edith_req is not None:
            await self._run_edith(cid, text, edith_req, mode)
            return

        # ¿Pide programar algo de verdad? Se delega al agente de código
        # (Antigravity/Qoder) en un subproceso, antes de las acciones del SO
        # para que «crea un script…» no se confunda con «crea una carpeta».
        coder_req = self.coder.interpret(text)
        if coder_req is not None:
            await self._run_coder(cid, text, coder_req, mode)
            return

        # ¿Es una acción del sistema (lanzar app / comando / consultar estado)?
        # Se ejecuta de inmediato sin pasar por el cerebro.
        intent = self.interp.interpret(text)
        if intent is None and self.interp.looks_like_action(text):
            # Fallback LLM: orden disfrazada de charla cortés ("¿me harías el
            # favor de abrir la terminal?"). Solo se gasta la micro-consulta
            # cuando el hint lo justifica; la charla normal NO paga este coste.
            action = await self.ai.parse_action(text)
            if action:
                intent = self._intent_from_action(action)
        if intent is not None:
            await self._run_intent(cid, text, intent, mode)
            return

        resp = await self.ai.process_message(text, mode)
        answer = resp.get("response", "")
        emotion = resp.get("emotion", "neutral")
        used_mode = resp.get("mode", mode)
        self.memory.add_message(self.session_id, "assistant", answer, used_mode, emotion)
        # El ánimo de Ri reacciona a este intercambio (persistente entre sesiones).
        self.personality.on_interaction(text, emotion)

        # Respuesta textual + emoción para el avatar
        await self.manager.send(cid, {
            "type": "response", "text": answer, "emotion": emotion,
            "mode": used_mode, "duration": resp.get("duration", 0),
        })

        # Hablar si el modo voz está activo
        if self.settings["voice_enabled"] and self.audio:
            await self._speak(cid, answer)

        await self.manager.send(cid, {"type": "state", "state": "idle"})

    async def _run_edith(self, cid: str, text: str,
                         req: Tuple[str, Optional[str]], mode: str) -> None:
        """Ejecuta una acción de E.D.I.T.H en un subproceso aislado.

        El subproceso muere al terminar, así que Cilix no paga RAM por el
        motor de pentesting ni por su analizador.
        """
        action, target = req
        started = time.time()
        data = await self.edith.run(action, target)
        answer = self.edith.format_reply(action, data)
        duration = round(time.time() - started, 3)
        emotion = "concentrado" if action in ("scan", "pentest") else "neutral"

        # El mensaje del usuario ya se guardó en _handle_chat.
        self.memory.add_message(self.session_id, "assistant", answer, "Ri", emotion)
        self.ai._add_to_history(text, answer, "Ri")

        await self.manager.send(cid, {
            "type": "response", "text": answer, "emotion": emotion,
            "mode": "Ri", "duration": duration, "source": "edith",
        })
        if self.settings["voice_enabled"] and self.audio:
            await self._speak(cid, answer)
        await self.manager.send(cid, {"type": "state", "state": "idle"})

    async def _run_coder(self, cid: str, text: str,
                         req: CoderRequest, mode: str) -> None:
        """Delega una tarea de código en Antigravity CLI / Qoder CLI.

        El agente corre en un subproceso con su propio directorio de trabajo y
        muere al terminar, así que Cilix no paga su RAM en reposo.
        """
        agent = {"agy": "Antigravity", "qoder": "Qoder"}.get(
            self.coder.provider or "", "el agente de código")
        # Aviso inmediato: la tarea puede tardar bastante. Se emite como globo
        # espontáneo y se vuelve a poner el estado "thinking" justo después.
        await self.manager.send(cid, {
            "type": "proactive",
            "text": f"Vale, se lo paso a {agent}. Dame un momento…",
            "emotion": "concentrado", "mode": "Ri",
            "mood": self.personality.mood.to_dict(),
        })
        await self.manager.send(cid, {"type": "state", "state": "thinking"})

        data = await self.coder.run(
            req.task, workspace=req.workspace, mode=req.mode)
        answer = self.coder.format_reply(data)
        emotion = "concentrado" if data.get("ok") else "neutral"

        self.memory.add_message(self.session_id, "assistant", answer, "Ri", emotion)
        self.ai._add_to_history(text, answer, "Ri")

        await self.manager.send(cid, {
            "type": "response", "text": answer, "emotion": emotion,
            "mode": "Ri", "duration": data.get("duration", 0),
            "source": "coder",
        })
        if (settings.coder_voice and self.settings["voice_enabled"]
                and self.audio):
            await self._speak(cid, answer)
        await self.manager.send(cid, {"type": "state", "state": "idle"})

    # ── Compañía en silencio (habla sola si no interactúas) ────────────────
    async def _run_companion_control(self, cid: str, text: str,
                                     action: str, mode: str) -> None:
        if action == "pause":
            self.companion.pause(30)
            answer = ("Vale, me quedo calladita 30 minutos. Si me necesitas, "
                      "escríbeme y vuelvo al momento.")
        else:
            self.companion.resume()
            answer = "Vuelvo a estar por aquí. Te escucho cuando quieras."
        self.memory.add_message(self.session_id, "assistant", answer, "Ri", "neutral")
        self.ai._add_to_history(text, answer, "Ri")
        await self.manager.send(cid, {
            "type": "response", "text": answer, "emotion": "neutral",
            "mode": "Ri", "source": "companion",
        })
        if self.settings["voice_enabled"] and self.audio:
            await self._speak(cid, answer)
        await self.manager.send(cid, {"type": "state", "state": "idle"})

    async def _companion_loop(self) -> None:
        """Habla sola tras 5/15/40 min de silencio, con topes y horas quietas."""
        await asyncio.sleep(20)   # dejar arrancar el resto del sistema
        while True:
            try:
                await asyncio.sleep(10)
                if self._memory_critical():
                    continue
                moment = self.companion.due(time.time(), self._last_user_ts)
                if moment is None:
                    continue
                try:
                    resp = await asyncio.wait_for(
                        self.ai.proactive_turn(moment.seed), timeout=75)
                except asyncio.TimeoutError:
                    logger.debug("Compañía: el cerebro tardó demasiado; silencio")
                    continue
                answer = (resp.get("response") or "").strip()
                if not answer:
                    continue
                emotion = resp.get("emotion", "neutral")
                self.companion.mark_spoke()
                self.memory.add_message(self.session_id, "assistant", answer,
                                        "Ri", emotion)
                await self.manager.broadcast({
                    "type": "proactive", "text": answer, "emotion": emotion,
                    "mode": "Ri", "tier": moment.tier,
                    "mood": self.personality.mood.to_dict(),
                })
                if (self.companion.voice and self.settings["voice_enabled"]
                        and self.audio):
                    await self._speak_broadcast(answer)
                logger.info("🗣️ Compañía (%s · %d s de silencio): %s",
                            moment.tier, int(moment.idle), answer[:90])
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug("Compañía: fallo silencioso (%r)", exc)

    # ── Curiosidad (busca temas random y adopta gustos) ────────────────────
    def _apply_curiosities(self, warm: bool = True) -> None:
        """Vuelca los últimos hallazgos en la capa de voz (prompt)."""
        if not self.ai.voice:
            return
        topics, opinion = self.curiosity.persona_hint()
        self.ai.voice.set_curiosities(topics, opinion)
        if warm:
            # La línea de curiosidad va en la parte variable del prompt: no
            # invalida la caché KV, así que no hace falta recalcular nada.
            logger.debug("Curiosidad aplicada: %s | %s", topics, opinion)

    async def _run_curiosity(self, cid: str, text: str,
                             req: Tuple[str, Optional[str]], mode: str) -> None:
        kind, topic = req
        started = time.time()
        if kind == "recall":
            answer = self.curiosity.recall_reply()
            record = None
        else:
            try:
                record = await asyncio.wait_for(self.curiosity.learn(topic), timeout=32)
            except asyncio.TimeoutError:
                record = None
            answer = self.curiosity.format_reply(record)
            self._apply_curiosities()

        duration = round(time.time() - started, 3)
        self.memory.add_message(self.session_id, "assistant", answer, "Ri", "curioso")
        self.ai._add_to_history(text, answer, "Ri")
        await self.manager.send(cid, {
            "type": "response", "text": answer, "emotion": "curioso",
            "mode": "Ri", "duration": duration, "source": "curiosity",
        })
        if self.settings["voice_enabled"] and self.audio:
            await self._speak(cid, answer)
        await self.manager.send(cid, {"type": "state", "state": "idle"})

    async def _curiosity_loop(self) -> None:
        """Aprende un tema al azar cuando la casa está en calma."""
        interval = max(300, int(settings.curiosity_interval))
        idle_needed = max(120, int(settings.curiosity_idle))
        await asyncio.sleep(min(300, interval))   # no nada más arrancar
        while True:
            try:
                if time.time() - self._last_user_ts >= idle_needed:
                    record = await asyncio.wait_for(self.curiosity.learn(), timeout=32)
                    if record:
                        self._apply_curiosities()
                        logger.info("🔎 Curiosidad autónoma: %s (%s)",
                                    record.get("short"), record.get("source"))
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug("Curiosidad autónoma falló: %r", exc)
            await asyncio.sleep(interval)

    def _intent_from_action(self, action: Dict[str, str]) -> Optional[Intent]:
        """Convierte el JSON del fallback LLM en una Intent ejecutable.
        El target pasa por los mismos filtros (sandbox/whitelist) que el
        intérprete regex: el modelo SUGIERE, el sándwich de seguridad dispone."""
        kind, target = action["action"], action["target"]
        if kind == "launch":
            app = self.interp._resolve_app(target) or target
            return Intent(kind="launch", app=app,
                          reply_hint=f"Abriendo {app}…")
        if kind == "usb":
            return Intent(kind="usb", app="", reply_hint="Conectando el USB…")
        if kind == "command":
            return Intent(kind="command", command=target,
                          reply_hint="Aquí tienes el dato del sistema.")
        if kind == "writefile":
            return Intent(kind="writefile", app=target,
                          reply_hint=f"Listo, creé «{target}»:")
        return None

    async def _ask_sudo_approval(self, cid: str, command: str) -> bool:
        """Human-in-the-loop: congela un comando privilegiado hasta que el
        usuario apruebe o rechace en la tarjeta de la UI (90 s → rechazo).
        La aprobación se pide SIEMPRE que la orden lleve sudo, aunque el
        sándwich de Python ya la considere segura: doble control."""
        rid = uuid.uuid4().hex[:8]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._sudo_pending[rid] = fut
        try:
            await self.manager.send(cid, {
                "type": "sudo_approval_required", "request_id": rid,
                "command": command,
                "message": "Ri quiere ejecutar esto con privilegios de administrador.",
            })
            logger.info("🔐 Aprobación humana solicitada para: %s", command[:120])
            return await asyncio.wait_for(fut, timeout=90.0)
        except asyncio.TimeoutError:
            logger.info("🔐 Sudo sin respuesta (90 s) → rechazado por defecto")
            return False
        finally:
            self._sudo_pending.pop(rid, None)

    async def _handle_sudo_approval(self, data: Dict[str, Any]) -> None:
        """Responde al clic del usuario en la tarjeta de aprobación."""
        fut = self._sudo_pending.pop(data.get("request_id") or "", None)
        if fut is not None and not fut.done():
            fut.set_result(bool(data.get("approved")))

    async def _run_social(self, cid: str, intent: Intent, mode: str) -> None:
        """Genera un pack de contenido social y lo presenta como tarjeta.
        NUNCA publica: el humano copia/abre el borrador (Human-in-the-Loop)."""
        sub = intent.args[0] if intent.args else "post"
        topic = intent.args[1] if len(intent.args) > 1 else ""
        pack = await self.social.prepare(sub, topic)
        if pack is not None and sub == "reel" and self.settings["voice_enabled"]:
            await self.social.reel_voice(pack)   # voz del guion a .wav local
        if pack is None:
            answer = "Quise redactarlo pero el borrador no salió bien… ¿lo intentamos de nuevo?"
            emotion = "triste"
        else:
            answer = ("¡Borrador listo! 📝 Lo dejé en «" + pack.draft_path +
                      "». Tú lo revisas y publicas (Instagram odia los bots, "
                      "mejor con Approval 😉):\n\n" + pack.summary())
            emotion = "feliz"
            await self.manager.send(cid, {
                "type": "social_proposal", "request_id": uuid.uuid4().hex[:8],
                "caption": pack.caption,
                "hashtags": ["#" + h.lstrip("#") for h in pack.hashtags],
                "draft_path": pack.draft_path,
                "kind": pack.kind,
            })
        self.memory.add_message(self.session_id, "assistant", answer, mode, emotion)
        await self.manager.send(cid, {
            "type": "response", "text": answer, "emotion": emotion,
            "mode": mode, "duration": 0.0,
        })
        if self.settings["voice_enabled"] and self.audio:
            await self._speak(cid, intent.reply_hint or "Listo el borrador.")
        await self.manager.send(cid, {"type": "state", "state": "idle"})

    async def _handle_social_action(self, cid: str, data: Dict[str, Any]) -> None:
        """Acciones de la tarjeta social: abrir la carpeta del borrador.

        La ruta la manda el cliente, así que se confina a
        `~/Documents/cilix-social` y se abre sin shell. Antes bastaba un
        `path: "x; rm -rf ~"` para inyectar un comando en el backend.
        """
        if data.get("action") != "open":
            return
        target = path_within(data.get("path") or "", SOCIAL_ROOT)
        if target is None:
            await self.manager.send(cid, {
                "type": "error",
                "message": "Ruta no permitida (solo la carpeta de borradores)",
            })
            return
        if not await self.osc.open_path(str(target)):
            await self.manager.send(cid, {
                "type": "error", "message": "No pude abrir la carpeta del borrador"})

    async def _on_clip_error(self, snippet: str) -> None:
        """ClipboardSentinel → Ri ofrece ayuda proactiva al ver un error copiado.
        Respeta RAM crítica y el rate-limit interno del centinela."""
        if self._memory_critical() or not settings.proactive_enabled:
            return
        first = next((l for l in snippet.splitlines() if l.strip()), "")[:140]
        seed = (f"El usuario acaba de copiar al portapapeles este error: "
                f"{first!r}. Ofrécete en UNA frase corta y natural a revisarlo "
                "junto a él.")
        try:
            resp = await self.ai.proactive_turn(seed)
            answer = (resp.get("response") or "").strip()
            if not answer:
                return
            emotion = resp.get("emotion", "concentrado")
            self._proactive_recent.append(time.time())
            self.memory.add_message(self.session_id, "assistant", answer, "Ri", emotion)
            await self.manager.broadcast({
                "type": "proactive", "text": answer, "emotion": emotion,
                "mode": "Ri", "mood": self.personality.mood.to_dict(),
            })
            if (settings.proactive_voice and self.settings["voice_enabled"]
                    and self.audio and not self._memory_critical()):
                await self._speak_broadcast(answer)
        except Exception as exc:  # noqa: BLE001
            logger.warning("clipboard→proactivo: %s", exc)

    async def _run_intent(self, cid: str, text: str, intent, mode: str) -> None:
        """Ejecuta una intención detectada (app o comando) y responde con el resultado."""
        await self.manager.send(cid, {"type": "state", "state": "executing"})
        if intent.kind == "launch":
            result = await self.osc.launch_application(intent.app, intent.args)
        elif intent.kind == "usb":
            # "abre el usb" → montar y abrir en el gestor de archivos
            result = await self.osc.mount_usb(intent.app or "")
        elif intent.kind == "help":
            # Catálogo de comandos: no se ejecuta nada, reply_hint es el texto
            result = CommandResult(True, "", "", 0, 0.0, "help")
        elif intent.kind == "social":
            await self._run_social(cid, intent, mode)
            return
        elif intent.kind == "writefile":
            # "haz un código llamado i.html" → plantilla real en ~/Documents/cilix
            nlines = int(intent.args[0]) if intent.args else 0
            result = await self.osc.create_code_file(intent.app or "", lines=nlines)
        else:
            cmd = (intent.command or "").strip()
            if cmd.startswith("sudo"):
                # Privilegios → SIEMPRE pasa por aprobación humana en la UI.
                approved = await self._ask_sudo_approval(cid, cmd)
                if not approved:
                    result = CommandResult(False, "",
                        "el usuario rechazó la operación privilegiada", 1,
                        0.0, cmd)
                else:
                    result = await self.osc.execute_safe_command(cmd)
            else:
                result = await self.osc.execute_safe_command(cmd)
        await self.manager.send(cid, {"type": "command_result", **result.to_dict()})

        if result.success:
            detalle = (result.output or "").strip()[:800]
            answer = intent.reply_hint or "Listo."
            if detalle:
                answer += "\n\n" + detalle
            emotion = "feliz"
            # Hito › sugiere contenido social (la sugerencia no gasta LLM).
            if intent.kind == "writefile":
                answer += ("\n\n💡 Si quieres, con «haz un post sobre esto» "
                           "te preparo el caption para #BuildInPublic.")
        else:
            answer = f"No pude completar la acción: {result.error or 'el comando falló'}"
            emotion = "triste"

        self.memory.add_message(self.session_id, "assistant", answer, mode, emotion)
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
        self._last_user_ts = time.time()
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

    # ── Historial / acceso a chats ─────────────────────────────────
    async def _handle_history(self, cid: str) -> None:
        """Envía los mensajes persistidos de la sesión actual al cliente."""
        msgs = self.memory.recent_messages(self.session_id, limit=80)
        await self.manager.send(cid, {"type": "history", "messages": msgs})

    async def _handle_new_chat(self, cid: str) -> None:
        """Inicia un chat nuevo: olvida la conversación (RAM **y** SQLite de la
        sesión actual) para que `load_history_from_memory` no reintroduzca el
        contexto viejo. Los HECHOS del perfil (nombre, gustos) SÍ se conservan."""
        self.ai.conversation_history = []
        try:
            self.memory.clear_session(self.session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("clear_session falló: %r", exc)
        await self.manager.send(cid, {"type": "new_chat_started"})

    def history_payload(self, limit: int = 40) -> List[Dict[str, Any]]:
        """Historial reciente para incluirlo en el saludo de conexión."""
        return self.memory.recent_messages(self.session_id, limit=limit)


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
    version="2.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Solo la propia interfaz (navegador local o Electron). Con "*" cualquier
    # web podía leer las rutas HTTP del backend desde el navegador.
    allow_origins=[
        f"http://127.0.0.1:{settings.port}",
        f"http://localhost:{settings.port}",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def guard_local_writes(request, call_next):
    """Bloquea escrituras HTTP con `Origin` externo.

    CORS solo impide LEER la respuesta, no enviar la petición (un POST
    "simple" no lleva preflight). Esto cierra esa vía para `/api/*` sin
    afectar al MCP ni a scripts locales (que no mandan `Origin`).
    """
    if (request.url.path.startswith("/api/")
            and request.method not in ("GET", "HEAD", "OPTIONS")):
        origin = request.headers.get("origin")
        if not origin_allowed(origin):
            logger.warning("🚫 API rechazada (Origin no local): %r", origin)
            return JSONResponse(
                {"ok": False, "error": "Origen no permitido"}, status_code=403)
    return await call_next(request)

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
        "version": "2.1",
        "local_only": True,
        "timestamp": time.time(),
        "ram_percent": server._ram_percent(),
        "connections": len(server.manager.active),
        # El cerebro activo se ve desde fuera (run.sh y MCP lo consultan).
        "brain": "opencode" if server.ai.online is not None else "ollama",
        "online": server.ai.online is not None,
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


@app.get("/history")
async def history(limit: int = 80) -> JSONResponse:
    """Devuelve el historial de conversación y los hechos recordados del
    usuario. Base del 'acceso a chats' (frontend y depuración)."""
    return JSONResponse({
        "session": server.session_id,
        "messages": server.memory.recent_messages(server.session_id, limit=limit),
        "facts": server.memory.get_all_facts(),
        "sessions": server.memory.list_sessions(limit=20),
    })


# ── API REST para el agente (MCP) ──────────────────────────────────────────
# El servidor MCP (`mcp_server.py`) y cualquier script local pueden hacer que
# Cilix hable o cambie de cara sin pasar por el WebSocket del navegador.
class SayPayload(BaseModel):
    text: str
    emotion: str = "neutral"
    speak: bool = True


class EmotionPayload(BaseModel):
    emotion: str = "neutral"


class AskPayload(BaseModel):
    text: str
    speak: bool = False


class RememberPayload(BaseModel):
    key: str
    value: str


class EdithPayload(BaseModel):
    action: str = "status"      # status | devices | scan | pentest
    target: str = ""            # IP privada (solo pentest)
    speak: bool = False


VALID_EDITH_ACTIONS = {"status", "devices", "scan", "pentest"}


class CoderPayload(BaseModel):
    task: str = ""
    workspace: str = ""         # vacío = proyecto por defecto
    mode: str = ""              # plan | accept-edits | auto
    timeout: float = 0          # 0 = CILIX_CODER_TIMEOUT
    speak: bool = False


class CuriosityPayload(BaseModel):
    topic: str = ""             # vacío = tema al azar
    speak: bool = False


class CompanionPayload(BaseModel):
    action: str = "status"      # status | pause | resume
    minutes: int = 30


VALID_EMOTIONS = {"neutral", "feliz", "triste", "enfadado", "sorprendido",
                  "concentrado"}


@app.post("/api/say")
async def api_say(payload: SayPayload) -> JSONResponse:
    """Hace que Cilix diga un texto ya escrito (voz + globo + emoción).

    No consulta al cerebro: es el canal de SALIDA que usa el agente cuando
    quiere hablar por ella. Coste: solo el TTS.
    """
    text = (payload.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "texto vacío"}, status_code=400)
    emotion = payload.emotion if payload.emotion in VALID_EMOTIONS else "neutral"
    await server.manager.broadcast({
        "type": "proactive", "text": text, "emotion": emotion, "mode": "Ri",
        "mood": server.personality.mood.to_dict(),
    })
    spoken = False
    if payload.speak and server.settings["voice_enabled"] and server.audio:
        await server._speak_broadcast(text)
        spoken = True
    server.memory.add_message(server.session_id, "assistant", text, "Ri", emotion)
    return JSONResponse({"ok": True, "spoken": spoken, "emotion": emotion})


@app.post("/api/emotion")
async def api_emotion(payload: EmotionPayload) -> JSONResponse:
    """Cambia la cara del avatar sin hablar (gesto del agente)."""
    emotion = payload.emotion if payload.emotion in VALID_EMOTIONS else "neutral"
    await server.manager.broadcast({"type": "emotion", "emotion": emotion})
    return JSONResponse({"ok": True, "emotion": emotion})


@app.post("/api/remember")
async def api_remember(payload: RememberPayload) -> JSONResponse:
    """Guarda un hecho persistente del usuario desde el agente/MCP."""
    key = (payload.key or "").strip()
    value = (payload.value or "").strip()
    if not key or not value:
        return JSONResponse(
            {"ok": False, "error": "key y value son obligatorios"},
            status_code=400)
    server.memory.remember_fact(key, value)
    return JSONResponse({"ok": True, "key": key, "value": value})


@app.post("/api/ask")
async def api_ask(payload: AskPayload) -> JSONResponse:
    """Responde una pregunta sin pasar por el WebSocket (canal del agente).

    Útil para el agente/MCP y para pruebas automatizadas del pipeline.
    """
    text = (payload.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "texto vacío"}, status_code=400)
    server.ai.load_history_from_memory(server.session_id)
    server.ai.extract_facts(text)
    server.memory.add_message(server.session_id, "user", text, "Ri")
    resp = await server.ai.process_message(text, "Ri")
    answer = resp.get("response", "")
    emotion = resp.get("emotion", "neutral")
    server.personality.on_interaction(text, emotion)
    server.memory.add_message(server.session_id, "assistant", answer, "Ri", emotion)
    await server.manager.broadcast({
        "type": "response", "text": answer, "emotion": emotion, "mode": "Ri",
        "duration": resp.get("duration", 0),
    })
    if payload.speak and server.settings["voice_enabled"] and server.audio:
        await server._speak_broadcast(answer)
    return JSONResponse({
        "ok": True, "response": answer, "emotion": emotion,
        "duration": resp.get("duration", 0), "mode": resp.get("mode", "Ri"),
    })


@app.post("/api/edith")
async def api_edith(payload: EdithPayload) -> JSONResponse:
    """Ejecuta una acción de E.D.I.T.H (Le'fil) y devuelve la frase + datos.

    Canal para agentes/automatización sin pasar por el WebSocket. El motor de
    E.D.I.T.H corre en un subproceso que muere al terminar: 0 RAM en reposo.
    """
    action = (payload.action or "status").strip().lower()
    if action not in VALID_EDITH_ACTIONS:
        return JSONResponse(
            {"ok": False, "error": f"acción no válida: {action}"}, status_code=400)
    data = await server.edith.run(action, (payload.target or "").strip() or None)
    reply = server.edith.format_reply(action, data)
    emotion = "concentrado" if action in ("scan", "pentest") else "neutral"
    server.memory.add_message(server.session_id, "assistant", reply, "Ri", emotion)
    await server.manager.broadcast({
        "type": "response", "text": reply, "emotion": emotion,
        "mode": "Ri", "source": "edith",
    })
    if payload.speak and server.settings["voice_enabled"] and server.audio:
        await server._speak_broadcast(reply)
    return JSONResponse({
        "ok": bool(data.get("ok")), "reply": reply,
        "emotion": emotion, "data": data,
    })


@app.post("/api/coder")
async def api_coder(payload: CoderPayload) -> JSONResponse:
    """Delega una tarea de programación a Antigravity CLI o Qoder CLI.

    El agente corre como subproceso en el proyecto indicado y muere al
    terminar: Cilix no paga su RAM en reposo. Canal para agentes/MCP y para
    automatización sin pasar por el WebSocket.
    """
    task = (payload.task or "").strip()
    if not task:
        return JSONResponse(
            {"ok": False, "error": "falta la tarea de programación"},
            status_code=400)
    data = await server.coder.run(
        task,
        workspace=(payload.workspace or "").strip() or None,
        mode=(payload.mode or "").strip() or None,
        timeout=payload.timeout or None,
    )
    reply = server.coder.format_reply(data)
    emotion = "concentrado" if data.get("ok") else "neutral"
    server.memory.add_message(server.session_id, "assistant", reply, "Ri", emotion)
    await server.manager.broadcast({
        "type": "response", "text": reply, "emotion": emotion,
        "mode": "Ri", "source": "coder",
        "duration": data.get("duration", 0),
    })
    if payload.speak and server.settings["voice_enabled"] and server.audio:
        await server._speak_broadcast(reply)
    return JSONResponse({
        "ok": bool(data.get("ok")), "reply": reply,
        "emotion": emotion, "data": data,
    })


@app.get("/api/coder")
async def api_coder_status() -> JSONResponse:
    """Estado del puente de programación (proveedor, proyecto y permisos)."""
    return JSONResponse({"ok": True, "coder": server.coder.status()})


@app.post("/api/curiosity")
async def api_curiosity(payload: CuriosityPayload) -> JSONResponse:
    """Busca un tema (o uno al azar), aprende y devuelve la frase + hallazgo.

    No usa el LLM: una petición HTTP y una plantilla. La personalidad cambia
    porque el hallazgo se inyecta desde ese momento en el prompt de Ri.
    """
    topic = (payload.topic or "").strip() or None
    try:
        record = await asyncio.wait_for(server.curiosity.learn(topic), timeout=32)
    except asyncio.TimeoutError:
        record = None
    reply = server.curiosity.format_reply(record)
    server._apply_curiosities()
    server.memory.add_message(server.session_id, "assistant", reply, "Ri", "curioso")
    await server.manager.broadcast({
        "type": "response", "text": reply, "emotion": "curioso",
        "mode": "Ri", "source": "curiosity",
    })
    if payload.speak and server.settings["voice_enabled"] and server.audio:
        await server._speak_broadcast(reply)
    topics, opinion = server.curiosity.persona_hint()
    return JSONResponse({
        "ok": bool(record), "reply": reply, "record": record,
        "personality": {"interests": topics, "opinion": opinion},
    })


@app.get("/api/companion")
async def api_companion_state() -> JSONResponse:
    """Estado del módulo de compañía (pausa, topes, horas de silencio)."""
    return JSONResponse({"ok": True, "companion": server.companion.status()})


@app.post("/api/companion")
async def api_companion(payload: CompanionPayload) -> JSONResponse:
    """Pausa, reanuda o consulta la voz espontánea de Cilix."""
    action = (payload.action or "status").strip().lower()
    if action == "pause":
        server.companion.pause(payload.minutes)
    elif action == "resume":
        server.companion.resume()
    elif action != "status":
        return JSONResponse({"ok": False,
                             "error": "acción no válida: status|pause|resume"},
                            status_code=400)
    return JSONResponse({"ok": True, "companion": server.companion.status()})


@app.get("/api/state")
async def api_state() -> JSONResponse:
    """Estado compacto para el agente: RAM, ánimo, cerebro y conexiones."""
    online = {"enabled": False}
    if server.ai.online is not None:
        online = {"enabled": True, **(await server.ai.online.health())}
    return JSONResponse({
        "ram_percent": server._ram_percent(),
        "connections": len(server.manager.active),
        "mood": server.personality.mood.to_dict(),
        "mode": server.ai.active_mode.value,
        "brain": "opencode" if server.ai.online is not None else "ollama",
        "ai": server.ai.get_stats(),
        "online": online,
        "coder": server.coder.status(),
    })


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Canal principal en tiempo real para la interfaz."""
    # CORS no protege los WebSockets: sin esta comprobación, cualquier página
    # abierta en el navegador podía conectar a ws://127.0.0.1:8765 y mandar
    # `command` al controlador del sistema.
    origin = ws.headers.get("origin")
    if not origin_allowed(origin):
        logger.warning("🚫 WebSocket rechazado (Origin no local): %r", origin)
        await ws.close(code=1008)
        return
    cid = await server.manager.connect(ws)
    await server.manager.send(cid, {
        "type": "connected", "client_id": cid, "state": "idle",
        "config": {**settings.as_public_dict(), **server.settings},
        "status": server.status,
        "history": server.history_payload(40),
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
        # Ruido habitual del cliente (recarga de pestaña, socket cerrado antes
        # de un envío): no es un fallo del servidor, solo informativo.
        logger.warning("WS %s cerrado: %r", cid[:8], exc)
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
        # Keepalive del WS: con 8 GB y swap, un pico de CPU (TTS/Ollama) puede
        # retrasar los pongs más de los 20 s por defecto y el servidor cortaba
        # la conexión del frontend (1011 keepalive ping timeout). Más margen.
        ws_ping_interval=60,
        ws_ping_timeout=300,
    )
