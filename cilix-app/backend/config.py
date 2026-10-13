#!/usr/bin/env python3
"""
Módulo de Configuración Centralizada de Cilix
=============================================
Define todos los parámetros de ejecución en un único punto, con especial
atención al LÍMITE ESTRICTO DE 8 GB DE RAM del equipo (Pop!_OS).

Nada de APIs de pago ni servicios en la nube: todo se ejecuta 100% local.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Rutas base del proyecto ──────────────────────────────────────────────────
# ROOT_DIR apunta a la carpeta `cilix-app` (dos niveles por encima de este archivo)
ROOT_DIR = Path(__file__).resolve().parent.parent

# Carga variables de entorno desde <cilix-app>/.env si existe (12Factor local).
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
except Exception:  # noqa: BLE001  (python-dotenv es opcional en runtime)
    pass
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
STATIC_DIR = ROOT_DIR / "static"
MODELS_DIR = ROOT_DIR / "models"
CONFIG_DIR = ROOT_DIR / "config"


def _env(key: str, default):
    """Lee una variable de entorno con valor por defecto tipado."""
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    # Conversión de tipo sencilla según el valor por defecto
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw


@dataclass
class Settings:
    """
    Parámetros globales de Cilix.

    Todos los valores pueden sobreescribirse mediante variables de entorno
    (ver `.env.example`), lo que facilita el despliegue sin tocar código.
    """

    # ── Red / servidor ────────────────────────────────────────────────────
    host: str = _env("CILIX_HOST", "127.0.0.1")
    port: int = _env("CILIX_PORT", 8765)

    # ── Límites de recursos (PROTECCIÓN DE 8 GB) ───────────────────────────
    total_ram_limit_gb: float = _env("CILIX_RAM_LIMIT_GB", 8.0)
    # Umbral de RAM (%) por encima del cual Re se descarga y se rechazan
    # cargas pesadas nuevas para no colapsar el sistema.
    ram_critical_percent: float = _env("CILIX_RAM_CRITICAL", 88.0)
    ram_warning_percent: float = _env("CILIX_RAM_WARNING", 78.0)
    # Umbral de EMERGENCIA (%): por encima se descarga también Ri para no tumbar
    # el equipo. Ri se recarga sola en el siguiente mensaje.
    ram_emergency_percent: float = _env("CILIX_RAM_EMERGENCY", 93.0)

    # ── Cerebro (Ollama local) ──────────────────────────────────────────────
    ollama_url: str = _env("OLLAMA_URL", "http://localhost:11434")
    # Cerebro UNICO por defecto (bajo consumo). Ri es el modelo residente.
    # Para ahorrar ~600 MB mas: CILIX_RI_MODEL=llama3.2:1b (y `ollama pull`).
    ri_model: str = _env("CILIX_RI_MODEL", "qwen2.5:1.5b")          # <1.5 GB
    re_model: str = _env("CILIX_RE_MODEL", "deepseek-coder:1.3b")   # ~3 GB
    # dual_brain=False: NUNCA se carga Re (se ahorra ~1 GB). Dejar True para
    # volver al modo dual (Ri residente + Re bajo demanda para código).
    dual_brain: bool = _env("CILIX_DUAL_BRAIN", False)
    # keep_alive CORTO por defecto: libera RAM rápido cuando el modelo no se usa.
    ri_keep_alive: str = _env("CILIX_RI_KEEP_ALIVE", "2m")          # residente
    re_keep_alive: str = _env("CILIX_RE_KEEP_ALIVE", "20s")         # bajo demanda

    # ── Ajuste fino de RAM en Ollama (la mayor palanca de ahorro) ────────────
    # num_ctx pequeño reduce drásticamente la caché KV (RAM por conversación).
    ollama_num_ctx: int = _env("CILIX_OLLAMA_NUM_CTX", 1024)
    ollama_num_batch: int = _env("CILIX_OLLAMA_NUM_BATCH", 128)
    # Tokens máximos de salida (antes 512). Menos = menos RAM y más rápido.
    ri_num_predict: int = _env("CILIX_RI_NUM_PREDICT", 220)
    re_num_predict: int = _env("CILIX_RE_NUM_PREDICT", 400)
    # use_mmap=True mapea el modelo a disco en vez de cargarlo entero en RAM.
    ollama_use_mmap: bool = _env("CILIX_OLLAMA_USE_MMAP", True)
    # Carga de pesos cuantizados en 4 bits (menor huella; requiere modelo Q4).
    ollama_num_thread: int = _env("CILIX_OLLAMA_NUM_THREAD", 2)

    # ── Motor de voz ────────────────────────────────────────────────────────
    whisper_model: str = _env("CILIX_WHISPER_MODEL", "tiny")        # STT ligero
    whisper_language: str = _env("CILIX_WHISPER_LANG", "es")
    # Backend TTS preferido: 'kokoro' (natural, femenina) o 'piper' (ligero).
    tts_backend: str = _env("CILIX_TTS_BACKEND", "kokoro")
    # Voz FEMENINA en español (Piper, local, ligera ~63 MB, poco robótica).
    piper_voice_path: str = _env(
        "CILIX_PIPER_VOICE",
        str(MODELS_DIR / "piper" / "es_ES-davefx-medium.onnx"),
    )
    # Kokoro: TTS natural (voz femenina 'ef_dora'). Se carga de forma diferida.
    kokoro_model_path: str = _env(
        "CILIX_KOKORO_MODEL", str(MODELS_DIR / "kokoro" / "kokoro-v1.0.onnx"))
    kokoro_voices_path: str = _env(
        "CILIX_KOKORO_VOICES", str(MODELS_DIR / "kokoro" / "voices-v1.0.bin"))
    kokoro_voice: str = _env("CILIX_KOKORO_VOICE", "ef_dora")       # femenina es
    kokoro_lang: str = _env("CILIX_KOKORO_LANG", "es")
    kokoro_speed: float = _env("CILIX_KOKORO_SPEED", 1.25)  # >1 = más rápido/agudo
    # Precarga el motor de voz tras arrancar (evita el retardo de la 1ª frase).
    # Se salta si la RAM está crítica. false = carga solo al primer uso.
    voice_warmup: bool = _env("CILIX_VOICE_WARMUP", True)
    # Tono (+semitonas, WSOLA) sobre la voz Kokoro. 0 = ef_dora NATURAL
    # (el punto de subida se logra con CILIX_KOKORO_SPEED). Subir a 1-2
    # si se quiere un timbre aún más agudo con duración intacta.
    kokoro_pitch: float = _env("CILIX_KOKORO_PITCH", 0.0)
    # Hilos de ONNXRuntime para Kokoro (menos hilos = menos RAM del arena).
    ort_threads: int = _env("CILIX_ORT_THREADS", 2)
    # Segundos de inactividad tras los cuales se DESCARGAN Kokoro/Whisper de
    # RAM (~1.5-2 GB liberados en reposo; se recargan solos al volver a usarlos).
    voice_idle_release_seconds: int = _env("CILIX_VOICE_IDLE_RELEASE", 300)

    # ── Personalidad proactiva (pensamiento propio + ánimo) ──────────────
    # Ri comenta cosas por su cuenta cuando llevas un rato sin interactuar.
    proactive_enabled: bool = _env("CILIX_PROACTIVE", True)
    proactive_idle_seconds: int = _env("CILIX_PROACTIVE_IDLE", 90)       # idle antes de hablar
    proactive_min_gap_seconds: int = _env("CILIX_PROACTIVE_MIN_GAP", 240)  # gap entre frases
    proactive_max_per_hour: int = _env("CILIX_PROACTIVE_MAX_HOUR", 6)    # tope por hora
    proactive_quiet_start: int = _env("CILIX_PROACTIVE_QUIET_START", 23)  # hora silencio
    proactive_quiet_end: int = _env("CILIX_PROACTIVE_QUIET_END", 8)
    proactive_voice: bool = _env("CILIX_PROACTIVE_VOICE", True)          # texto + voz

    # ── Percepción / control ────────────────────────────────────────────────
    vision_enabled: bool = _env("CILIX_VISION_ENABLED", False)      # OFF por defecto (RAM)
    voice_enabled: bool = _env("CILIX_VOICE_ENABLED", True)

    # ── Modo desarrollo ─────────────────────────────────────────────────────
    dev_mode: bool = _env("CILIX_DEV", False)

    def as_public_dict(self) -> dict:
        """Configuración segura para exponer al frontend (sin rutas absolutas)."""
        return {
            "ri_model": self.ri_model,
            "re_model": self.re_model,
            "dual_brain": self.dual_brain,
            "voice_enabled": self.voice_enabled,
            "vision_enabled": self.vision_enabled,
            "ram_limit_gb": self.total_ram_limit_gb,
            "dev_mode": self.dev_mode,
            "proactive_enabled": self.proactive_enabled,
            "proactive_voice": self.proactive_voice,
        }


# Instancia global única
settings = Settings()


def log_startup_summary() -> None:
    """Imprime un resumen de la configuración al arrancar el servidor."""
    logger.info("⚙️  ── Configuración de Cilix ──")
    logger.info(f"   Servidor       : http://{settings.host}:{settings.port}")
    logger.info(f"   WebSocket      : ws://{settings.host}:{settings.port}/ws")
    logger.info(f"   Ollama         : {settings.ollama_url}")
    if settings.dual_brain:
        logger.info(f"   Cerebro Ri     : {settings.ri_model} (residente)")
        logger.info(f"   Cerebro Re     : {settings.re_model} (bajo demanda)")
    else:
        logger.info(f"   Cerebro unico  : {settings.ri_model} (Re desactivada)")
    logger.info(f"   Voz (TTS)      : {settings.tts_backend} "
                f"(respaldo Piper: {Path(settings.piper_voice_path).name})")
    logger.info(f"   STT (Whisper)  : {settings.whisper_model}")
    logger.info(f"   Límite RAM     : {settings.total_ram_limit_gb} GB "
                f"(crítico {settings.ram_critical_percent}%)")
    logger.info(f"   Visión         : {'ON' if settings.vision_enabled else 'OFF'}")
    logger.info(f"   Proactividad   : {'ON' if settings.proactive_enabled else 'OFF'} "
                f"(idle {settings.proactive_idle_seconds}s · voz "
                f"{'ON' if settings.proactive_voice else 'OFF'})")
    logger.info("   100% LOCAL / OFFLINE · Sin APIs de pago")
