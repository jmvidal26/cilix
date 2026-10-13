#!/usr/bin/env python3
"""
Servidor principal de Cilix - FastAPI con WebSockets
Orquestador de todos los subsistemas: IA, voz, visión y control
Optimizado para sistemas con 8GB RAM
"""

import asyncio
import json
import logging
import sys
import time
from typing import Dict, List, Optional, Any
from enum import Enum

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import psutil

# Importar módulos de Cilix
try:
    from core_ia import CoreIA, AIMode
    from audio_engine import AudioEngine
    from vista_engine import VistaEngine
    from os_controller import OSController
except ImportError as e:
    print(f"⚠️  Error al importar módulos: {e}")
    print("Instala las dependencias: pip install -r requirements.txt")
    sys.exit(1)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('cilix_server.log')
    ]
)
logger = logging.getLogger(__name__)

class ConnectionManager:
    """Gestiona conexiones WebSocket activas"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.message_history: List[Dict] = []
        self.max_history = 50
        
    async def connect(self, websocket: WebSocket):
        """Aceptar nueva conexión WebSocket"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"✅ Nueva conexión WebSocket. Total: {len(self.active_connections)}")
        
    async def disconnect(self, websocket: WebSocket):
        """Eliminar conexión desconectada"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"🔌 Conexión WebSocket cerrada. Restantes: {len(self.active_connections)}")
            
    async def send_personal_message(self, message: Dict, websocket: WebSocket):
        """Enviar mensaje a un cliente específico"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"❌ Error al enviar mensaje: {e}")
            
    async def broadcast(self, message: Dict):
        """Enviar mensaje a todos los clientes conectados"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"❌ Error en broadcast: {e}")
                disconnected.append(connection)
                
        # Limpiar conexiones desconectadas
        for connection in disconnected:
            await self.disconnect(connection)
            
    def add_to_history(self, message: Dict):
        """Agregar mensaje al historial"""
        self.message_history.append(message)
        if len(self.message_history) > self.max_history:
            self.message_history.pop(0)
            
    def get_history(self) -> List[Dict]:
        """Obtener historial de mensajes"""
        return self.message_history.copy()

class CilixServer:
    """Servidor principal de Cilix que coordina todos los subsistemas"""
    
    def __init__(self, dev_mode: bool = False):
        self.dev_mode = dev_mode
        self.connection_manager = ConnectionManager()
        
        # Instanciar subsistemas
        logger.info("🚀 Inicializando subsistemas de Cilix...")
        
        # Sistema de IA (modo perezoso para ahorrar RAM)
        self.ai_system = CoreIA(dev_mode=dev_mode)
        
        # Motor de audio (inicialización diferida)
        self.audio_engine = None
        
        # Motor de visión (inicialización diferida)
        self.vista_engine = None
        
        # Controlador del sistema
        self.os_controller = OSController()
        
        # Estado del sistema
        self.system_status = {
            "ram_usage": 0,
            "cpu_usage": 0,
            "ai_loaded": False,
            "voice_active": False,
            "vision_active": False,
            "active_mode": "Ri"
        }
        
        # Configuración
        self.settings = {
            "ai_model": "qwen2.5:1.5b",
            "voice_model": "female-light",
            "auto_start": True,
            "transparency": 0.9,
            "voice_enabled": True,
            "vision_enabled": False  # Desactivado por defecto para ahorrar RAM
        }
        
        # Tareas en segundo plano
        self.background_tasks = set()
        
        logger.info("✅ Cilix Server inicializado")
        
    async def initialize_audio_engine(self):
        """Inicializar motor de audio bajo demanda"""
        if not self.audio_engine:
            try:
                self.audio_engine = AudioEngine(voice_model=self.settings["voice_model"])
                logger.info("🎵 Motor de audio inicializado")
            except Exception as e:
                logger.error(f"❌ Error al inicializar audio engine: {e}")
                return False
        return True
        
    async def initialize_vista_engine(self):
        """Inicializar motor de visión bajo demanda"""
        if not self.vista_engine and self.settings["vision_enabled"]:
            try:
                self.vista_engine = VistaEngine()
                logger.info("👁️  Motor de visión inicializado")
            except Exception as e:
                logger.error(f"❌ Error al inicializar vista engine: {e}")
                return False
        return True
        
    async def update_system_status(self):
        """Actualizar estado del sistema periódicamente"""
        self.system_status["ram_usage"] = psutil.virtual_memory().percent
        self.system_status["cpu_usage"] = psutil.cpu_percent(interval=0.1)
        self.system_status["ai_loaded"] = self.ai_system.is_model_loaded()
        
        # Enviar actualización a clientes
        await self.connection_manager.broadcast({
            "type": "system_status",
            **self.system_status,
            "timestamp": time.time()
        })
        
    async def handle_websocket_message(self, websocket: WebSocket, data: Dict):
        """Procesar mensaje WebSocket entrante"""
        message_type = data.get("type")
        logger.info(f"📨 Mensaje recibido: {message_type}")
        
        # Agregar al historial
        self.connection_manager.add_to_history(data)
        
        try:
            if message_type == "init":
                # Cliente se presenta
                await self.connection_manager.send_personal_message({
                    "type": "init_response",
                    "status": "ready",
                    "version": "1.0",
                    "settings": self.settings,
                    "system_status": self.system_status
                }, websocket)
                
            elif message_type == "user_message":
                # Mensaje de usuario para la IA
                await self.handle_user_message(data, websocket)
                
            elif message_type == "start_listening":
                # Iniciar escucha de voz
                await self.handle_start_listening(websocket)
                
            elif message_type == "stop_listening":
                # Detener escucha de voz
                await self.handle_stop_listening(websocket)
                
            elif message_type == "switch_mode":
                # Cambiar modo de IA (Ri/Re)
                await self.handle_switch_mode(data, websocket)
                
            elif message_type == "voice_mode":
                # Activar/desactivar modo voz
                await self.handle_voice_mode(data, websocket)
                
            elif message_type == "get_system_status":
                # Obtener estado del sistema
                await self.handle_get_system_status(websocket)
                
            elif message_type == "update_settings":
                # Actualizar configuración
                await self.handle_update_settings(data, websocket)
                
            elif message_type == "execute_command":
                # Ejecutar comando del sistema
                await self.handle_execute_command(data, websocket)
                
            else:
                logger.warning(f"⚠️ Tipo de mensaje desconocido: {message_type}")
                await self.connection_manager.send_personal_message({
                    "type": "error",
                    "message": f"Tipo de mensaje desconocido: {message_type}",
                    "code": "unknown_message_type"
                }, websocket)
                
        except Exception as e:
            logger.error(f"❌ Error al procesar mensaje: {e}")
            await self.connection_manager.send_personal_message({
                "type": "error",
                "message": f"Error interno: {str(e)}",
                "code": "internal_error"
            }, websocket)
            
    async def handle_user_message(self, data: Dict, websocket: WebSocket):
        """Procesar mensaje de usuario y obtener respuesta de la IA"""
        message = data.get("message", "").strip()
        requested_mode = data.get("mode", "Ri")
        
        if not message:
            await self.connection_manager.send_personal_message({
                "type": "error",
                "message": "Mensaje vacío",
                "code": "empty_message"
            }, websocket)
            return
            
        # Actualizar modo activo si se solicita cambio
        if requested_mode != self.system_status["active_mode"]:
            await self.switch_ai_mode(requested_mode)
            
        # Enviar indicador de procesamiento
        await self.connection_manager.send_personal_message({
            "type": "processing",
            "status": "ai_thinking"
        }, websocket)
        
        try:
            # Obtener respuesta de la IA
            response = await self.ai_system.process_message(
                message=message,
                mode=self.system_status["active_mode"]
            )
            
            # Actualizar emoción detectada
            emotion = response.get("emotion", "neutral")
            await self.update_emotion(emotion)
            
            # Si el modo voz está activo, generar audio
            audio_path = None
            if self.settings["voice_enabled"]:
                audio_path = await self.generate_audio(response["response"])
                
            # Enviar respuesta al cliente
            await self.connection_manager.send_personal_message({
                "type": "ai_response",
                "message": response["response"],
                "mode": self.system_status["active_mode"],
                "emotion": emotion,
                "audio_path": audio_path,
                "duration": response.get("duration", 0),
                "timestamp": time.time()
            }, websocket)
            
        except Exception as e:
            logger.error(f"❌ Error en IA: {e}")
            await self.connection_manager.send_personal_message({
                "type": "error",
                "message": f"Error en IA: {str(e)}",
                "code": "ai_error"
            }, websocket)
            
    async def handle_start_listening(self, websocket: WebSocket):
        """Iniciar escucha de voz"""
        if not await self.initialize_audio_engine():
            await self.connection_manager.send_personal_message({
                "type": "error",
                "message": "Motor de audio no disponible",
                "code": "audio_not_available"
            }, websocket)
            return
            
        try:
            # Notificar que se está escuchando
            await self.connection_manager.send_personal_message({
                "type": "voice_status",
                "status": "listening",
                "timestamp": time.time()
            }, websocket)
            
            # Iniciar grabación (esto sería asíncrono en producción)
            # Por ahora simulamos
            logger.info("🎤 Escuchando...")
            
        except Exception as e:
            logger.error(f"❌ Error al iniciar escucha: {e}")
            
    async def handle_stop_listening(self, websocket: WebSocket):
        """Detener escucha de voz y transcribir"""
        if not self.audio_engine:
            return
            
        try:
            # Notificar que se está procesando
            await self.connection_manager.send_personal_message({
                "type": "voice_status",
                "status": "processing",
                "timestamp": time.time()
            }, websocket)
            
            # Aquí se transcribiría el audio grabado
            # Por ahora usamos texto simulado
            transcript = "Hola Cilix, ¿cómo estás?"
            
            # Enviar transcripción
            await self.connection_manager.send_personal_message({
                "type": "voice_status",
                "status": "transcribed",
                "text": transcript,
                "timestamp": time.time()
            }, websocket)
            
        except Exception as e:
            logger.error(f"❌ Error al detener escucha: {e}")
            
    async def switch_ai_mode(self, mode: str):
        """Cambiar entre Ri y Re"""
        old_mode = self.system_status["active_mode"]
        
        if mode == "Re" and old_mode == "Ri":
            # Cargar modelo Re bajo demanda
            success = await self.ai_system.load_re_model()
            if success:
                self.system_status["active_mode"] = "Re"
                logger.info(f"🔁 Cambiado a modo Re")
            else:
                logger.error("❌ No se pudo cargar modelo Re")
        elif mode == "Ri" and old_mode == "Re":
            # Descargar modelo Re para liberar RAM
            await self.ai_system.unload_re_model()
            self.system_status["active_mode"] = "Ri"
            logger.info(f"🔁 Cambiado a modo Ri")
            
    async def generate_audio(self, text: str) -> Optional[str]:
        """Generar audio para texto usando TTS"""
        if not await self.initialize_audio_engine():
            return None
            
        try:
            audio_path, duration = self.audio_engine.text_to_speech(text)
            
            # Enviar información de lip sync
            await self.connection_manager.broadcast({
                "type": "lip_sync",
                "active": True,
                "duration": duration,
                "timestamp": time.time()
            })
            
            return audio_path
            
        except Exception as e:
            logger.error(f"❌ Error al generar audio: {e}")
            return None
            
    async def update_emotion(self, emotion: str):
        """Actualizar emoción actual y notificar clientes"""
        await self.connection_manager.broadcast({
            "type": "emotion_update",
            "emotion": emotion,
            "intensity": 0.7,
            "timestamp": time.time()
        })
        
    async def handle_switch_mode(self, data: Dict, websocket: WebSocket):
        """Manejador para cambio de modo"""
        mode = data.get("mode", "Ri")
        await self.switch_ai_mode(mode)
        
        await self.connection_manager.send_personal_message({
            "type": "mode_switched",
            "mode": mode,
            "timestamp": time.time()
        }, websocket)
        
    async def handle_voice_mode(self, data: Dict, websocket: WebSocket):
        """Manejador para modo voz"""
        active = data.get("active", False)
        self.settings["voice_enabled"] = active
        
        await self.connection_manager.send_personal_message({
            "type": "settings_updated",
            "setting": "voice_enabled",
            "value": active,
            "timestamp": time.time()
        }, websocket)
        
    async def handle_get_system_status(self, websocket: WebSocket):
        """Manejador para estado del sistema"""
        await self.update_system_status()
        
    async def handle_update_settings(self, data: Dict, websocket: WebSocket):
        """Manejador para actualizar configuración"""
        settings = data.get("settings", {})
        self.settings.update(settings)
        
        # Reinicializar motores si es necesario
        if "voice_model" in settings:
            self.audio_engine = None  # Forzar reinicialización
            
        await self.connection_manager.send_personal_message({
            "type": "settings_updated",
            "settings": self.settings,
            "timestamp": time.time()
        }, websocket)
        
    async def handle_execute_command(self, data: Dict, websocket: WebSocket):
        """Manejador para ejecutar comandos del sistema"""
        command = data.get("command", "")
        if not command:
            return
            
        try:
            result = self.os_controller.execute_safe_command(command)
            await self.connection_manager.send_personal_message({
                "type": "command_result",
                "command": command,
                "result": result,
                "success": True,
                "timestamp": time.time()
            }, websocket)
            
        except Exception as e:
            await self.connection_manager.send_personal_message({
                "type": "command_result",
                "command": command,
                "result": str(e),
                "success": False,
                "timestamp": time.time()
            }, websocket)
            
    async def start_background_tasks(self):
        """Iniciar tareas en segundo plano"""
        # Actualizar estado del sistema cada 5 segundos
        async def update_status_task():
            while True:
                try:
                    await self.update_system_status()
                    await asyncio.sleep(5)
                except Exception as e:
                    logger.error(f"❌ Error en tarea de estado: {e}")
                    await asyncio.sleep(10)
                    
        task = asyncio.create_task(update_status_task())
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        
        # Tarea de monitoreo de visión si está habilitada
        if self.settings["vision_enabled"]:
            async def vision_monitor_task():
                while True:
                    try:
                        await self.initialize_vista_engine()
                        if self.vista_engine:
                            # Verificar presencia de usuario
                            user_present = self.vista_engine.check_user_presence()
                            if not user_present:
                                # Usuario ausente, posiblemente reducir actividad
                                pass
                        await asyncio.sleep(10)
                    except Exception as e:
                        logger.error(f"❌ Error en tarea de visión: {e}")
                        await asyncio.sleep(30)
                        
            task = asyncio.create_task(vision_monitor_task())
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)
            
    async def cleanup(self):
        """Limpiar recursos antes de cerrar"""
        logger.info("🧹 Limpiando recursos de Cilix...")
        
        # Cancelar tareas en segundo plano
        for task in self.background_tasks:
            task.cancel()
            
        # Esperar que todas las tareas se cancelen
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
            
        # Limpiar subsistemas
        if self.audio_engine:
            self.audio_engine.cleanup()
            
        if self.vista_engine:
            self.vista_engine.cleanup()
            
        await self.ai_system.cleanup()
        
        logger.info("✅ Recursos limpiados")

# Crear aplicación FastAPI
app = FastAPI(title="Cilix Server", version="1.0")

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, restringir
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instancia global del servidor
server_instance = None

@app.on_event("startup")
async def startup_event():
    """Evento de inicio del servidor"""
    global server_instance
    dev_mode = "--dev" in sys.argv
    server_instance = CilixServer(dev_mode=dev_mode)
    await server_instance.start_background_tasks()
    logger.info("🚀 Servidor Cilix iniciado")
    
@app.on_event("shutdown")
async def shutdown_event():
    """Evento de cierre del servidor"""
    global server_instance
    if server_instance:
        await server_instance.cleanup()
    logger.info("🛑 Servidor Cilix detenido")
    
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Endpoint principal de WebSocket"""
    await server_instance.connection_manager.connect(websocket)
    
    try:
        while True:
            # Recibir mensaje
            data = await websocket.receive_json()
            # Procesar mensaje
            await server_instance.handle_websocket_message(websocket, data)
            
    except WebSocketDisconnect:
        await server_instance.connection_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"❌ Error en WebSocket: {e}")
        await server_instance.connection_manager.disconnect(websocket)
        
