#!/usr/bin/env python3
"""
Motor de Audio de Cilix — STT + TTS 100%% local
================================================
· STT : faster-whisper (modelo 'tiny', CPU) para dictado al español.
· TTS : Piper con voz femenina en español (`es_ES-sharvard-medium`).
· Lip-sync : se extrae una envolvente de volumen por fotograma del audio
             generado, para que el avatar sincronice la boca.

Todo funciona offline. Si una dependencia no está instalada, el motor degrada
de forma elegante (audio simulado / sin transcripción) sin tumbar el servidor.
"""

import asyncio
import base64
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import soundfile as sf
except Exception:  # noqa: BLE001
    sf = None

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except Exception:  # noqa: BLE001
    WHISPER_AVAILABLE = False

try:
    from piper import PiperVoice
    PIPER_AVAILABLE = True
except Exception:  # noqa: BLE001
    PIPER_AVAILABLE = False

try:
    from kokoro_onnx import Kokoro
    KOKORO_AVAILABLE = True
except Exception:  # noqa: BLE001
    KOKORO_AVAILABLE = False


def _patch_numpy_pickle():
    """
    Permite cargar voices-v1.0.bin (dict pickled) con numpy>=2, que por defecto
    rechaza datos pickle. Se aplica solo alrededor de la carga de Kokoro.
    """
    orig = np.load

    def loader(*a, **k):
        r = orig(*a, **{**k, "allow_pickle": True})
        if isinstance(r, np.ndarray) and r.dtype == object and r.shape == ():
            return r.item()
        return r
    return orig, loader


from config import settings

logger = logging.getLogger(__name__)


@dataclass
class AudioConfig:
    """Parámetros del motor de audio."""
    sample_rate: int = 16000          # entrada STT
    tts_sample_rate: int = 22050      # salida por defecto (Piper)
    channels: int = 1
    whisper_model: str = settings.whisper_model
    whisper_language: str = settings.whisper_language
    piper_voice_path: str = settings.piper_voice_path
    tts_backend: str = settings.tts_backend
    kokoro_model_path: str = settings.kokoro_model_path
    kokoro_voices_path: str = settings.kokoro_voices_path
    kokoro_voice: str = settings.kokoro_voice
    kokoro_lang: str = settings.kokoro_lang
    kokoro_speed: float = settings.kokoro_speed
    # Nº de fotogramas de lip-sync por segundo de audio
    lipsync_fps: int = 25


@dataclass
class SpeechResult:
    """Resultado de una síntesis de voz."""
    wav_b64: str          # audio WAV codificado en base64 para el navegador
    duration: float       # segundos
    volume_frames: List[float]  # envolvente 0..1 para sincronizar la boca
    sample_rate: int


