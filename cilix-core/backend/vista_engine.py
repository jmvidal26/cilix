#!/usr/bin/env python3
"""
Módulo de Percepción de Cilix - VistaEngine
Captura de cámara y monitoreo de ventana activa
Optimizado para bajo consumo de recursos
"""

import asyncio
import json
import logging
import os
import platform
import time
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
from enum import Enum

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    
try:
    import pyautogui
    PYATUIGUI_AVAILABLE = True
except ImportError:
    PYATUIGUI_AVAILABLE = False

logger = logging.getLogger(__name__)

class CaptureSource(Enum):
    """Fuentes de captura disponibles"""
    CAMERA = "camera"
    SCREEN = "screen"
    WINDOW = "window"

@dataclass
class VisionConfig:
    """Configuración del sistema de visión"""
    # Cámara
    camera_index: int = 0
    camera_resolution: Tuple[int, int] = (320, 240)  # Baja resolución para ahorrar RAM
    camera_fps: int = 5  # Bajo FPS para reducir carga CPU
    
    # Detección de presencia
    presence_check_interval: float = 10.0  # Segundos
    motion_threshold: float = 10.0  # Umbral para detección de movimiento
    
    # Monitoreo de ventanas
    window_check_interval: float = 2.0
    window_title_max_length: int = 50
    
    # Recursos
    max_cpu_usage: float = 15.0  # % Máximo uso de CPU permitido
    max_memory_mb: float = 200.0  # MB máximo de RAM para visión

class UserPresence:
    """Información sobre presencia del usuario"""
    
    def __init__(self):
        self.last_seen = 0
        self.presence_score = 0.0
        self.motion_detected = False
        self.face_detected = False
        
    def update(self, has_motion: bool, has_face: bool):
        """Actualizar estado de presencia"""
        current_time = time.time()
        
        if has_motion or has_face:
            self.last_seen = current_time
            self.presence_score = min(1.0, self.presence_score + 0.2)
        else:
            self.presence_score = max(0.0, self.presence_score - 0.1)
            
        self.motion_detected = has_motion
        self.face_detected = has_face
        
    def is_present(self, threshold: float = 0.3) -> bool:
        """Determinar si el usuario está presente"""
        time_since_seen = time.time() - self.last_seen
        return self.presence_score > threshold and time_since_seen < 300  # 5 minutos
        
    def get_status(self) -> Dict[str, Any]:
        """Obtener estado como diccionario"""
        return {
            "present": self.is_present(),
            "score": self.presence_score,
            "last_seen": self.last_seen,
            "motion": self.motion_detected,
            "face": self.face_detected,
            "seconds_since_seen": time.time() - self.last_seen
        }

