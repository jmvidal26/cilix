#!/usr/bin/env python3
"""
Motor VTuber para Cilix v1.1
Manejo del modelo Live2D Design_genius_white
Integración con audio_engine para lip-sync avanzado
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# Verificar dependencias para Live2D
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

class Emotion(Enum):
    """Emociones disponibles del modelo VTuber"""
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    SURPRISED = "surprised"
    WINK = "wink"
    BLINK = "blink"
    SPEAKING = "speaking"
    THINKING = "thinking"
    CONFUSED = "confused"
    SLEEPY = "sleepy"
    EXCITED = "excited"
    SHY = "shy"

@dataclass
class VTuberConfig:
    """Configuración del modelo VTuber"""
    # Modelo Live2D
    model_path: str = "../assets/models/Design_genius(1).model3.json"
    moc3_file: str = "../assets/models/Design_genius(1).moc3"
    textures_dir: str = "../assets/textures/"
    
    # Expresiones
    expressions_dir: str = "../assets/models/"
    default_expressions: List[str] = None  # Inicializar en __post_init__
    
    # Animación
    idle_motion: str = "../assets/models/idle.motion3.json"
    frame_rate: int = 30
    smoothing_factor: float = 0.3
    
    # Lip-sync
    lip_sync_parameter: str = "ParamMouthOpenY"
    lip_sync_sensitivity: float = 0.5
    min_phoneme_duration: float = 0.05
    
    # Rendimiento
    render_width: int = 512
    render_height: int = 512
    max_cpu_usage: float = 10.0
    
    def __post_init__(self):
        if self.default_expressions is None:
            self.default_expressions = [
                "1.exp3.json", "2.exp3.json", "3.exp3.json",
                "4.exp3.json", "5.exp3.json", "6.exp3.json",
                "7.exp3.json", "8.exp3.json", "10.exp3.json",
                "12.exp3.json", "13.exp3.json", "14.exp3.json",
                "144.exp3.json"
            ]

@dataclass
class PhonemeData:
    """Datos de fonemas para lip-sync"""
    phoneme: str
    intensity: float
    duration: float
    timestamp: float

class VTuberEngine:
    """
    Motor principal para el VTuber Design_genius_white
    Maneja animaciones, expresiones y lip-sync
    """
    
    def __init__(self, config: Optional[VTuberConfig] = None):
        self.config = config or VTuberConfig()
        
        # Estado del modelo
        self.current_emotion = Emotion.NEUTRAL
        self.is_speaking = False
        self.is_idle = True
        self.model_loaded = False
        
        # Parámetros de animación
        self.parameters: Dict[str, float] = {}
        self.expressions: Dict[str, Dict] = {}
        self.motions: Dict[str, List] = {}
        
        # Lip-sync
        self.phoneme_queue: List[PhonemeData] = []
        self.current_phoneme: Optional[PhonemeData] = None
        self.lip_sync_active = False
        
        # Estadísticas
        self.stats = {
            "frames_rendered": 0,
            "expressions_changed": 0,
            "phonemes_processed": 0,
            "avg_render_time": 0.0
        }
        
        # Cache de recursos
        self.textures_cache: Dict[str, Any] = {}
        self.expression_cache: Dict[str, Dict] = {}
        
        logger.info("🎭 VTuberEngine inicializado (Design_genius_white)")
        
    async def initialize(self):
        """Inicializar motor VTurer y cargar modelo"""
        try:
            logger.info("🔄 Inicializando modelo VTuber...")
            
            # Verificar que existan los archivos del modelo
            model_files_exist = await self._check_model_files()
            
            if not model_files_exist:
                logger.error("❌ Archivos del modelo no encontrados")
                logger.info("💡 Copia el modelo de ../design_genius_white/ a assets/")
                return False
                
            # Cargar configuración del modelo
            await self._load_model_config()
            
            # Cargar expresiones
            await self._load_expressions()
            
            # Cargar animaciones idle
            await self._load_idle_motion()
            
            # Inicializar parámetros por defecto
            self._initialize_default_parameters()
            
            self.model_loaded = True
            logger.info(f"✅ Modelo VTuber cargado: {len(self.expressions)} expresiones")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error inicializando VTuberEngine: {e}")
            return False
            
    async def _check_model_files(self) -> bool:
        """Verificar que existan los archivos necesarios del modelo"""
        required_files = [
            self.config.model_path,
            self.config.moc3_file,
            self.config.idle_motion
        ]
        
        all_exist = True
        for file_path in required_files:
            if not os.path.exists(file_path):
                logger.warning(f"⚠️ Archivo no encontrado: {file_path}")
                all_exist = False
                
        # Verificar al menos una textura
        textures_exist = False
        if os.path.exists(self.config.textures_dir):
            texture_files = list(Path(self.config.textures_dir).glob("*.png"))
            if texture_files:
                textures_exist = True
                logger.info(f"✅ Texturas encontradas: {len(texture_files)}")
            else:
                logger.warning(f"⚠️ No hay texturas PNG en: {self.config.textures_dir}")
        else:
            logger.warning(f"⚠️ Directorio de texturas no existe: {self.config.textures_dir}")
            
        return all_exist and textures_exist
        
    async def _load_model_config(self):
        """Cargar configuración del modelo desde .model3.json"""
        try:
            if not os.path.exists(self.config.model_path):
                logger.warning("⚠️ Archivo .model3.json no encontrado, usando configuración por defecto")
                return
                
            with open(self.config.model_path, 'r', encoding='utf-8') as f:
                model_data = json.load(f)
                
            # Extraer información del modelo
            if "FileReferences" in model_data:
                refs = model_data["FileReferences"]
                
                # Mapear texturas
                if "Textures" in refs:
                    textures = refs["Textures"]
                    logger.info(f"📋 Texturas referenciadas: {len(textures)} grupos")
                    
                # Mapear movimientos
                if "Motions" in refs:
                    motions = refs["Motions"]
                    logger.info(f"💃 Movimientos disponibles: {len(motions)}")
                    
            # Extraer grupos de parámetros
            if "Groups" in model_data:
                for group in model_data["Groups"]:
                    if group.get("Name") == "Parameter":
                        logger.info(f"🔧 Parámetros del modelo: {len(group.get('Ids', []))}")
                        
            logger.info("✅ Configuración del modelo cargada")
            
        except Exception as e:
            logger.error(f"❌ Error cargando configuración del modelo: {e}")
            
    async def _load_expressions(self):
        """Cargar expresiones faciales desde archivos .exp3.json"""
        try:
            expressions_loaded = 0
            
            for exp_file in self.config.default_expressions:
                exp_path = os.path.join(self.config.expressions_dir, exp_file)
                
                if os.path.exists(exp_path):
                    try:
                        with open(exp_path, 'r', encoding='utf-8') as f:
                            exp_data = json.load(f)
                            
                        # Extraer nombre de la expresión
                        exp_name = Path(exp_file).stem
                        self.expressions[exp_name] = exp_data
                        
                        # Cachear para rápido acceso
                        self.expression_cache[exp_name] = self._extract_expression_params(exp_data)
                        
                        expressions_loaded += 1
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Error cargando expresión {exp_file}: {e}")
                else:
                    logger.warning(f"⚠️ Expresión no encontrada: {exp_path}")
                    
            logger.info(f"😊 Expresiones cargadas: {expressions_loaded}/{len(self.config.default_expressions)}")
            
        except Exception as e:
            logger.error(f"❌ Error cargando expresiones: {e}")
            
    def _extract_expression_params(self, exp_data: Dict) -> Dict[str, float]:
        """Extraer parámetros de una expresión"""
        params = {}
        
        if "Parameters" in exp_data:
            for param in exp_data["Parameters"]:
                param_id = param.get("Id", "")
                param_value = param.get("Value", 0.0)
                if param_id:
                    params[param_id] = param_value
                    
        return params
        
    async def _load_idle_motion(self):
        """Cargar animación idle del modelo"""
        try:
            if os.path.exists(self.config.idle_motion):
                with open(self.config.idle_motion, 'r', encoding='utf-8') as f:
                    motion_data = json.load(f)
                    
                # Procesar frames de animación
                if "Curves" in motion_data:
                    self.motions["idle"] = motion_data["Curves"]
                    logger.info("🌀 Animación idle cargada")
            else:
                logger.warning("⚠️ Archivo de animación idle no encontrado")
                
        except Exception as e:
            logger.error(f"❌ Error cargando animación idle: {e}")
            
    def _initialize_default_parameters(self):
        """Inicializar parámetros del modelo por defecto"""
        # Parámetros faciales comunes en Live2D
        default_params = {
            "ParamAngleX": 0.0,
            "ParamAngleY": 0.0,
            "ParamAngleZ": 0.0,
            "ParamEyeLOpen": 1.0,
            "ParamEyeROpen": 1.0,
            "ParamEyeBallX": 0.0,
            "ParamEyeBallY": 0.0,
            "ParamBrowLY": 0.0,
            "ParamBrowRY": 0.0,
            "ParamBrowLAngle": 0.0,
            "ParamBrowRAngle": 0.0,
            "ParamBrowLForm": 0.0,
            "ParamBrowRForm": 0.0,
            "ParamMouthForm": 0.0,
            "ParamMouthOpenY": 0.0,
            "ParamCheek": 0.0,
            "ParamBodyAngleX": 0.0,
            "ParamBodyAngleY": 0.0,
            "ParamBodyAngleZ": 0.0,
        }
        
        self.parameters.update(default_params)
        logger.info(f"⚙️ Parámetros inicializados: {len(self.parameters)}")
        
    async def set_emotion(self, emotion: Emotion, intensity: float = 1.0):
        """
        Cambiar la emoción del VTuber
        
        Args:
            emotion: Emoción a mostrar
            intensity: Intensidad de la emoción (0.0 a 1.0)
        """
        if not self.model_loaded:
            return
            
        try:
            old_emotion = self.current_emotion
            self.current_emotion = emotion
            
            # Mapear emoción a expresión
            expression_map = self._get_expression_for_emotion(emotion)
            
            if expression_map:
                # Aplicar expresión con suavizado
                await self._apply_expression(expression_map, intensity)
                
                self.stats["expressions_changed"] += 1
                logger.info(f"😊 Emoción cambiada: {old_emotion.value} → {emotion.value} (intensidad: {intensity:.2f})")
                
        except Exception as e:
            logger.error(f"❌ Error cambiando emoción: {e}")
            
    def _get_expression_for_emotion(self, emotion: Emotion) -> Optional[Dict[str, float]]:
        """Obtener parámetros de expresión para una emoción"""
        # Mapeo de emociones a expresiones
        emotion_to_expression = {
            Emotion.NEUTRAL: "1",      # Expresión neutral
            Emotion.HAPPY: "2",        # Feliz
            Emotion.SAD: "3",          # Triste
            Emotion.ANGRY: "4",        # Enfadado
            Emotion.SURPRISED: "5",    # Sorprendido
            Emotion.WINK: "6",         # Guiño
            Emotion.BLINK: "7",        # Parpadeo
            Emotion.SPEAKING: "8",     # Hablando
            Emotion.THINKING: "10",    # Pensando
            Emotion.CONFUSED: "12",    # Confundido
            Emotion.SLEEPY: "13",      # Soñoliento
            Emotion.EXCITED: "14",     # Emocionado
            Emotion.SHY: "144",        # Tímido
        }
        
        exp_key = emotion_to_expression.get(emotion, "1")
        return self.expression_cache.get(exp_key)
        
    async def _apply_expression(self, expression_params: Dict[str, float], intensity: float):
        """Aplicar expresión con suavizado"""
        for param_id, target_value in expression_params.items():
            current_value = self.parameters.get(param_id, 0.0)
            
            # Suavizar transición
            new_value = current_value + (target_value * intensity - current_value) * self.config.smoothing_factor
            
            self.parameters[param_id] = new_value
            
    async def process_lip_sync(self, phoneme: str, intensity: float, duration: float):
        """
        Procesar fonema para lip-sync
        
        Args:
            phoneme: Fonema detectado
            intensity: Intensidad del fonema (0.0 a 1.0)
            duration: Duración en segundos
        """
        if not self.model_loaded:
            return
            
        try:
            # Crear dato de fonema
            phoneme_data = PhonemeData(
                phoneme=phoneme,
                intensity=intensity,
                duration=duration,
                timestamp=time.time()
            )
            
            # Agregar a la cola
            self.phoneme_queue.append(phoneme_data)
            
            # Limitar tamaño de la cola
            if len(self.phoneme_queue) > 10:
                self.phoneme_queue.pop(0)
                
            self.stats["phonemes_processed"] += 1
            
            # Procesar lip-sync inmediatamente
            await self._update_lip_sync()
            
        except Exception as e:
            logger.error(f"❌ Error procesando lip-sync: {e}")
            
    async def _update_lip_sync(self):
        """Actualizar parámetros de lip-sync basado en fonemas actuales"""
        if not self.phoneme_queue:
            # Sin fonemas, cerrar boca gradualmente
            current_value = self.parameters.get(self.config.lip_sync_parameter, 0.0)
            self.parameters[self.config.lip_sync_parameter] = current_value * 0.7
            return
            
        # Tomar el fonema más reciente
        current_phoneme = self.phoneme_queue[-1]
        
        # Mapear fonema a valor de apertura de boca
        mouth_open_value = self._phoneme_to_mouth_open(current_phoneme.phoneme)
        
        # Aplicar con intensidad
        target_value = mouth_open_value * current_phoneme.intensity * self.config.lip_sync_sensitivity
        
        # Suavizar transición
        current_value = self.parameters.get(self.config.lip_sync_parameter, 0.0)
        new_value = current_value + (target_value - current_value) * 0.5
        
        self.parameters[self.config.lip_sync_parameter] = new_value
        self.is_speaking = new_value > 0.1
        
    def _phoneme_to_mouth_open(self, phoneme: str) -> float:
        """Convertir fonema a valor de apertura de boca"""
        # Mapeo básico de fonemas a apertura de boca
        phoneme_map = {
            # Vocales - boca más abierta
            "a": 0.8, "e": 0.6, "i": 0.4, "o": 0.7, "u": 0.5,
            "aa": 0.9, "ee": 0.7, "ii": 0.5, "oo": 0.8, "uu": 0.6,
            
            # Consonantes - boca menos abierta
            "p": 0.3, "b": 0.3, "m": 0.4,
            "t": 0.2, "d": 0.2, "n": 0.3,
            "k": 0.1, "g": 0.1, "ng": 0.2,
            "f": 0.5, "v": 0.5,
            "s": 0.4, "z": 0.4,
            "sh": 0.6, "zh": 0.6,
            "l": 0.3, "r": 0.3,
            
            # Silencio
            "sil": 0.0, "": 0.0
        }
        
        # Normalizar fonema
        phoneme_lower = phoneme.lower().strip()
        
        # Buscar coincidencia exacta o parcial
        for key, value in phoneme_map.items():
            if key in phoneme_lower or phoneme_lower in key:
                return value
                
        # Valor por defecto para fonemas desconocidos
        return 0.3
        
    async def update_idle_animation(self):
        """Actualizar animación idle del modelo"""
        if not self.model_loaded or not self.is_idle:
            return
            
        try:
            # Simular movimiento idle básico
            current_time = time.time()
            
            # Movimiento suave de cabeza
            head_move = np.sin(current_time * 0.5) * 0.1
            self.parameters["ParamAngleX"] = head_move * 0.3
            self.parameters["ParamAngleY"] = head_move * 0.2
            
            # Parpadeo ocasional
            if current_time % 5 < 0.1:  # Cada ~5 segundos
                self.parameters["ParamEyeLOpen"] = 0.0
                self.parameters["ParamEyeROpen"] = 0.0
                await asyncio.sleep(0.1)
                self.parameters["ParamEyeLOpen"] = 1.0
                self.parameters["ParamEyeROpen"] = 1.0
                
        except Exception as e:
            logger.error(f"❌ Error en animación idle: {e}")
            
    async def get_current_state(self) -> Dict[str, Any]:
        """Obtener estado actual del VTurer para el frontend"""
        return {
            "emotion": self.current_emotion.value,
            "parameters": self.parameters.copy(),
            "is_speaking": self.is_speaking,
            "is_idle": self.is_idle,
            "lip_sync_active": self.lip_sync_active,
            "stats": self.stats.copy()
        }
        
    async def render_frame(self) -> Optional[Dict]:
        """
        Renderizar un frame del VTurer (simulado)
        En producción, esto generaría una imagen real
        
        Returns:
            Diccionario con datos del frame o None
        """
        if not self.model_loaded:
            return None
            
        try:
            start_time = time.time()
            
            # Actualizar estado
            if self.is_speaking:
                await self._update_lip_sync()
            else:
                await self.update_idle_animation()
                
            # Crear datos del frame
            frame_data = {
                "timestamp": time.time(),
                "parameters": self.parameters.copy(),
                "emotion": self.current_emotion.value,
                "lip_sync_value": self.parameters.get(self.config.lip_sync_parameter, 0.0)
            }
            
            # Actualizar estadísticas
            render_time = time.time() - start_time
            self.stats["frames_rendered"] += 1
            self.stats["avg_render_time"] = (
                self.stats["avg_render_time"] * 0.9 + render_time * 0.1
            )
            
            return frame_data
            
        except Exception as e:
            logger.error(f"❌ Error renderizando frame: {e}")
            return None
            
    async def start_animation_loop(self, callback=None):
        """
        Iniciar loop de animación continua
        
        Args:
            callback: Función a llamar con cada frame
        """
        logger.info("▶️ Iniciando loop de animación VTuber...")
        
        try:
            while self.model_loaded:
                start_time = time.time()
                
                # Renderizar frame
                frame_data = await self.render_frame()
                
                if frame_data and callback:
                    await callback(frame_data)
                    
                # Controlar FPS
                frame_time = time.time() - start_time
                target_frame_time = 1.0 / self.config.frame_rate
                
                if frame_time < target_frame_time:
                    await asyncio.sleep(target_frame_time - frame_time)
                    
        except asyncio.CancelledError:
            logger.info("⏹️ Loop de animación cancelado")
        except Exception as e:
            logger.error(f"❌ Error en loop de animación: {e}")
            
    def cleanup(self):
        """Limpiar recursos del VTurer"""
        try:
            self.model_loaded = False
            
            # Limpiar colas
            self.phoneme_queue.clear()
            
            # Limpiar cachés
            self.textures_cache.clear()
            self.expression_cache.clear()
            
            logger.info("🧹 VTuberEngine limpiado")
            
        except Exception as e:
            logger.error(f"❌ Error limpiando VTuberEngine: {e}")

# Función de prueba
async def test_vtuber_engine():
    """Probar VTuberEngine"""
    print("🧪 Probando VTuberEngine (Design_genius_white)...")
    
    engine = VTuberEngine()
    
    # Inicializar
    print("🔧 Inicializando modelo...")
    success = await engine.initialize()
    
    if not success:
        print("⚠️ VTuberEngine no se pudo inicializar completamente")
        print("💡 Asegúrate de tener los archivos del modelo en assets/")
        return
        
    # Probar emociones
    print("\n😊 Probando emociones...")
    emotions_to_test = [
        (Emotion.HAPPY, 0.8),
        (Emotion.SAD, 0.6),
        (Emotion.SURPRISED, 1.0),
        (Emotion.THINKING, 0.7),
    ]
    
    for emotion, intensity in emotions_to_test:
        print(f"  Cambiando a: {emotion.value} (intensidad: {intensity})")
        await engine.set_emotion(emotion, intensity)
        await asyncio.sleep(0.5)
        
    # Probar lip-sync
    print("\n🗣️ Probando lip-sync...")
    test_phonemes = [
        ("a", 0.8, 0.2),
        ("i", 0.6, 0.15),
        ("o", 0.7, 0.18),
        ("sil", 0.0, 0.1),
    ]
    
    for phoneme, intensity, duration in test_phonemes:
        print(f"  Fonema: {phoneme} (intensidad: {intensity})")
        await engine.process_lip_sync(phoneme, intensity, duration)
        await asyncio.sleep(duration)
        
    # Obtener estado
    print("\n📊 Estado del VTuber:")
    state = await engine.get_current_state()
    print(f"  Emoción actual: {state['emotion']}")
    print(f"  Hablando: {state['is_speaking']}")
    print(f"  Parámetros activos: {len(state['parameters'])}")
    print(f"  Frames renderizados: {state['stats']['frames_rendered']}")
    
    # Limpiar
    engine.cleanup()
    print("\n✅ Pruebas completadas")

if __name__ == "__main__":
    # Ejecutar prueba
    asyncio.run(test_vtuber_engine())