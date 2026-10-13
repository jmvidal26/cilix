"""
main.py — Sylix OS Core Assistant
Backend FastAPI + Async WebSocket + Multi-Backend IA + TTS Lip-Sync

Backends de IA (selección automática):
  1. Google Gemini API  (online, primario)    — requiere GEMINI_API_KEY
  2. Anthropic Claude   (online, secundario)  — requiere ANTHROPIC_API_KEY
  3. Ollama local       (offline, fallback)   — requiere servidor Ollama corriendo
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from tools import ANTHROPIC_TOOLS, dispatch_tool
from ai_backends import AIRouter, BackendType, check_internet, invalidate_connectivity_cache

# Importar características avanzadas
try:
    from advanced_features import get_advanced_features
    ADVANCED_FEATURES_AVAILABLE = True
except ImportError:
    ADVANCED_FEATURES_AVAILABLE = False
    logger.warning("[Advanced] Características avanzadas no disponibles")

# ─── Cargar .env si existe ────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass   # python-dotenv opcional

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sylix.main")

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN DE API KEYS Y MODELOS
# ═══════════════════════════════════════════════════════════════════════════════

GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY",    "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

GEMINI_MODEL    = os.environ.get("GEMINI_MODEL",    "gemini-2.0-flash")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL",    "qwen2.5:1.5b")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# Validación de configuración
if not GEMINI_API_KEY and not ANTHROPIC_API_KEY:
    logger.warning(
        "[Config] ⚠ Sin GEMINI_API_KEY ni ANTHROPIC_API_KEY. "
        "El agente solo funcionará offline con Ollama."
    )
elif GEMINI_API_KEY:
    logger.info(f"[Config] ✓ Gemini configurado → {GEMINI_MODEL}")
    if ANTHROPIC_API_KEY:
        logger.info(f"[Config] ✓ Anthropic configurado (fallback) → {ANTHROPIC_MODEL}")
elif ANTHROPIC_API_KEY:
    logger.info(f"[Config] ✓ Anthropic configurado → {ANTHROPIC_MODEL}")

logger.info(f"[Config] Ollama offline model → {OLLAMA_MODEL} @ {OLLAMA_BASE_URL}")

# ─── System Prompt de Sylix ──────────────────────────────────────────────────
SYLIX_SYSTEM_PROMPT = """Eres Sylix, asistente VTuber anime del sistema operativo Pop!_OS. Personalidad amable y eficiente.

REGLAS CRÍTICAS DE HERRAMIENTAS:
- SIEMPRE usa execute_bash para: crear carpetas (mkdir), instalar paquetes (pip, apt), mover archivos, ejecutar scripts, consultar sistema.
- SIEMPRE usa file_manager para leer/escribir/listar archivos.
- JAMÁS respondas solo con texto cuando el usuario pide una acción del sistema. PRIMERO ejecuta la herramienta, LUEGO confirma.
- Para instalar con apt usa: execute_bash con "sudo apt-get install -y <paquete>" — si sudo requiere contraseña, usa pkexec o avisa.
- Crear carpeta: execute_bash → "mkdir -p /ruta/carpeta"
- Listar archivos: execute_bash → "ls -la /ruta"
- Ver proceso: execute_bash → "ps aux | grep nombre"

REGLAS DE RESPUESTA:
- Respuestas ULTRA CORTAS (máximo 15 palabras habladas) después de ejecutar la herramienta.
- NUNCA des explicaciones largas ni saludos innecesarios.
- Idioma: español.
- Confirma siempre qué herramienta ejecutaste y su resultado en 1 frase.