class VistaEngine:
    """
    Sistema de percepción de Cilix
    - Captura de cámara para detección de presencia
    - Monitoreo de ventana activa para contexto
    - Optimizado para bajo consumo en sistemas con 8GB RAM
    """
    
    def __init__(self, config: Optional[VisionConfig] = None):
        self.config = config or VisionConfig()
        
        # Componentes
        self.camera = None
        self.face_cascade = None
        
        # Estado
        self.is_active = False
        self.last_frame = None
        self.user_presence = UserPresence()
        self.active_window_info = {}
        
        # Estadísticas
        self.stats = {
            "frames_processed": 0,
            "face_detections": 0,
            "motion_detections": 0,
            "avg_process_time": 0.0,
            "camera_available": False
        }
        
        # Tareas en segundo plano
        self.background_tasks = set()
        
        logger.info("👁️ VistaEngine inicializado")
        
    async def initialize(self):
        """Inicializar sistemas de visión"""
        try:
            # Inicializar cámara (si está disponible)
            camera_success = await self._initialize_camera()
            
            # Cargar clasificador de rostros
            self._load_face_classifier()
            
            # Inicializar detección de ventanas
            window_success = self._initialize_window_detection()
            
            self.is_active = camera_success or window_success
            
            if self.is_active:
                logger.info("✅ VistaEngine inicializado exitosamente")
                return True
            else:
                logger.warning("⚠️ VistaEngine no pudo inicializar componentes principales")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error al inicializar VistaEngine: {e}")
            return False
            
    async def _initialize_camera(self):
        """Inicializar cámara web"""
        if not CV2_AVAILABLE:
            logger.warning("⚠️ OpenCV no disponible")
            return False
            
        try:
            # Intentar abrir cámara
            self.camera = cv2.VideoCapture(self.config.camera_index)
            
            if not self.camera.isOpened():
                logger.warning("⚠️ No se pudo abrir cámara")
                self.camera = None
                return False
                
            # Configurar cámara para baja resolución
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera_resolution[0])
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera_resolution[1])
            self.camera.set(cv2.CAP_PROP_FPS, self.config.camera_fps)
            
            # Verificar que funcione
            ret, frame = self.camera.read()
            if not ret:
                logger.warning("⚠️ No se pudo leer de la cámara")
                self.camera.release()
                self.camera = None
                return False
                
            self.stats["camera_available"] = True
            logger.info(f"📷 Cámara inicializada: {self.config.camera_resolution[0]}x{self.config.camera_resolution[1]} @ {self.config.camera_fps}FPS")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error al inicializar cámara: {e}")
            self.camera = None
            return False
            
    def _load_face_classifier(self):
        """Cargar clasificador de rostros Haar Cascade"""
        if not CV2_AVAILABLE:
            return
            
        try:
            # Intentar cargar clasificador pre-entrenado
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            
            if os.path.exists(cascade_path):
                self.face_cascade = cv2.CascadeClassifier(cascade_path)
                logger.info("😊 Clasificador de rostros cargado")
            else:
                logger.warning("⚠️ No se encontró clasificador de rostros")
                self.face_cascade = None
                
        except Exception as e:
            logger.error(f"❌ Error al cargar clasificador: {e}")
            self.face_cascade = None
            
    def _initialize_window_detection(self):
        """Inicializar detección de ventana activa"""
        if not PYATUIGUI_AVAILABLE:
            logger.warning("⚠️ PyAutoGUI no disponible para detección de ventanas")
            return False
            
        try:
            # Probar obtención de ventana activa
            window_info = self._get_active_window_info()
            
            if window_info:
                logger.info(f"🪟 Detección de ventanas disponible")
                return True
            else:
                logger.warning("⚠️ No se pudo obtener información de ventana")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error en detección de ventanas: {e}")
            return False
            
    def _get_active_window_info(self) -> Optional[Dict]:
        """
        Obtener información de la ventana activa
        
        Returns:
            Diccionario con título, aplicación, etc.
        """
        if not PYATUIGUI_AVAILABLE:
            return None
            
        try:
            # Obtener ventana activa
            active_window = pyautogui.getActiveWindow()
            
            if not active_window:
                return None
                
            window_info = {
                "title": active_window.title[:self.config.window_title_max_length],
                "app": self._extract_app_name(active_window.title),
                "geometry": {
                    "left": active_window.left,
                    "top": active_window.top,
                    "width": active_window.width,
                    "height": active_window.height
                },
                "is_maximized": active_window.isMaximized,
                "is_minimized": active_window.isMinimized,
                "timestamp": time.time()
            }
            
            return window_info
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo ventana activa: {e}")
            return None
            
    def _extract_app_name(self, window_title: str) -> str:
        """
        Extraer nombre de aplicación del título de ventana
        
        Args:
            window_title: Título completo de ventana
            
        Returns:
            Nombre de aplicación estimado
        """
        if not window_title:
            return "Unknown"
            
        # Diccionario de aplicaciones comunes
        app_patterns = {
            "vscode": ["visual studio code", "vscode"],
            "chrome": ["google chrome", "chrome"],
            "firefox": ["mozilla firefox", "firefox"],
            "terminal": ["terminal", "gnome-terminal", "konsole", "xterm"],
            "python": ["python", "idle"],
            "libreoffice": ["libreoffice", "writer", "calc"],
            "gedit": ["gedit"],
            "file manager": ["files", "nautilus", "dolphin"]
        }
        
        title_lower = window_title.lower()
        
        for app_name, patterns in app_patterns.items():
            for pattern in patterns:
                if pattern in title_lower:
                    return app_name
                    
        # Si no coincide, devolver primeras palabras
        words = window_title.split()
        if len(words) > 2:
            return " ".join(words[:2])
        else:
            return window_title[:20]
            
    async def capture_frame(self) -> Optional[Tuple[bool, bool]]:
        """
        Capturar y procesar un fotograma de la cámara
        
        Returns:
            Tupla (motion_detected, face_detected)
        """
        if not self.camera or not self.is_active:
            return False, False
            
        try:
            start_time = time.time()
            
            # Leer fotograma
            ret, frame = self.camera.read()
            if not ret:
                return False, False
                
            # Convertir a escala de grises para procesamiento más rápido
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Detectar movimiento
            motion_detected = self._detect_motion(gray)
            
            # Detectar rostros
            face_detected = self._detect_faces(gray)
            
            # Actualizar último fotograma
            self.last_frame = gray
            
            # Actualizar estadísticas
            process_time = time.time() - start_time
            self.stats["frames_processed"] += 1
            self.stats["avg_process_time"] = (
                self.stats["avg_process_time"] * 0.9 + process_time * 0.1
            )
            
            if motion_detected:
                self.stats["motion_detections"] += 1
            if face_detected:
                self.stats["face_detections"] += 1
                
            return motion_detected, face_detected
            
        except Exception as e:
            logger.error(f"❌ Error procesando fotograma: {e}")
            return False, False
            
    def _detect_motion(self, current_frame) -> bool:
        """Detectar movimiento entre fotogramas"""
        if self.last_frame is None:
            return False
            
        try:
            # Calcular diferencia absoluta
            diff = cv2.absdiff(self.last_frame, current_frame)
            
            # Aplicar umbral
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            
            # Calcular porcentaje de píxeles que cambiaron
            changed_pixels = np.sum(thresh) / 255.0
            total_pixels = thresh.size
            
            change_percentage = (changed_pixels / total_pixels) * 100
            
            # Verificar si supera el umbral
            return change_percentage > self.config.motion_threshold
            
        except Exception as e:
            logger.error(f"❌ Error en detección de movimiento: {e}")
            return False
            
    def _detect_faces(self, gray_frame) -> bool:
        """Detectar rostros en el fotograma"""
        if not self.face_cascade:
            return False
            
        try:
            # Detectar rostros (escala reducida para velocidad)
            faces = self.face_cascade.detectMultiScale(
                gray_frame,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30)
            )
            
            return len(faces) > 0
            
        except Exception as e:
            logger.error(f"❌ Error en detección de rostros: {e}")
            return False
            
    def check_user_presence(self) -> bool:
        """
        Verificar si el usuario está presente
        
        Returns:
            True si el usuario está presente
        """
        if not self.is_active:
            return False
            
        return self.user_presence.is_present()
        
    def get_active_window(self) -> Dict:
        """
        Obtener información de la ventana activa
        
        Returns:
            Diccionario con información de ventana
        """
        window_info = self._get_active_window_info()
        
        if window_info:
            self.active_window_info = window_info
            
        return self.active_window_info.copy()
        
    async def start_presence_monitoring(self, callback=None):
        """
        Iniciar monitoreo continuo de presencia
        
        Args:
            callback: Función a llamar cuando cambia el estado
        """
        if not self.is_active:
            logger.warning("⚠️ VistaEngine no está activo")
            return
            
        logger.info("👀 Iniciando monitoreo de presencia...")
        
        async def monitor_presence():
            last_window_check = 0
            
            while self.is_active:
                try:
                    current_time = time.time()
                    
                    # Verificar presencia por cámara
                    if self.camera:
                        motion, face = await self.capture_frame()
                        self.user_presence.update(motion, face)
                        
                        # Llamar callback si hay cambio significativo
                        if callback and (motion or face):
                            await callback({
                                "type": "presence_update",
                                "presence": self.user_presence.get_status(),
                                "timestamp": current_time
                            })
                    
                    # Verificar ventana activa periódicamente
                    if current_time - last_window_check > self.config.window_check_interval:
                        window_info = self.get_active_window()
                        
                        if window_info and callback:
                            await callback({
                                "type": "window_update",
                                "window": window_info,
                                "timestamp": current_time
                            })
                            
                        last_window_check = current_time
                    
                    # Esperar antes del siguiente ciclo
                    await asyncio.sleep(1.0 / self.config.camera_fps)
                    
                except Exception as e:
                    logger.error(f"❌ Error en monitoreo de presencia: {e}")
                    await asyncio.sleep(5.0)
                    
        # Iniciar tarea
        task = asyncio.create_task(monitor_presence())
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        
        logger.info("✅ Monitoreo de presencia iniciado")
        
    def get_system_status(self) -> Dict[str, Any]:
        """Obtener estado del sistema de visión"""
        return {
            "active": self.is_active,
            "camera_available": self.stats["camera_available"],
            "face_detector_loaded": self.face_cascade is not None,
            "presence": self.user_presence.get_status(),
            "active_window": self.active_window_info,
            "stats": self.stats.copy()
        }
        
    def cleanup(self):
        """Limpiar recursos"""
        try:
            self.is_active = False
            
            # Detener cámara
            if self.camera:
                self.camera.release()
                self.camera = None
                
            # Cancelar tareas en segundo plano
            for task in self.background_tasks:
                task.cancel()
                
            if self.background_tasks:
                asyncio.gather(*self.background_tasks, return_exceptions=True)
                
            logger.info("🧹 VistaEngine limpiado")
            
        except Exception as e:
            logger.error(f"❌ Error limpiando VistaEngine: {e}")

