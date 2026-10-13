#!/usr/bin/env python3
"""
Motor de Audio de Cilix - STT (Whisper) + TTS (Piper) local
Optimizado para 8GB RAM, 100% offline
"""

import asyncio
import json
import logging
import os
import tempfile
import time
import wave
from typing import Optional, Tuple, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
import soundfile as sf
import simpleaudio as sa

# Importar Whisper (CPU-only para ahorrar RAM)
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ faster-whisper no disponible. Instala: pip install faster-whisper")

# Importar Piper TTS
try:
    # Piper es más ligero que otros TTS
    import piper
    PIPER_AVAILABLE = True
except ImportError:
    PIPER_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ Piper TTS no disponible. Instala: pip install piper-tts")

logger = logging.getLogger(__name__)

@dataclass
class AudioConfig:
    """Configuración de audio"""
    # Grabación
    sample_rate: int = 16000
    channels: int = 1
    dtype: str = 'float32'
    
    # Whisper STT
    whisper_model: str = "tiny"  # tiny, base, small (para ahorrar RAM)
    whisper_device: str = "cpu"
    compute_type: str = "int8"
    
    # Piper TTS
    tts_model_path: str = ""
    tts_voice: str = "female-light"
    tts_speaker: Optional[int] = None
    tts_length_scale: float = 1.0
    tts_noise_scale: float = 0.667
    tts_noise_w: float = 0.8

class AudioBuffer:
    """Buffer circular para grabación de audio"""
    
    def __init__(self, sample_rate: int = 16000, max_duration: float = 30.0):
        self.sample_rate = sample_rate
        self.max_samples = int(sample_rate * max_duration)
        self.buffer = np.zeros(self.max_samples, dtype=np.float32)
        self.idx = 0
        self.is_recording = False
        
    def start(self):
        """Iniciar grabación"""
        self.buffer.fill(0)
        self.idx = 0
        self.is_recording = True
        
    def stop(self):
        """Detener grabación"""
        self.is_recording = False
        
    def add_samples(self, samples: np.ndarray):
        """Agregar muestras al buffer"""
        if not self.is_recording:
            return
            
        n = len(samples)
        if self.idx + n > self.max_samples:
            # Buffer lleno, desplazar
            overflow = self.idx + n - self.max_samples
            self.buffer[:-overflow] = self.buffer[overflow:]
            self.buffer[-overflow:] = samples[:overflow]
            self.idx = self.max_samples
        else:
            self.buffer[self.idx:self.idx + n] = samples
            self.idx += n
            
    def get_audio(self) -> np.ndarray:
        """Obtener audio grabado"""
        return self.buffer[:self.idx]
        
    def get_duration(self) -> float:
        """Obtener duración en segundos"""
        return self.idx / self.sample_rate