CAPACIDADES DISPONIBLES:
- execute_bash: cualquier comando de terminal Linux/Pop!_OS
- file_manager: leer, escribir, mover, eliminar, listar archivos
- desktop_automation: mover mouse, hacer clic, abrir apps, captura de pantalla
- system_monitor: CPU, RAM, procesos, discos, red"""

# ─── Router de IA (inicializado en lifespan) ─────────────────────────────────
AI_ROUTER: AIRouter | None = None

# ─── Características avanzadas (inicializado en lifespan) ─────────────────────
ADVANCED_FEATURES = None


# ═══════════════════════════════════════════════════════════════════════════════
#  TTS (edge-tts online → pyttsx3 offline → simulado)
# ═══════════════════════════════════════════════════════════════════════════════

import tempfile
import subprocess
import struct

# ── Edge-TTS (Microsoft Neural voices — requiere internet) ───────────────────
EDGE_TTS_VOICE = os.environ.get("EDGE_TTS_VOICE", "es-CO-SalomeNeural")
EDGE_TTS_RATE  = os.environ.get("EDGE_TTS_RATE",  "+10%")
EDGE_TTS_PITCH = os.environ.get("EDGE_TTS_PITCH", "+5Hz")

EDGE_TTS_AVAILABLE = False
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
    logger.info(f"[TTS] edge-tts disponible ✓ (voz: {EDGE_TTS_VOICE})")
except ImportError:
    logger.warning("[TTS] edge-tts no instalado.")

# ── Piper TTS (neural offline — voz femenina natural en español) ─────────────────
PIPER_AVAILABLE = False
_piper_voice    = None
PIPER_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "piper", "es_ES-sharvard-medium.onnx"
)
try:
    from piper.voice import PiperVoice
    if os.path.exists(PIPER_MODEL_PATH):
        _piper_voice   = PiperVoice.load(PIPER_MODEL_PATH)
        PIPER_AVAILABLE = True
        logger.info(f"[TTS] Piper neural offline ✓ (es_ES-sharvard-medium, {_piper_voice.config.sample_rate}Hz)")
    else:
        logger.warning(f"[TTS] Piper: modelo no encontrado en {PIPER_MODEL_PATH}")
except Exception as exc:
    logger.warning(f"[TTS] Piper no disponible: {exc}")

# ── pyttsx3 (fallback si Piper no está) ────────────────────────────────────────────
PYTTSX3_AVAILABLE = False
_tts_engine = None
if not PIPER_AVAILABLE:
    try:
        import pyttsx3
        _tts_engine = pyttsx3.init()
        _tts_engine.setProperty("rate", 185)
        for v in _tts_engine.getProperty("voices"):
            if any(lang in str(v.languages) for lang in ["es", "spa"]):
                _tts_engine.setProperty("voice", v.id)
                break
        PYTTSX3_AVAILABLE = True
        logger.info("[TTS] pyttsx3 ✓ (fallback offline)")
    except Exception:
        logger.warning("[TTS] pyttsx3 no disponible.")

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False

FRAME_DURATION_S = 1 / 30
SAMPLE_RATE      = 24000


def _get_tts_backend() -> str:
    """Selecciona el mejor TTS backend según conectividad actual."""
    if EDGE_TTS_AVAILABLE:
        if _CONNECTIVITY_CACHE.get("online") is not False:
            return "edge_tts"
    if PIPER_AVAILABLE:
        return "piper"
    if PYTTSX3_AVAILABLE:
        return "pyttsx3"
    return "simulated"


# Referencia al cache de conectividad (se llena en ai_backends.py)
_CONNECTIVITY_CACHE = {}


# ═══════════════════════════════════════════════════════════════════════════════
#  GESTOR DE CONEXIONES WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"[WS] Cliente conectado: {client_id[:8]}… | Total: {len(self.active_connections)}")

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)
        logger.info(f"[WS] Cliente desconectado: {client_id[:8]}…")

    async def send_json(self, client_id: str, data: dict):
        ws = self.active_connections.get(client_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception as e:
                logger.debug(f"[WS] Error enviando a {client_id[:8]}: {e}")


manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════════════════════
#  CALLBACK DE ESTADO (para los backends de IA)
# ═══════════════════════════════════════════════════════════════════════════════

async def on_state_change(client_id: str, state: str, message: str = "") -> None:
    """
    Callback que los backends usan para notificar cambios de estado al frontend.
    """
    payload: dict[str, Any] = {"state": state}
    if message:
        payload["message"] = message
    await manager.send_json(client_id, payload)


# ═══════════════════════════════════════════════════════════════════════════════
#  AGENTIC TURN (usa el router)
# ═══════════════════════════════════════════════════════════════════════════════

async def dispatch_tool_with_memory(tool_name: str, tool_input: dict, client_id: str) -> dict:
    """
    Wrapper para dispatch_tool que también registra acciones en la memoria.
    """
    try:
        # Ejecutar la herramienta
        result = await dispatch_tool(tool_name, tool_input, client_id)
        
        # Registrar acción en memoria si está disponible
        if ADVANCED_FEATURES:
            try:
                success = result.get("status") == "success" or "error" not in result
                importance = 1.0 if tool_name == "execute_bash" else 0.5
                
                ADVANCED_FEATURES.add_action(
                    action_type=tool_name,
                    command=str(tool_input.get("command", tool_input.get("input", ""))),
                    result=result,
                    success=success,
                    importance=importance
                )
                
                # Si es un comando de sistema, también registrar contexto de actividad
                if tool_name == "execute_bash" and "command" in tool_input:
                    cmd = tool_input["command"]
                    # Detectar si es un comando de sistema común
                    common_system_commands = ["ls", "cd", "mkdir", "rm", "cp", "mv", "apt", "pip", "git", "npm"]
                    if any(cmd.startswith(c) or f" {c} " in cmd for c in common_system_commands):
                        activity_data = {
                            "command_executed": cmd,
                            "success": success,
                            "timestamp": time.time()
                        }
                        ADVANCED_FEATURES.update_activity_context({
                            "user_interaction": {
                                "type": "command_execution",
                                "details": activity_data
                            }
                        })
            except Exception as e:
                logger.error(f"[Advanced] Error adding action to memory: {e}")
        
        return result
        
    except Exception as e:
        logger.error(f"[Tool/Memory] Error: {e}")
        # Si falla el wrapper, intentar ejecutar sin memoria
        return await dispatch_tool(tool_name, tool_input, client_id)


async def run_agent_turn(
    user_message: str,
    client_id:    str,
    history:      list[dict],
) -> tuple[str, list[dict]]:
    """
    Ejecuta un turno completo del agente con selección automática de backend.
    """
    assert AI_ROUTER is not None, "AI_ROUTER no inicializado"

    # Notificar LISTENING → THINKING al frontend
    await manager.send_json(client_id, {"state": "listening", "text": user_message})

    # ── Características avanzadas: agregar conversación a memoria ───────────────
    if ADVANCED_FEATURES:
        try:
            ADVANCED_FEATURES.add_conversation("user", user_message)
        except Exception as e:
            logger.error(f"[Advanced] Error adding conversation to memory: {e}")

    # Añadir mensaje del usuario al historial
    history.append({"role": "user", "content": user_message})

    # ── Verificar conectividad y notificar al frontend ─────────────────────────
    online = await check_internet()
    await manager.send_json(client_id, {
        "type":    "network_status",
        "online":  online,
        "message": "Online" if online else "Offline — usando modelo local",
    })

    # ── Características avanzadas: enriquecer system prompt con contexto ──────
    enhanced_system_prompt = SYLIX_SYSTEM_PROMPT
    if ADVANCED_FEATURES:
        try:
            # Obtener contexto de características avanzadas
            advanced_context = ADVANCED_FEATURES.get_context_for_ai()
            if advanced_context:
                enhanced_system_prompt = f"{SYLIX_SYSTEM_PROMPT}\n\n{advanced_context}"
                logger.debug(f"[Advanced] Contexto añadido: {len(advanced_context)} caracteres")
        except Exception as e:
            logger.error(f"[Advanced] Error getting context: {e}")

    # ── Ejecutar con el router ────────────────────────────────────────────────
    try:
        final_text, updated_history, backend_used = await AI_ROUTER.run_turn(
            system_prompt=enhanced_system_prompt,
            history=history,
            tools_anthropic=ANTHROPIC_TOOLS,
            dispatch_fn=lambda tool_name, tool_input, client_id=client_id: dispatch_tool_with_memory(tool_name, tool_input, client_id),
            on_state=on_state_change,
            client_id=client_id,
        )
    except Exception as e:
        logger.exception("[Agent] Error inesperado en run_turn")
        final_text    = f"Error interno: {e}"
        updated_history = history

    # ── Emitir respuesta final al frontend ────────────────────────────────────
    backend_label = {
        BackendType.GEMINI:    "Gemini",
        BackendType.ANTHROPIC: "Claude",
        BackendType.OLLAMA:    "Ollama (local)",
    }.get(backend_used, "?")  # type: ignore[arg-type]

    if final_text:
        # ── Características avanzadas: agregar respuesta del asistente a memoria ──
        if ADVANCED_FEATURES:
            try:
                ADVANCED_FEATURES.add_conversation("assistant", final_text)
            except Exception as e:
                logger.error(f"[Advanced] Error adding assistant response to memory: {e}")
        
        await manager.send_json(client_id, {
            "type":    "response",
            "text":    final_text,
            "state":   "talking",
            "backend": backend_label,
        })
        # Síntesis de voz en background
        asyncio.create_task(synthesize_and_lipsync(final_text, client_id))
    else:
        await manager.send_json(client_id, {"state": "idle"})

    return final_text, updated_history


# ═══════════════════════════════════════════════════════════════════════════════
#  TTS + LIP-SYNC
# ═══════════════════════════════════════════════════════════════════════════════

def compute_rms_volume(chunk: np.ndarray) -> float:
    if len(chunk) == 0:
        return 0.0
    rms = math.sqrt(np.mean(chunk.astype(np.float64) ** 2))
    normalized = (rms / 32768.0) if chunk.dtype == np.int16 else min(rms, 1.0)
    return round(min(normalized * 3.0, 1.0), 4)


async def synthesize_and_lipsync(text: str, client_id: str) -> None:
    _preview = repr(text[:80])
    tts = _get_tts_backend()
    logger.info(f"[TTS] Sintetizando ({tts}): {_preview}")

    # Modo optimizado para texto largo (más de 3 oraciones)
    text_length = len(text.split())
    
    if tts == "edge_tts":
        await _synthesize_edge_tts(text, client_id)
    elif tts == "piper":
        if text_length > 50:  # Texto largo, usar versión optimizada
            logger.debug("[TTS] Usando Piper optimizado para texto largo")
        await _synthesize_piper(text, client_id)
    elif tts == "pyttsx3":
        await _synthesize_pyttsx3(text, client_id)
    else:
        await _simulate_lipsync(text, client_id)

    await manager.send_json(client_id, {"state": "idle", "volume": 0.0})


def _split_into_sentences(text: str) -> list[str]:
    """Divide texto en oraciones naturales."""
    import re
    # Patrones para dividir oraciones
    sentence_endings = r'[.!?。！？]+'
    sentences = re.split(sentence_endings, text)
    # Filtrar oraciones vacías y limpiar espacios
    sentences = [s.strip() for s in sentences if s.strip()]
    # Si no se encontraron divisiones, dividir por comas
    if len(sentences) <= 1 and len(text) > 50:
        sentences = re.split(r'[,，;；]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
    return sentences if sentences else [text]


def _split_text_into_fragments(text: str, max_length: int = 100) -> list[str]:
    """Divide texto en fragmentos de longitud máxima."""
    words = text.split()
    fragments = []
    current_fragment = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) + 1 <= max_length:
            current_fragment.append(word)
            current_length += len(word) + 1
        else:
            if current_fragment:
                fragments.append(" ".join(current_fragment))
            current_fragment = [word]
            current_length = len(word)
    
    if current_fragment:
        fragments.append(" ".join(current_fragment))
    
    return fragments


def _decode_mp3_to_pcm(mp3_path: str) -> tuple[np.ndarray, int]:
    """Decode MP3 file to PCM samples using ffmpeg."""
    result = subprocess.run(
        [
            "ffmpeg", "-i", mp3_path,
            "-f", "s16le",       # raw PCM signed 16-bit little-endian
            "-acodec", "pcm_s16le",
            "-ac", "1",          # mono
            "-ar", "24000",      # 24kHz sample rate
            "-v", "quiet",
            "pipe:1",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed: {result.stderr.decode()[:200]}")

    pcm_data = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return pcm_data, 24000


async def _synthesize_edge_tts(text: str, client_id: str) -> None:
    """Synthesize speech using Microsoft Edge-TTS neural voices."""
    loop = asyncio.get_event_loop()

    # Generate MP3 audio
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    mp3_path = tmp.name

    try:
        communicate = edge_tts.Communicate(
            text,
            EDGE_TTS_VOICE,
            rate=EDGE_TTS_RATE,
            pitch=EDGE_TTS_PITCH,
        )
        await communicate.save(mp3_path)

        # Decode MP3 → PCM samples for lip-sync
        samples, sr = await loop.run_in_executor(None, _decode_mp3_to_pcm, mp3_path)
        logger.info(f"[TTS/Edge] Audio generado: {len(samples)} muestras @ {sr}Hz")

        frame_size   = max(1, int(sr * FRAME_DURATION_S))
        total_frames = math.ceil(len(samples) / frame_size)

        async def _stream():
            for i in range(total_frames):
                chunk  = samples[i * frame_size: (i + 1) * frame_size]
                volume = compute_rms_volume(chunk)
                await manager.send_json(client_id, {
                    "state": "talking", "volume": volume,
                    "frame": i, "total_frames": total_frames,
                })
                await asyncio.sleep(FRAME_DURATION_S)

        def _play():
            if SOUNDDEVICE_AVAILABLE:
                sd.play(samples, samplerate=sr, blocking=True)
            else:
                # Use paplay/aplay to play the MP3 via ffmpeg conversion to wav
                wav_path = mp3_path.replace(".mp3", ".wav")
                subprocess.run(
                    ["ffmpeg", "-y", "-i", mp3_path, "-ar", "24000", "-ac", "1", wav_path],
                    capture_output=True,
                )
                for player in ["paplay", "aplay"]:
                    try:
                        subprocess.run([player, wav_path], timeout=60)
                        break
                    except Exception:
                        continue
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

        await asyncio.gather(loop.run_in_executor(None, _play), _stream())

    except Exception as e:
        logger.error(f"[TTS/Edge] Error: {e}")
        await _simulate_lipsync(text, client_id)
    finally:
        try:
            os.unlink(mp3_path)
        except OSError:
            pass


async def _synthesize_piper(text: str, client_id: str) -> None:
    """Piper TTS offline optimizado — voz femenina neural (es_ES-sharvard-medium)."""
    loop = asyncio.get_event_loop()
    
    # Optimización: dividir texto en oraciones para latencia reducida
    sentences = _split_into_sentences(text)
    
    try:
        import io, wave
        # Generar audio para todas las oraciones en lote
        def _generate_all() -> bytes:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                for sentence in sentences:
                    if sentence.strip():
                        _piper_voice.synthesize_wav(sentence.strip(), wf)
            buf.seek(0)
            return buf.read()

        # Generar audio en hilo secundario
        wav_bytes = await loop.run_in_executor(None, _generate_all)
        
        # Calcular duración total aproximada
        word_count = sum(len(s.split()) for s in sentences)
        duration = max(1.0, word_count / 4.0)

        # Escribir WAV temporal
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_bytes)
            wav_path = tmp.name

        # Reproducir y lip-sync en paralelo
        async def _play():
            try:
                # Intentar paplay primero (PipeWire/PulseAudio)
                proc = await asyncio.create_subprocess_exec(
                    "paplay", wav_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await proc.wait()
                
                # Si paplay falla, intentar aplay (ALSA)
                if proc.returncode != 0:
                    proc = await asyncio.create_subprocess_exec(
                        "aplay", "-q", wav_path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc.wait()
            except Exception as e:
                logger.warning(f"[TTS/Piper] Error reproduciendo: {e}")

        await asyncio.gather(_play(), _simulate_lipsync(text, client_id, duration))

    except Exception as e:
        logger.error(f"[TTS/Piper] Error: {e}")
        await _simulate_lipsync(text, client_id)
    finally:
        try:
            os.unlink(wav_path)
        except Exception:
            pass


async def _synthesize_kokoro_optimized(text: str, client_id: str) -> None:
    """Kokoro TTS optimizado para latencia reducida (procesamiento por fragmentos)."""
    loop = asyncio.get_event_loop()
    
    # Dividir texto en fragmentos manejables
    fragments = _split_text_into_fragments(text, max_length=100)
    
    if not fragments:
        await _simulate_lipsync(text, client_id)
        return
    
    try:
        import numpy as np
        from scipy.io import wavfile
        
        # Generar audio fragmento por fragmento
        all_samples = []
        sample_rate = 24000  # Frecuencia estándar para Kokoro
        
        for fragment in fragments:
            if not fragment.strip():
                continue
                
            # Generar audio para este fragmento
            def _generate_fragment(frag: str) -> np.ndarray:
                # Aquí iría la lógica de generación con Kokoro
                # Por ahora simulamos con silencio
                words = len(frag.split())
                duration = max(0.1, words / 3.0)
                samples = np.zeros(int(duration * sample_rate))
                # Agregar algo de variación para lip-sync
                t = np.linspace(0, duration, len(samples))
                samples = np.sin(2 * np.pi * 220 * t) * np.exp(-t) * 0.3
                return samples.astype(np.float32)
            
            fragment_samples = await loop.run_in_executor(
                None, _generate_fragment, fragment
            )
            all_samples.append(fragment_samples)
            
            # Enviar actualización de lip-sync para este fragmento
            frag_duration = len(fragment_samples) / sample_rate
            await _simulate_lipsync(fragment, client_id, frag_duration)
        
        if all_samples:
            # Concatenar todos los samples
            final_samples = np.concatenate(all_samples)
            
            # Guardar y reproducir
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wavfile.write(tmp.name, sample_rate, final_samples)
                wav_path = tmp.name
            
            async def _play():
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "paplay", wav_path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc.wait()
                except Exception:
                    pass  # Ignorar errores de reproducción
            
            await _play()
            
            try:
                os.unlink(wav_path)
            except Exception:
                pass
    
    except Exception as e:
        logger.error(f"[TTS/Kokoro] Error: {e}")
        await _simulate_lipsync(text, client_id)


async def _synthesize_pyttsx3(text: str, client_id: str) -> None:
    loop     = asyncio.get_event_loop()
    duration = max(1.0, len(text.split()) / 3.5)
    await asyncio.gather(
        loop.run_in_executor(None, lambda: (_tts_engine.say(text), _tts_engine.runAndWait())),
        _simulate_lipsync(text, client_id, duration),
    )


async def _simulate_lipsync(text: str, client_id: str, duration: float | None = None) -> None:
    if duration is None:
        duration = max(1.5, len(text.split()) / 3.5)
    frames = int(duration * 30)
    for i in range(frames):
        t        = i / frames
        envelope = min(t * 5, 1.0, (1 - t) * 5)
        volume   = round(abs(math.sin(i * 0.7)) * envelope * 0.8, 4)
        await manager.send_json(client_id, {
            "state": "talking", "volume": volume,
            "frame": i, "total_frames": frames,
        })
        await asyncio.sleep(FRAME_DURATION_S)


# ═══════════════════════════════════════════════════════════════════════════════
#  APLICACIÓN FASTAPI
# ═══════════════════════════════════════════════════════════════════════════════

async def _warmup_ollama(backend) -> None:
    """Pre-carga el modelo Ollama en RAM/GPU para eliminar latencia cold-start."""
    try:
        import httpx
        async with httpx.AsyncClient(base_url=backend.base_url, timeout=httpx.Timeout(60.0)) as client:
            await client.post("/api/generate", json={
                "model": backend.model,
                "prompt": "hi",
                "stream": False,
                "keep_alive": "10m",
                "options": {"num_predict": 1, "num_ctx": 512},
            })
        logger.info(f"[Warmup] Modelo '{backend.model}' precargado en memoria ✓")
    except Exception as e:
        logger.warning(f"[Warmup] No se pudo precargar Ollama: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global AI_ROUTER
    global ADVANCED_FEATURES

    logger.info("=" * 64)
    logger.info("  SYLIX OS CORE ASSISTANT — Iniciando...")
    logger.info(f"  Gemini:    {'✓ ' + GEMINI_MODEL    if GEMINI_API_KEY    else '✗ No configurado'}")
    logger.info(f"  Anthropic: {'✓ ' + ANTHROPIC_MODEL if ANTHROPIC_API_KEY else '✗ No configurado'}")
    logger.info(f"  Ollama:    ✓ {OLLAMA_MODEL} @ {OLLAMA_BASE_URL} (offline)")
    tts_info = []
    if EDGE_TTS_AVAILABLE:
        tts_info.append(f"edge-tts ({EDGE_TTS_VOICE}) [online]")
    if PIPER_AVAILABLE:
        tts_info.append("Piper es_ES-sharvard [offline neural ✓]")
    if PYTTSX3_AVAILABLE:
        tts_info.append("pyttsx3 [offline fallback]")
    logger.info(f"  TTS:       {' | '.join(tts_info) or 'Simulado'}")
    logger.info("=" * 64)

    # Inicializar el router
    AI_ROUTER = AIRouter(
        gemini_api_key    = GEMINI_API_KEY,
        anthropic_api_key = ANTHROPIC_API_KEY,
        gemini_model      = GEMINI_MODEL,
        anthropic_model   = ANTHROPIC_MODEL,
        ollama_base_url   = OLLAMA_BASE_URL,
        ollama_model      = OLLAMA_MODEL,
    )

    # Link connectivity cache for dynamic TTS switching
    from ai_backends import _CONNECTIVITY_CACHE as _ai_cache
    _CONNECTIVITY_CACHE.update(_ai_cache)
    # Share the same dict reference
    import main as _self
    _self._CONNECTIVITY_CACHE = _ai_cache

    # Pre-check de red al inicio
    online = await check_internet()
    logger.info(f"  Red:       {'✓ Online' if online else '✗ Offline — usando Ollama local'}")

    # Pre-warm Ollama model (load into memory for instant first response)
    if await AI_ROUTER.ollama_backend.is_available():
        asyncio.create_task(_warmup_ollama(AI_ROUTER.ollama_backend))

    # ── Inicializar características avanzadas ────────────────────────────────
    if ADVANCED_FEATURES_AVAILABLE:
        try:
            # Cargar configuración desde archivo
            config_path = "advanced_config.json"
            advanced_config = {}
            if os.path.exists(config_path):
                import json
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                logger.info("[Advanced] Configuración cargada desde advanced_config.json")
                
                # Extraer configuración de características avanzadas
                advanced_features_config = config.get("advanced_features", {})
                
                # Convertir a formato plano que espera AdvancedFeatures
                flat_config = {}
                if "activity_monitor" in advanced_features_config:
                    flat_config["activity_monitor_enabled"] = advanced_features_config["activity_monitor"].get("enabled", False)
                
                if "proactive_thinking" in advanced_features_config:
                    flat_config["proactive_thinking_enabled"] = advanced_features_config["proactive_thinking"].get("enabled", False)
                    
                advanced_config = flat_config
                
            else:
                logger.info("[Advanced] Configuración por defecto (archivo no encontrado)")
            
            ADVANCED_FEATURES = get_advanced_features(advanced_config)
            ADVANCED_FEATURES.start_integration()
            
            # Log estado de características avanzadas
            features_status = ADVANCED_FEATURES.get_feature_status()
            memory_enabled = features_status["memory"]["enabled"]
            activity_enabled = features_status["activity_monitor"]["enabled"]
            thinking_enabled = features_status["proactive_thinking"]["enabled"]
            
            logger.info("[Advanced] Características avanzadas:")
            logger.info(f"  Memoria:        {'✓ SIEMPRE' if memory_enabled else '✗'}")
            logger.info(f"  Monitor:        {'✓ ACTIVO' if activity_enabled else '✗ OPcional'}")
            logger.info(f"  Pensamiento:    {'✓ ACTIVO' if thinking_enabled else '✗ OPcional'}")
            
        except Exception as e:
            logger.error(f"[Advanced] Error inicializando características: {e}")
            ADVANCED_FEATURES = None
    else:
        logger.warning("[Advanced] Características avanzadas no disponibles (import falló)")

    logger.info("=" * 64)

    yield
    # Apagar características avanzadas al cerrar
    if ADVANCED_FEATURES:
        ADVANCED_FEATURES.stop_integration()
        logger.info("[Advanced] Características avanzadas detenidas")
    logger.info("[Sylix] Apagando servidor...")


app = FastAPI(
    title="Sylix OS Core Assistant",
    description="Agente VTuber autónomo — Gemini + Claude + Ollama local",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Archivos estáticos
for d in ("static", "models"):
    if os.path.exists(d):
        app.mount(f"/{d}", StaticFiles(directory=d), name=d)


# ─── Rutas HTTP ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    if os.path.exists("index.html"):
        with open("index.html", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Sylix OS — index.html no encontrado</h1>", status_code=404)


@app.get("/health")
async def health_check():
    online  = await check_internet()
    ollama_ok = await AI_ROUTER.ollama_backend.is_available() if AI_ROUTER else False
    return {
        "status":        "online",
        "service":       "Sylix OS Core Assistant",
        "version":       "1.1.0",
        "network":       "online" if online else "offline",
        "backends": {
            "gemini":    bool(GEMINI_API_KEY),
            "anthropic": bool(ANTHROPIC_API_KEY),
            "ollama":    {"available": ollama_ok, "model": OLLAMA_MODEL},
        },
        "active_backend": _current_backend_name(),
        "tts":            _get_tts_backend(),
        "connections":    len(manager.active_connections),
    }


@app.get("/network")
async def network_status():
    """Fuerza re-evaluación de conectividad."""
    invalidate_connectivity_cache()
    online = await check_internet()
    return {"online": online, "timestamp": time.time()}


@app.get("/backends")
async def list_backends():
    """Lista los backends configurados y su estado."""
    online = await check_internet()
    ollama_ok = await AI_ROUTER.ollama_backend.is_available() if AI_ROUTER else False
    return {
        "internet": online,
        "backends": [
            {
                "name":      "Gemini",
                "type":      "cloud",
                "model":     GEMINI_MODEL,
                "available": bool(GEMINI_API_KEY) and online,
                "priority":  1,
            },
            {
                "name":      "Anthropic Claude",
                "type":      "cloud",
                "model":     ANTHROPIC_MODEL,
                "available": bool(ANTHROPIC_API_KEY) and online,
                "priority":  2,
            },
            {
                "name":      "Ollama",
                "type":      "local",
                "model":     OLLAMA_MODEL,
                "available": ollama_ok,
                "priority":  3,
                "url":       OLLAMA_BASE_URL,
            },
        ],
    }


@app.get("/api/models")
async def list_live2d_models():
    """
    Escanea la carpeta models/ y lista todos los modelos Cubism 4 (.model3.json)
    disponibles para el avatar Live2D.
    """
    found_models = []
    models_dir = "models"
    if os.path.exists(models_dir):
        for root, dirs, files in os.walk(models_dir):
            for file in files:
                if file.endswith(".model3.json"):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, start=".")
                    web_path = "/" + rel_path.replace("\\", "/")
                    folder_name = os.path.basename(root)
                    # Evitar duplicados por symlinks
                    if not any(m["path"] == web_path for m in found_models):
                        found_models.append({
                            "name": folder_name.replace("_", " ").title(),
                            "file": file,
                            "path": web_path,
                            "dir": folder_name,
                        })

    # Priorizar design_genius_white si existe
    default_model = None
    for m in found_models:
        if "design_genius" in m["dir"].lower():
            default_model = m["path"]
            break
    if not default_model and found_models:
        default_model = found_models[0]["path"]

    return {
        "models": found_models,
        "default": default_model or "/models/design_genius_white/Design_genius(1).model3.json",
    }


# ─── Endpoints de Características Avanzadas ──────────────────────────────────

@app.get("/api/advanced/status")
async def get_advanced_features_status():
    """Obtener estado de características avanzadas."""
    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
        return {
            "available": False,
            "message": "Características avanzadas no disponibles",
            "features": {}
        }
    
    try:
        features_status = ADVANCED_FEATURES.get_feature_status()
        system_stats = ADVANCED_FEATURES.get_system_stats()
        
        # Obtener sugerencias proactivas
        suggestions = []
        if features_status.get("proactive_thinking", {}).get("enabled", False):
            suggestions = ADVANCED_FEATURES.get_proactive_suggestions(limit=3)
        
        return {
            "available": True,
            "message": "Características avanzadas activas",
            "features": features_status,
            "stats": system_stats,
            "suggestions": suggestions,
            "integration_running": ADVANCED_FEATURES.is_running if hasattr(ADVANCED_FEATURES, "is_running") else False
        }
    except Exception as e:
        logger.error(f"[Advanced] Error getting status: {e}")
        return {
            "available": False,
            "error": str(e),
            "features": {}
        }


@app.post("/api/advanced/features/{feature_name}/enable")
async def enable_advanced_feature(feature_name: str):
    """Habilitar una característica avanzada."""
    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
        return {"success": False, "message": "Características avanzadas no disponibles"}
    
    if feature_name == "memory":
        return {"success": True, "message": "La memoria está siempre activa y no puede deshabilitarse"}
    
    try:
        success = ADVANCED_FEATURES.enable_feature(feature_name)
        if success:
            return {
                "success": True,
                "message": f"Característica '{feature_name}' habilitada",
                "feature": feature_name,
                "enabled": True
            }
        else:
            return {
                "success": False,
                "message": f"No se pudo habilitar la característica '{feature_name}'",
                "feature": feature_name,
                "enabled": False
            }
    except Exception as e:
        logger.error(f"[Advanced] Error enabling feature {feature_name}: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/advanced/features/{feature_name}/disable")
async def disable_advanced_feature(feature_name: str):
    """Deshabilitar una característica avanzada."""
    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
        return {"success": False, "message": "Características avanzadas no disponibles"}
    
    if feature_name == "memory":
        return {"success": False, "message": "La memoria está siempre activa y no puede deshabilitarse"}
    
    try:
        success = ADVANCED_FEATURES.disable_feature(feature_name)
        if success:
            return {
                "success": True,
                "message": f"Característica '{feature_name}' deshabilitada",
                "feature": feature_name,
                "enabled": False
            }
        else:
            return {
                "success": False,
                "message": f"No se pudo deshabilitar la característica '{feature_name}'",
                "feature": feature_name,
                "enabled": True
            }
    except Exception as e:
        logger.error(f"[Advanced] Error disabling feature {feature_name}: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/advanced/memory/context")
async def get_memory_context(window_minutes: int = 60):
    """Obtener contexto de memoria reciente."""
    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
        return {"available": False, "context": ""}
    
    try:
        context = ADVANCED_FEATURES.get_conversation_context(window_minutes)
        return {
            "available": True,
            "context": context,
            "window_minutes": window_minutes,
            "length": len(context)
        }
    except Exception as e:
        logger.error(f"[Advanced] Error getting memory context: {e}")
        return {"available": False, "error": str(e)}


@app.get("/api/advanced/activity/summary")
async def get_activity_summary(hours: int = 24):
    """Obtener resumen de actividad."""
    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
        return {"available": False, "summary": {}}
    
    try:
        summary = ADVANCED_FEATURES.get_activity_summary(hours)
        return {
            "available": True,
            "summary": summary,
            "hours": hours
        }
    except Exception as e:
        logger.error(f"[Advanced] Error getting activity summary: {e}")
        return {"available": False, "error": str(e)}


@app.get("/api/advanced/suggestions")
async def get_proactive_suggestions(limit: int = 3):
    """Obtener sugerencias proactivas."""
    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
        return {"available": False, "suggestions": []}
    
    try:
        suggestions = ADVANCED_FEATURES.get_proactive_suggestions(limit)
        return {
            "available": True,
            "suggestions": suggestions,
            "count": len(suggestions)
        }
    except Exception as e:
        logger.error(f"[Advanced] Error getting proactive suggestions: {e}")
        return {"available": False, "error": str(e)}


@app.post("/api/advanced/suggestions/{suggestion_id}/acknowledge")
async def acknowledge_suggestion(suggestion_id: str, response: Optional[str] = None):
    """Reconocer/responder a una sugerencia proactiva."""
    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
        return {"success": False, "message": "Características avanzadas no disponibles"}
    
    try:
        success = ADVANCED_FEATURES.acknowledge_suggestion(suggestion_id, response)
        if success:
            return {
                "success": True,
                "message": "Sugerencia reconocida",
                "suggestion_id": suggestion_id
            }
        else:
            return {
                "success": False,
                "message": "No se pudo reconocer la sugerencia",
                "suggestion_id": suggestion_id
            }
    except Exception as e:
        logger.error(f"[Advanced] Error acknowledging suggestion: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/advanced/user/preferences")
async def get_user_preferences():
    """Obtener preferencias del usuario aprendidas."""
    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
        return {"available": False, "preferences": {}}
    
    try:
        preferences = ADVANCED_FEATURES.get_user_preferences()
        return {
            "available": True,
            "preferences": preferences
        }
    except Exception as e:
        logger.error(f"[Advanced] Error getting user preferences: {e}")
        return {"available": False, "error": str(e)}


@app.post("/api/advanced/cleanup")
async def cleanup_advanced_data(days_to_keep: int = 7):
    """Limpiar datos antiguos de características avanzadas."""
    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
        return {"success": False, "message": "Características avanzadas no disponibles"}
    
    try:
        results = ADVANCED_FEATURES.cleanup(days_to_keep)
        return {
            "success": True,
            "message": "Limpieza completada",
            "days_to_keep": days_to_keep,
            "results": results
        }
    except Exception as e:
        logger.error(f"[Advanced] Error cleaning up data: {e}")
        return {"success": False, "error": str(e)}


@app.get("/advanced")
async def serve_advanced_panel():
    """Servir el panel de control de características avanzadas."""
    if os.path.exists("advanced_panel.html"):
        with open("advanced_panel.html", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Panel de características avanzadas no encontrado</h1>", status_code=404)


def _current_backend_name() -> str:
    if AI_ROUTER is None:
        return "none"
    if AI_ROUTER._last_backend == BackendType.GEMINI:
        return f"Gemini/{GEMINI_MODEL}"
    if AI_ROUTER._last_backend == BackendType.ANTHROPIC:
        return f"Anthropic/{ANTHROPIC_MODEL}"
    if AI_ROUTER._last_backend == BackendType.OLLAMA:
        return f"Ollama/{OLLAMA_MODEL}"
    return "none"


# ─── WebSocket Principal ──────────────────────────────────────────────────────

SESSION_HISTORIES: dict[str, list[dict]] = {}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Canal WebSocket principal.

    Entrada (JSON del frontend):
        {"type": "message",       "text": "..."}
        {"type": "ping"}
        {"type": "clear_history"}
        {"type": "network_check"}

    Salida (JSON al frontend):
        {"state": "thinking"|"executing"|"talking"|"idle"|"error"}
        {"type": "response",        "text": "...", "backend": "Gemini"}
        {"type": "network_status",  "online": bool}
        {"type": "tool_result",     "tool": "...", "result": "..."}
        {"state": "talking",        "volume": float, "frame": int}
        {"state": "idle",           "volume": 0.0}
    """
    client_id = str(uuid.uuid4())
    await manager.connect(websocket, client_id)
    SESSION_HISTORIES[client_id] = []

    # Bienvenida con estado de red
    online = await check_internet()
    await manager.send_json(client_id, {
        "type":    "connected",
        "client_id": client_id,
        "state":   "idle",
        "network": "online" if online else "offline",
        "backend": _current_backend_name() or ("Gemini" if GEMINI_API_KEY else "Claude" if ANTHROPIC_API_KEY else "Ollama"),
        "message": "Sylix OS Core conectado.",
    })

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"type": "message", "text": raw}

            msg_type = data.get("type", "message")

            # ── Keepalive ─────────────────────────────────────────────────────
            if msg_type == "ping":
                await manager.send_json(client_id, {"type": "pong", "ts": time.time()})
                continue

            # ── Forzar re-check de red ────────────────────────────────────────
            if msg_type == "network_check":
                invalidate_connectivity_cache()
                online = await check_internet()
                await manager.send_json(client_id, {
                    "type":    "network_status",
                    "online":  online,
                    "backend": _current_backend_name(),
                })
                continue

            # ── Comandos de características avanzadas ──────────────────────────
            if msg_type == "advanced_features":
                action = data.get("action", "")
                
                if action == "get_status":
                    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
                        await manager.send_json(client_id, {
                            "type": "advanced_features_status",
                            "available": False,
                            "message": "Características avanzadas no disponibles"
                        })
                    else:
                        try:
                            features_status = ADVANCED_FEATURES.get_feature_status()
                            system_stats = ADVANCED_FEATURES.get_system_stats()
                            suggestions = []
                            if features_status.get("proactive_thinking", {}).get("enabled", False):
                                suggestions = ADVANCED_FEATURES.get_proactive_suggestions(limit=3)
                            
                            await manager.send_json(client_id, {
                                "type": "advanced_features_status",
                                "available": True,
                                "features": features_status,
                                "stats": system_stats,
                                "suggestions": suggestions,
                                "integration_running": ADVANCED_FEATURES.is_running if hasattr(ADVANCED_FEATURES, "is_running") else False
                            })
                        except Exception as e:
                            logger.error(f"[WS/Advanced] Error getting status: {e}")
                            await manager.send_json(client_id, {
                                "type": "advanced_features_status",
                                "available": False,
                                "error": str(e)
                            })
                    continue
                
                elif action == "enable_feature":
                    feature_name = data.get("feature_name", "")
                    if not feature_name:
                        await manager.send_json(client_id, {
                            "type": "advanced_features_error",
                            "message": "No se especificó nombre de característica"
                        })
                        continue
                    
                    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": False,
                            "message": "Características avanzadas no disponibles"
                        })
                        continue
                    
                    try:
                        success = ADVANCED_FEATURES.enable_feature(feature_name)
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": success,
                            "action": "enable_feature",
                            "feature_name": feature_name,
                            "message": f"Característica '{feature_name}' habilitada" if success else f"No se pudo habilitar '{feature_name}'"
                        })
                    except Exception as e:
                        logger.error(f"[WS/Advanced] Error enabling feature: {e}")
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": False,
                            "action": "enable_feature",
                            "error": str(e)
                        })
                    continue
                
                elif action == "disable_feature":
                    feature_name = data.get("feature_name", "")
                    if not feature_name:
                        await manager.send_json(client_id, {
                            "type": "advanced_features_error",
                            "message": "No se especificó nombre de característica"
                        })
                        continue
                    
                    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": False,
                            "message": "Características avanzadas no disponibles"
                        })
                        continue
                    
                    try:
                        success = ADVANCED_FEATURES.disable_feature(feature_name)
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": success,
                            "action": "disable_feature",
                            "feature_name": feature_name,
                            "message": f"Característica '{feature_name}' deshabilitada" if success else f"No se pudo deshabilitar '{feature_name}'"
                        })
                    except Exception as e:
                        logger.error(f"[WS/Advanced] Error disabling feature: {e}")
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": False,
                            "action": "disable_feature",
                            "error": str(e)
                        })
                    continue
                
                elif action == "get_suggestions":
                    limit = data.get("limit", 3)
                    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
                        await manager.send_json(client_id, {
                            "type": "advanced_features_suggestions",
                            "available": False,
                            "suggestions": []
                        })
                        continue
                    
                    try:
                        suggestions = ADVANCED_FEATURES.get_proactive_suggestions(limit)
                        await manager.send_json(client_id, {
                            "type": "advanced_features_suggestions",
                            "available": True,
                            "suggestions": suggestions,
                            "count": len(suggestions)
                        })
                    except Exception as e:
                        logger.error(f"[WS/Advanced] Error getting suggestions: {e}")
                        await manager.send_json(client_id, {
                            "type": "advanced_features_suggestions",
                            "available": False,
                            "error": str(e)
                        })
                    continue
                
                elif action == "acknowledge_suggestion":
                    suggestion_id = data.get("suggestion_id", "")
                    response = data.get("response", None)
                    
                    if not suggestion_id:
                        await manager.send_json(client_id, {
                            "type": "advanced_features_error",
                            "message": "No se especificó ID de sugerencia"
                        })
                        continue
                    
                    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": False,
                            "message": "Características avanzadas no disponibles"
                        })
                        continue
                    
                    try:
                        success = ADVANCED_FEATURES.acknowledge_suggestion(suggestion_id, response)
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": success,
                            "action": "acknowledge_suggestion",
                            "suggestion_id": suggestion_id,
                            "message": "Sugerencia reconocida" if success else "No se pudo reconocer la sugerencia"
                        })
                    except Exception as e:
                        logger.error(f"[WS/Advanced] Error acknowledging suggestion: {e}")
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": False,
                            "action": "acknowledge_suggestion",
                            "error": str(e)
                        })
                    continue
                
                elif action == "cleanup":
                    days_to_keep = data.get("days_to_keep", 7)
                    if not ADVANCED_FEATURES_AVAILABLE or not ADVANCED_FEATURES:
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": False,
                            "message": "Características avanzadas no disponibles"
                        })
                        continue
                    
                    try:
                        results = ADVANCED_FEATURES.cleanup(days_to_keep)
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": True,
                            "action": "cleanup",
                            "results": results,
                            "message": "Limpieza completada"
                        })
                    except Exception as e:
                        logger.error(f"[WS/Advanced] Error cleaning up: {e}")
                        await manager.send_json(client_id, {
                            "type": "advanced_features_result",
                            "success": False,
                            "action": "cleanup",
                            "error": str(e)
                        })
                    continue
                
                # Comando desconocido
                await manager.send_json(client_id, {
                    "type": "advanced_features_error",
                    "message": f"Acción desconocida: {action}"
                })
                continue

            # ── Limpiar historial ─────────────────────────────────────────────
            if msg_type == "clear_history":
                SESSION_HISTORIES[client_id] = []
                await manager.send_json(client_id, {"type": "history_cleared", "state": "idle"})
                continue

            # ── Mensaje al agente ─────────────────────────────────────────────
            if msg_type == "message":
                user_text = data.get("text", "").strip()
                if not user_text:
                    continue

                if AI_ROUTER is None:
                    await manager.send_json(client_id, {
                        "state":   "error",
                        "message": "Router de IA no inicializado.",
                    })
                    continue

                history = SESSION_HISTORIES.get(client_id, [])

                try:
                    final_response, updated_history = await run_agent_turn(
                        user_message=user_text,
                        client_id=client_id,
                        history=history,
                    )
                    SESSION_HISTORIES[client_id] = updated_history
                except Exception as e:
                    logger.exception(f"[WS] Error en run_agent_turn: {e}")
                    await manager.send_json(client_id, {
                        "state":   "error",
                        "message": f"Error: {e}",
                    })
                continue

            await manager.send_json(client_id, {
                "type":    "error",
                "message": f"Tipo desconocido: {msg_type!r}",
            })

    except WebSocketDisconnect:
        logger.info(f"[WS] {client_id[:8]}… desconectado.")
    except Exception as e:
        logger.exception(f"[WS] Error para {client_id[:8]}: {e}")
    finally:
        manager.disconnect(client_id)
        SESSION_HISTORIES.pop(client_id, None)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        log_level="info",
        reload=False,
    )