# Importar numpy aquí para evitar error
import numpy as np

# Función de prueba
async def test_vista_engine():
    """Probar VistaEngine"""
    print("🧪 Probando VistaEngine...")
    
    engine = VistaEngine()
    
    # Inicializar
    print("🔧 Inicializando...")
    success = await engine.initialize()
    
    if not success:
        print("⚠️ VistaEngine no se pudo inicializar completamente")
        print("💡 Asegúrate de tener cámara conectada y dependencias instaladas")
        
    # Mostrar estado
    status = engine.get_system_status()
    print(f"\n📊 Estado del sistema:")
    print(f"  Activo: {status['active']}")
    print(f"  Cámara disponible: {status['camera_available']}")
    print(f"  Detector de rostros: {status['face_detector_loaded']}")
    
    # Probar ventana activa
    print("\n🪟 Ventana activa:")
    window_info = engine.get_active_window()
    if window_info:
        print(f"  Título: {window_info.get('title', 'N/A')}")
        print(f"  Aplicación: {window_info.get('app', 'N/A')}")
    else:
        print("  No se pudo obtener información de ventana")
        
    # Probar presencia (simulado)
    print("\n👤 Estado de presencia:")
    presence_status = engine.user_presence.get_status()
    print(f"  Presente: {presence_status['present']}")
    print(f"  Puntuación: {presence_status['score']:.2f}")
    
    # Limpiar
    engine.cleanup()
    print("\n✅ Pruebas completadas")

if __name__ == "__main__":
    asyncio.run(test_vista_engine())