@app.get("/")
async def root():
    """Endpoint raíz para verificación de salud"""
    return {
        "status": "online",
        "service": "Cilix Server",
        "version": "1.0",
        "websocket_endpoint": "/ws"
    }
    
@app.get("/health")
async def health_check():
    """Endpoint de verificación de salud"""
    return JSONResponse(
        content={
            "status": "healthy",
            "timestamp": time.time(),
            "ram_usage": psutil.virtual_memory().percent,
            "active_connections": len(server_instance.connection_manager.active_connections)
        }
    )
    
@app.get("/status")
async def get_status():
    """Obtener estado detallado del sistema"""
    if not server_instance:
        raise HTTPException(status_code=503, detail="Servidor no inicializado")
        
    return JSONResponse(content={
        "system_status": server_instance.system_status,
        "settings": server_instance.settings,
        "active_connections": len(server_instance.connection_manager.active_connections),
        "message_history_count": len(server_instance.connection_manager.message_history)
    })

if __name__ == "__main__":
    # Parsear argumentos
    dev_mode = "--dev" in sys.argv
    host = "127.0.0.1"
    port = 8765
    
    logger.info(f"🌐 Iniciando servidor Cilix en {host}:{port}")
    logger.info(f"🔧 Modo desarrollo: {dev_mode}")
    logger.info("📡 WebSocket disponible en: ws://localhost:8765/ws")
    
    # Ejecutar servidor
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info" if dev_mode else "warning",
        access_log=dev_mode
    )