class AudioEngine:
    """Coordinador de voz (escuchar + hablar + sincronizar labios)."""

    def __init__(self, config: Optional[AudioConfig] = None):
        self.config = config or AudioConfig()
        self.temp_dir = Path(tempfile.gettempdir()) / "cilix_audio"
        self.temp_dir.mkdir(exist_ok=True)

        self.whisper: Optional[Any] = None
        self.piper: Optional[Any] = None
        self.kokoro: Optional[Any] = None
        self.is_speaking = False

        logger.info(
            "🎵 AudioEngine (Whisper=%s, Kokoro=%s, Piper=%s, backend=%s)",
            "OK" if WHISPER_AVAILABLE else "no",
            "OK" if KOKORO_AVAILABLE else "no",
            "OK" if PIPER_AVAILABLE else "no",
            self.config.tts_backend,
        )

    async def initialize(self) -> bool:
        """
        Preparación ligera al arranque.

        NO carga Piper/Kokoro ni Whisper de inicio para no consumir RAM en reposo.
        Si `voice_warmup` está activo y la RAM lo permite, precarga el motor de
        voz en segundo plano para que la PRIMERA frase salga rápida.
        """
        logger.info("🎵 AudioEngine en modo diferido (Piper/Whisper lazy-load)")
        if getattr(settings, "voice_warmup", False):
            try:
                asyncio.create_task(self._warmup())
            except Exception:  # noqa: BLE001
                pass
        return True

    async def _warmup(self) -> None:
        """Precarga el TTS en segundo plano salvo que la RAM esté crítica."""
        await asyncio.sleep(2.0)          # dejar que el resto arranque primero
        try:
            import psutil
            if psutil.virtual_memory().percent >= settings.ram_critical_percent:
                logger.info("🎵 warmup omitido (RAM alta) → carga diferida")
                return
        except Exception:  # noqa: BLE001
            pass
        if self.config.tts_backend == "kokoro" and KOKORO_AVAILABLE:
            await self._ensure_kokoro()
        elif PIPER_AVAILABLE:
            await self._ensure_piper()
        logger.info("🎵 Motor de voz precargado (primera frase rápida)")

    async def _ensure_piper(self) -> bool:
        """Carga Piper bajo demanda (primera síntesis)."""
        if self.piper is not None:
            return True
        return await self._load_piper()

    async def _ensure_kokoro(self) -> bool:
        """Carga Kokoro bajo demanda (voz femenina natural)."""
        if self.kokoro is not None:
            return True
        if not KOKORO_AVAILABLE:
            return False
        if not (os.path.exists(self.config.kokoro_model_path)
                and os.path.exists(self.config.kokoro_voices_path)):
            logger.warning("⚠️ Ficheros Kokoro no encontrados → respaldo Piper")
            return False
        try:
            loop = asyncio.get_event_loop()

            def _load():
                orig, loader = _patch_numpy_pickle()
                np.load = loader
                try:
                    return Kokoro(self.config.kokoro_model_path,
                                  self.config.kokoro_voices_path)
                finally:
                    np.load = orig

            self.kokoro = await loop.run_in_executor(None, _load)
            logger.info("✅ Kokoro cargado (voz %s)", self.config.kokoro_voice)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error cargando Kokoro: %s", exc)
            self.kokoro = None
            return False

    async def _kokoro_synthesize(self, text: str) -> Tuple[Optional[np.ndarray], int]:
        """Sintetiza con Kokoro → float32 mono + sample rate (24 kHz)."""
        loop = asyncio.get_event_loop()

        def _run():
            samples, sr = self.kokoro.create(
                text, voice=self.config.kokoro_voice,
                speed=self.config.kokoro_speed, lang=self.config.kokoro_lang,
            )
            return np.asarray(samples, dtype=np.float32), int(sr)

        return await loop.run_in_executor(None, _run)

    # ── Carga de modelos ───────────────────────────────────────────────────
    async def _load_piper(self) -> bool:
        if not PIPER_AVAILABLE:
            logger.warning("⚠️ Piper no instalado → TTS simulado")
            return False
        voice = self.config.piper_voice_path
        if not os.path.exists(voice):
            logger.warning("⚠️ Voz Piper no encontrada: %s", voice)
            return False
        try:
            loop = asyncio.get_event_loop()
            self.piper = await loop.run_in_executor(None, lambda: PiperVoice.load(voice))
            self.config.tts_sample_rate = getattr(
                self.piper.config, "sample_rate", self.config.tts_sample_rate
            )
            logger.info("✅ Piper cargado: %s", Path(voice).name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error cargando Piper: %s", exc)
            self.piper = None
            return False

    async def _ensure_whisper(self) -> bool:
        """Carga Whisper bajo demanda (primera transcripción)."""
        if self.whisper is not None:
            return True
        if not WHISPER_AVAILABLE:
            return False
        try:
            loop = asyncio.get_event_loop()
            self.whisper = await loop.run_in_executor(
                None,
                lambda: WhisperModel(
                    self.config.whisper_model,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=2,   # tope de CPU para no saturar el equipo
                ),
            )
            logger.info("✅ Whisper '%s' cargado", self.config.whisper_model)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error cargando Whisper: %s", exc)
            return False

    # ── STT (voz → texto) ──────────────────────────────────────────────────
    async def transcribe(self, wav_bytes: bytes) -> Optional[str]:
        """
        Transcribe un WAV (bytes) a texto.

        Devuelve None si no hay modelo o el audio es demasiado corto.
        """
        if sf is None:
            logger.warning("⚠️ soundfile no instalado, STT no disponible")
            return None
        if not await self._ensure_whisper():
            logger.warning("⚠️ Whisper no disponible, no se puede transcribir")
            return None

        tmp = self.temp_dir / f"stt_{int(time.time()*1000)}.wav"
        try:
            with open(tmp, "wb") as fh:
                fh.write(wav_bytes)

            loop = asyncio.get_event_loop()

            def _run() -> str:
                segments, _info = self.whisper.transcribe(
                    str(tmp),
                    language=self.config.whisper_language,
                    beam_size=1,          # mínimo para velocidad/RAM
                    vad_filter=True,
                )
                return " ".join(s.text for s in segments).strip()

            text = await loop.run_in_executor(None, _run)
            return text or None
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error en transcripción: %s", exc)
            return None
        finally:
            Path(tmp).unlink(missing_ok=True)

    # ── TTS (texto → voz) + lip-sync ───────────────────────────────────────
    async def synthesize(self, text: str) -> Optional[SpeechResult]:
        """
        Genera audio para `text` y su envolvente de lip-sync.

        Usa Piper si está disponible; si no, sintetiza un tono de relleno
        (modo desarrollo) para que el avatar siga animándose.
        """
        text = (text or "").strip()
        if not text:
            return None

        self.is_speaking = True
        try:
            samples, sr = None, self.config.tts_sample_rate
            # 1) Kokoro (voz femenina natural) si es el backend elegido.
            if self.config.tts_backend == "kokoro" and KOKORO_AVAILABLE:
                if await self._ensure_kokoro():
                    samples, sr = await self._kokoro_synthesize(text)
            # 2) Respaldo: Piper (ligero).
            if (samples is None or len(samples) == 0) and PIPER_AVAILABLE:
                await self._ensure_piper()
                if self.piper is not None:
                    samples, sr = await self._piper_synthesize(text)
            # 3) Último recurso: audio sintético (para que el avatar se anime).
            if samples is None or len(samples) == 0:
                samples, sr = self._synthetic_speech(text)

            if samples is None or len(samples) == 0:
                return None

            duration = len(samples) / sr
            frames = self._compute_volume_frames(samples, sr)
            wav_b64 = self._encode_wav_b64(samples, sr)

            return SpeechResult(
                wav_b64=wav_b64,
                duration=round(duration, 3),
                volume_frames=frames,
                sample_rate=sr,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error en TTS: %s", exc)
            return None
        finally:
            self.is_speaking = False

    async def _piper_synthesize(self, text: str) -> Tuple[Optional[np.ndarray], int]:
        """Sintetiza con Piper devolviendo float32 mono + sample rate."""
        loop = asyncio.get_event_loop()

        def _run() -> np.ndarray:
            chunks: List[np.ndarray] = []
            # API actual de Piper: synthesize() es un generador de AudioChunk.
            # Cada AudioChunk expone `audio_int16_array` (numpy int16).
            for chunk in self.piper.synthesize(text):
                arr = getattr(chunk, "audio_int16_array", None)
                if arr is None:
                    # Fallback: algunos la dan como bytes PCM int16.
                    raw = getattr(chunk, "audio_int16_bytes", None)
                    if raw:
                        arr = np.frombuffer(raw, dtype=np.int16)
                if arr is not None and len(arr):
                    chunks.append(np.asarray(arr, dtype=np.int16))
            if not chunks:
                return np.zeros(0, dtype=np.float32)
            pcm = np.concatenate(chunks)
            return pcm.astype(np.float32) / 32768.0

        audio = await loop.run_in_executor(None, _run)
        return audio, self.config.tts_sample_rate

    def _synthetic_speech(self, text: str) -> Tuple[np.ndarray, int]:
        """Audio de relleno (tono con envolvente) cuando no hay Piper."""
        sr = self.config.tts_sample_rate
        dur = max(0.6, len(text.split()) * 0.28)
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)
        wave = 0.25 * np.sin(2 * np.pi * 220 * t) + 0.08 * np.sin(2 * np.pi * 440 * t)
        # Envolvente tipo habla (varias sílabas)
        syl = max(1, len(text.split()))
        env = np.abs(np.sin(np.linspace(0, syl * np.pi, len(t))))
        return (wave * env * 0.9).astype(np.float32), sr

    # ── Lip-sync ───────────────────────────────────────────────────────────
    def _compute_volume_frames(self, samples: np.ndarray, sr: int) -> List[float]:
        """
        Divide el audio en fotogramas y calcula una envolvente expresiva (0..1).

        Aplica una curva gamma (realza volúmenes bajos para que la boca no
        parezca rígida) y un suavizado con media móvil para evitar el parpadeo.
        El frontend usa estos valores para abrir/cerrar la boca del avatar.
        """
        if len(samples) == 0:
            return []
        frame_size = max(1, int(sr / self.config.lipsync_fps))
        raw: List[float] = []
        for i in range(0, len(samples), frame_size):
            window = samples[i:i + frame_size]
            if len(window) == 0:
                break
            rms = float(np.sqrt(np.mean(window ** 2)))
            # gamma 0.75 + ganancia: voz suave abre bien la boca.
            raw.append(min(1.0, (rms * 5.0) ** 0.75))
        # Suavizado (25/50/25) para transiciones naturales.
        if len(raw) >= 3:
            sm: List[float] = []
            for i in range(len(raw)):
                a = raw[i - 1] if i > 0 else raw[i]
                b = raw[i]
                c = raw[i + 1] if i + 1 < len(raw) else raw[i]
                sm.append(round(min(1.0, 0.25 * a + 0.5 * b + 0.25 * c), 3))
            return sm
        return [round(min(1.0, v), 3) for v in raw]

    def _encode_wav_b64(self, samples: np.ndarray, sr: int) -> str:
        """Codifica float32 → WAV bytes → base64 (para envío por WebSocket)."""
        if sf is not None:
            import io
            buf = io.BytesIO()
            sf.write(buf, samples, sr, format="WAV", subtype="PCM_16")
            return base64.b64encode(buf.getvalue()).decode("ascii")
        # Fallback sin soundfile: cabecera WAV manual sobre PCM int16
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        header = self._wav_header(len(pcm), sr)
        return base64.b64encode(header + pcm).decode("ascii")

    @staticmethod
    def _wav_header(data_len: int, sr: int) -> bytes:
        """Construye una cabecera WAV PCM 16-bit mono mínima."""
        import struct
        byte_rate = sr * 2
        return b"RIFF" + struct.pack("<I", 36 + data_len) + b"WAVE" + \
            b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, byte_rate, 2, 16) + \
            b"data" + struct.pack("<I", data_len)

    def cleanup(self) -> None:
        """Borra archivos temporales antiguos (>1 h)."""
        try:
            for f in self.temp_dir.glob("*.wav"):
                if time.time() - f.stat().st_mtime > 3600:
                    Path(f).unlink(missing_ok=True)
            logger.info("🧹 AudioEngine limpiado")
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error limpiando AudioEngine: %s", exc)