class AudioEngine:
    """
    Motor de audio completo para Cilix
    - STT: faster-whisper (CPU, ligero)
    - TTS: Piper TTS (local, femenino, eficiente)
    """
    
    def __init__(self, config: Optional[AudioConfig] = None, voice_model: str = "female-light"):
        self.config = config or AudioConfig()
        self.config.tts_voice = voice_model
        
        # Directorios temporales
        self.temp_dir = Path(tempfile.gettempdir()) / "cilix_audio"
        self.temp_dir.mkdir(exist_ok=True)
        
        # Inicializar componentes
        self.whisper_model = None
        self.piper_model = None
        self.audio_buffer = AudioBuffer(self.config.sample_rate)
        
        # Estado
        self.is_listening = False
        self.is_speaking = False
        self.stream = None
        
        # Configurar modelos de voz femeninos
        self.voice_models = {
            "female-light": {
                "path": self._get_voice_path("female-light"),
                "description": "Voz femenina ligera y amigable"
            },
            "female-warm": {
                "path": self._get_voice_path("female-warm"),
                "description": "Voz femenina cálida y expresiva"
            }
        }
        
        logger.info("🎵 AudioEngine inicializado")
        
    def _get_voice_path(self, voice_name: str) -> str:
        """
        Obtener ruta al modelo de voz Piper
        En producción, estos modelos se descargarían automáticamente
        """
        # Directorio para modelos de voz
        voice_dir = self.temp_dir / "voices"
        voice_dir.mkdir(exist_ok=True)
        
        voice_file = voice_dir / f"{voice_name}.onnx"
        
        # Si no existe el archivo, notificar
        if not voice_file.exists():
            logger.warning(f"⚠️ Modelo de voz no encontrado: {voice_file}")
            logger.info("💡 Descarga modelos de voz de: https://github.com/rhasspy/piper-tts")
            
        return str(voice_file)
        
    async def initialize(self):
        """Inicializar modelos de audio"""
        try:
            # Inicializar Whisper STT
            await self._initialize_whisper()
            
            # Inicializar Piper TTS
            await self._initialize_piper()
            
            logger.info("✅ AudioEngine inicializado exitosamente")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error al inicializar AudioEngine: {e}")
            return False
            
    async def _initialize_whisper(self):
        """Inicializar modelo Whisper para STT"""
        if not WHISPER_AVAILABLE:
            logger.warning("❌ faster-whisper no disponible")
            return False
            
        try:
            logger.info(f"🤫 Inicializando Whisper ({self.config.whisper_model})...")
            
            # Usar modelo pequeño para ahorrar RAM
            self.whisper_model = WhisperModel(
                self.config.whisper_model,
                device=self.config.whisper_device,
                compute_type=self.config.compute_type,
                cpu_threads=2  # Limitado para no consumir toda la CPU
            )
            
            logger.info(f"✅ Whisper cargado: {self.config.whisper_model}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error al cargar Whisper: {e}")
            self.whisper_model = None
            return False
            
    async def _initialize_piper(self):
        """Inicializar Piper TTS"""
        if not PIPER_AVAILABLE:
            logger.warning("❌ Piper TTS no disponible")
            return False
            
        try:
            # Obtener ruta al modelo de voz
            voice_path = self.voice_models[self.config.tts_voice]["path"]
            
            if not os.path.exists(voice_path):
                logger.warning(f"⚠️ Modelo de voz no encontrado: {voice_path}")
                logger.info("💡 Usando voz simulada por ahora")
                self.piper_model = None
                return False
                
            logger.info(f"🗣️ Inicializando Piper TTS ({self.config.tts_voice})...")
            
            # Cargar modelo Piper
            self.piper_model = piper.PiperVoice.load(
                voice_path,
                config_path=None,
                use_cuda=False  # CPU-only para ahorrar RAM
            )
            
            logger.info(f"✅ Piper TTS cargado: {self.config.tts_voice}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error al cargar Piper: {e}")
            self.piper_model = None
            return False
            
    def start_listening(self, callback=None):
        """
        Iniciar escucha del micrófono
        
        Args:
            callback: Función a llamar cuando se detecta voz
        """
        if self.is_listening:
            logger.warning("⚠️ Ya se está escuchando")
            return
            
        try:
            logger.info("🎤 Iniciando escucha...")
            
            # Configurar callback para captura de audio
            def audio_callback(indata, frames, time_info, status):
                if status:
                    logger.warning(f"Audio status: {status}")
                    
                if self.is_listening:
                    # Convertir a float32
                    audio_data = indata[:, 0].astype(np.float32)
                    self.audio_buffer.add_samples(audio_data)
                    
                    # Detección simple de actividad vocal
                    if self._has_voice_activity(audio_data):
                        if callback:
                            callback("voice_activity")
                            
            # Crear stream de entrada
            self.stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype,
                callback=audio_callback,
                blocksize=1024
            )
            
            self.audio_buffer.start()
            self.stream.start()
            self.is_listening = True
            
            logger.info("✅ Escucha activa")
            
        except Exception as e:
            logger.error(f"❌ Error al iniciar escucha: {e}")
            self.is_listening = False
            
    def stop_listening(self) -> Optional[str]:
        """
        Detener escucha y transcribir audio
        
        Returns:
            Texto transcrito o None
        """
        if not self.is_listening:
            return None
            
        try:
            logger.info("⏹️ Deteniendo escucha...")
            
            # Detener stream
            if self.stream:
                self.stream.stop()
                self.stream.close()
                self.stream = None
                
            self.audio_buffer.stop()
            self.is_listening = False
            
            # Obtener audio grabado
            audio_data = self.audio_buffer.get_audio()
            duration = self.audio_buffer.get_duration()
            
            if duration < 0.5:  # Menos de medio segundo
                logger.info("🗣️ Audio demasiado corto, ignorando")
                return None
                
            logger.info(f"🎙️ Audio grabado: {duration:.2f}s")
            
            # Transcribir
            if self.whisper_model:
                text = self._transcribe_audio(audio_data)
                return text
            else:
                logger.warning("⚠️ Whisper no disponible, usando texto simulado")
                return "Hola Cilix, ¿cómo estás hoy?"
                
        except Exception as e:
            logger.error(f"❌ Error al detener escucha: {e}")
            return None
            
    def _has_voice_activity(self, audio_data: np.ndarray, threshold: float = 0.02) -> bool:
        """
        Detectar actividad vocal simple
        
        Args:
            audio_data: Datos de audio
            threshold: Umbral de amplitud
            
        Returns:
            True si hay actividad vocal
        """
        amplitude = np.abs(audio_data).max()
        return amplitude > threshold
        
    def _transcribe_audio(self, audio_data: np.ndarray) -> str:
        """
        Transcribir audio a texto usando Whisper
        
        Args:
            audio_data: Audio en formato float32
            
        Returns:
            Texto transcrito
        """
        if not self.whisper_model:
            return "Whisper no disponible"
            
        try:
            start_time = time.time()
            
            # Guardar audio temporal para Whisper
            temp_audio = self.temp_dir / f"stt_{int(time.time())}.wav"
            sf.write(temp_audio, audio_data, self.config.sample_rate)
            
            # Transcribir
            segments, info = self.whisper_model.transcribe(
                str(temp_audio),
                beam_size=3,  # Reducido para velocidad
                language="es",  # Forzar español
                vad_filter=True,  # Filtrar silencios
                vad_parameters=dict(
                    threshold=0.5,
                    min_speech_duration_ms=250,
                    min_silence_duration_ms=100
                )
            )
            
            # Unir segmentos
            text = " ".join([segment.text for segment in segments])
            
            # Limpiar
            try:
                temp_audio.unlink()
            except:
                pass
                
            duration = time.time() - start_time
            logger.info(f"📝 Transcrito en {duration:.2f}s: {text[:50]}...")
            
            return text.strip()
            
        except Exception as e:
            logger.error(f"❌ Error en transcripción: {e}")
            return "Error en transcripción"
            
    def text_to_speech(self, text: str, output_file: Optional[str] = None) -> Tuple[str, float]:
        """
        Convertir texto a voz usando Piper TTS
        
        Args:
            text: Texto a convertir
            output_file: Ruta de salida opcional
            
        Returns:
            Tupla (ruta_audio, duración_segundos)
        """
        if not text.strip():
            return "", 0.0
            
        try:
            start_time = time.time()
            
            # Generar archivo de salida
            if not output_file:
                output_file = str(self.temp_dir / f"tts_{int(time.time())}.wav")
                
            if self.piper_model:
                # Usar Piper TTS real
                audio_data = self._synthesize_with_piper(text)
                duration = len(audio_data) / self.config.sample_rate
                
                # Guardar archivo WAV
                sf.write(output_file, audio_data, self.config.sample_rate)
                
            else:
                # Modo simulado (para desarrollo)
                logger.warning("⚠️ Piper no disponible, usando TTS simulado")
                duration = len(text.split()) * 0.3  # Estimación
                
                # Crear archivo de audio simulado
                self._create_simulated_audio(output_file, duration)
                
            tts_duration = time.time() - start_time
            logger.info(f"🗣️ TTS generado en {tts_duration:.2f}s ({duration:.2f}s audio)")
            
            return output_file, duration
            
        except Exception as e:
            logger.error(f"❌ Error en TTS: {e}")
            return "", 0.0
            
    def _synthesize_with_piper(self, text: str) -> np.ndarray:
        """
        Sintetizar voz usando Piper
        
        Args:
            text: Texto a sintetizar
            
        Returns:
            Datos de audio
        """
        # Configurar opciones de síntesis
        synthesis_args = {
            "length_scale": self.config.tts_length_scale,
            "noise_scale": self.config.tts_noise_scale,
            "noise_w": self.config.tts_noise_w,
            "speaker_id": self.config.tts_speaker
        }
        
        # Sintetizar
        audio_data = self.piper_model.synthesize(text, **synthesis_args)
        return audio_data
        
    def _create_simulated_audio(self, output_path: str, duration: float):
        """
        Crear audio simulado para desarrollo
        
        Args:
            output_path: Ruta de salida
            duration: Duración en segundos
        """
        sample_rate = 22050
        t = np.linspace(0, duration, int(sample_rate * duration))
        
        # Crear tono simple
        freq = 220  # Hz
        audio = 0.3 * np.sin(2 * np.pi * freq * t)
        
        # Agregar algo de variación
        audio += 0.1 * np.sin(2 * np.pi * 440 * t)
        
        # Aplicar envolvente ADSR
        attack = 0.05
        decay = 0.1
        sustain = 0.7
        release = 0.15
        
        # Crear envolvente
        n_samples = len(audio)
        envelope = np.ones(n_samples)
        
        attack_samples = int(attack * n_samples)
        decay_samples = int(decay * n_samples)
        release_samples = int(release * n_samples)
        sustain_samples = n_samples - attack_samples - decay_samples - release_samples
        
        if attack_samples > 0:
            envelope[:attack_samples] = np.linspace(0, 1, attack_samples)
        if decay_samples > 0:
            envelope[attack_samples:attack_samples+decay_samples] = np.linspace(1, sustain, decay_samples)
        if sustain_samples > 0:
            envelope[attack_samples+decay_samples:attack_samples+decay_samples+sustain_samples] = sustain
        if release_samples > 0:
            envelope[attack_samples+decay_samples+sustain_samples:] = np.linspace(sustain, 0, release_samples)
            
        # Aplicar envolvente
        audio *= envelope
        
        # Guardar
        sf.write(output_path, audio, sample_rate)
        
    def play_audio(self, audio_path: str):
        """
        Reproducir archivo de audio usando simpleaudio
        
        Args:
            audio_path: Ruta al archivo de audio
        """
        if not os.path.exists(audio_path):
            logger.error(f"❌ Archivo de audio no encontrado: {audio_path}")
            return
            
        try:
            self.is_speaking = True
            
            # Cargar archivo de audio
            wave_obj = sa.WaveObject.from_wave_file(audio_path)
            
            # Reproducir
            play_obj = wave_obj.play()
            play_obj.wait_done()  # Esperar que termine la reproducción
            
            self.is_speaking = False
            
        except Exception as e:
            logger.error(f"❌ Error al reproducir audio: {e}")
            logger.info("💡 Intentando método alternativo...")
            
            # Método alternativo usando soundfile y sounddevice
            try:
                data, samplerate = sf.read(audio_path)
                sd.play(data, samplerate)
                sd.wait()
                self.is_speaking = False
            except Exception as e2:
                logger.error(f"❌ Error también en método alternativo: {e2}")
                self.is_speaking = False
            
    async def play_audio_async(self, audio_path: str):
        """Reproducir audio asíncronamente"""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.play_audio, audio_path
        )
        
    def get_audio_duration(self, audio_path: str) -> float:
        """
        Obtener duración de archivo de audio
        
        Args:
            audio_path: Ruta al archivo
            
        Returns:
            Duración en segundos
        """
        try:
            with sf.SoundFile(audio_path) as f:
                return len(f) / f.samplerate
        except:
            return 0.0
            
    def cleanup(self):
        """Limpiar recursos"""
        try:
            # Detener escucha si está activa
            if self.is_listening and self.stream:
                self.stream.stop()
                self.stream.close()
                
            # Limpiar archivos temporales antiguos (más de 1 hora)
            for file in self.temp_dir.glob("*.wav"):
                if time.time() - file.stat().st_mtime > 3600:
                    try:
                        file.unlink()
                    except:
                        pass
                        
            logger.info("🧹 AudioEngine limpiado")
            
        except Exception as e:
            logger.error(f"❌ Error limpiando AudioEngine: {e}")

# Función de prueba
async def test_audio_engine():
    """Probar AudioEngine"""
    print("🧪 Probando AudioEngine...")
    
    engine = AudioEngine()
    
    # Inicializar
    print("🔧 Inicializando...")
    await engine.initialize()
    
    # Probar TTS
    print("\n🗣️ Probando TTS...")
    text = "Hola, soy Cilix. Tu asistente de voz local."
    audio_path, duration = engine.text_to_speech(text)
    
    print(f"✅ Audio generado: {audio_path}")
    print(f"⏱️ Duración: {duration:.2f}s")
    
    # Reproducir (opcional)
    play = input("¿Reproducir audio? (s/n): ").lower()
    if play == 's':
        engine.play_audio(audio_path)
        
    # Probar STT (simulado)
    print("\n🎤 Probando STT (simulado)...")
    print("💡 En una implementación real, grabaría del micrófono")
    
    # Limpiar
    engine.cleanup()
    print("\n✅ Pruebas completadas")

if __name__ == "__main__":
    asyncio.run(test_audio_engine())