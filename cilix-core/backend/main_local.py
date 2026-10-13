#!/usr/bin/env python3
"""
Servidor principal de Cilix - 100% Local (sin APIs externas)
Usa solo Ollama para IA y modelos locales para todo
Optimizado para 8GB RAM
"""

import asyncio
import json
import logging
import sys
import time
from typing import Dict, List, Optional, Any
from enum import Enum

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import psutil

# Importar módulos de Cilix
try:
    from core_ia import CoreIA, AIMode
    from audio_engine import AudioEngine
    from vtuber_engine import VTuberEngine, Emotion
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
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"✅ Nueva conexión WebSocket. Total: {len(self.active_connections)}")
        
    async def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"🔌 Conexión WebSocket cerrada. Restantes: {len(self.active_connections)}")
            
    async def send_personal_message(self, message: Dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"❌ Error al enviar mensaje: {e}")
            
    async def broadcast(self, message: Dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"❌ Error en broadcast: {e}")
                disconnected.append(connection)
                
        for connection in disconnected:
            await self.disconnect(connection)
            
    def add_to_history(self, message: Dict):
        self.message_history.append(message)
        if len(self.message_history) > self.max_history:
            self.message_history.pop(0)

class CilixServer:
    """Servidor principal de Cilix 100% local"""
    
    def __init__(self, dev_mode: bool = False):
        self.dev_mode = dev_mode
        self.connection_manager = ConnectionManager()
        
        # Instanciar subsistemas
        logger.info("🚀 Inicializando subsistemas de Cilix...")
        
        # Sistema de IA (solo Ollama local)
        self.ai_system = CoreIA(dev_mode=dev_mode)
        
        # Motor de audio
        self.audio_engine = None
        
        # Motor VTuber
        self.vtuber_engine = None
        
        # Controlador del sistema
        self.os_controller = OSController()
        
        # Estado
        self.system_status = {
            "ram_usage": 0,
            "cpu_usage": 0,
            "backend": "Ollama (local)",
            "memory_enabled": True,
            "active_mode": "general"
        }
        
        # Configuración
        self.settings = {
            "auto_unload_re": True,
            "voice_enabled": True,
            "vision_enabled": False,
            " vtuber_enabled": True
        }
        
        self.background_tasks = set()
        
        logger.info("✅ Cilix Server 100% local inicializado")
        
    async def initialize_audio_engine(self):
        if not self.audio_engine:
            try:
                self.audio_engine = AudioEngine()
                await self.audio_engine.initialize()
                logger.info("🎵 Motor de audio inicializado")
            except Exception as e:
                logger.error(f"❌ Error al inicializar audio engine: {e}")
                return False
        return True
        
    async def initialize_vtuber_engine(self):
        if not self.vtuber_engine and self.settings.get("vtuber_enabled", True):
            try:
                self.vtuber_engine = VTuberEngine()
                await self.vtuber_engine.initialize()
                logger.info("🎭 Motor VTuber inicializado")
            except Exception as e:
                logger.error(f"❌ Error al inicializar vtuber engine: {e}")
                return False
        return True
        
    async def update_system_status(self):
        self.system_status["ram_usage"] = psutil.virtual_memory().percent
        self.system_status["cpu_usage"] = psutil.cpu_percent(interval=0.1)
        
        await self.connection_manager.broadcast({
            "type": "status",
            **self.system_status,
            "timestamp": time.time()
        })
        
    async def handle_websocket_message(self, websocket: WebSocket, data: Dict):
        message_type = data.get("type")
        logger.info(f"📨 Mensaje recibido: {message_type}")
        
        self.connection_manager.add_to_history(data)
        
        try:
            if message_type == "init":
                await self.connection_manager.send_personal_message({
                    "type": "init_response",
                    "status": "ready",
                    "version": "1.2",
                    "backend": self.system_status["backend"],
                    "settings": self.settings
                }, websocket)
                
            elif message_type == "chat":
                await self.handle_chat_message(data, websocket)
                
            elif message_type == "start_listening":
                await self.handle_start_listening(websocket)
                
            elif message_type == "stop_listening":
                await self.handle_stop_listening(websocket)
                
            elif "get_status":
                await self.update_system_status()
                
            elif message_type == "get_system_status":
                await self.connection_manager.send_personal_message({
                    "type": "status",
                    **self.system_status
                }, websocket)
                
            else:
                logger.warning(f"⚠️ Tipo de mensaje desconocido: {message_type}")
                
        except Exception as e:
            logger.error(f"❌ Error al procesar mensaje: {e}")
            await self.connection_manager.send_personal_message({
                "type": "error",
                "message": f"Error interno: {str(e)}",
                "code": "internal_error"
            }, websocket)
            
    async def handle_chat_message(self, data: Dict, websocket: WebSocket):
        message = data.get("message", "").strip()
        
        if not message:
            await self.connection_manager.send_personal_message({
                "type": "error",
                "message": "Mensaje vacío"
            }, websocket)
            return
            
        # Enviar indicador de procesamiento
        await self.connection_manager.send_personal_message({
            "type": "status",
            "state": "thinking"
        }, websocket)
        
        try:
            # Obtener respuesta de la IA
            response = await self.ai_system.process_message(
                message=message,
                mode="general"
            )
            
            # Actualizar estado
            emotion = response.get("emotion", "neutral")
            
            # Si el modo voz está activo, generar audio
            audio_path = None
            if self.settings.get("voice_enabled", True):
                audio_path = await self.generate_audio(response["response"])
                
            # Enviar respuesta
            await self.connection_manager.send_personal_message({
                "type": "chat_response",
                "message": response["response"],
                "emotion": emotion,
                "audio_path": audio_path,
                "duration": response.get("duration", 0),
                "timestamp": time.time()
            }, websocket)
            
            # Actualizar emoción del VTuber
            if self.vtuber_engine:
                await self.vtuber_engine.set_emotion(Emotion(emotion), 0.7)
                
        except Exception as e:
            logger.error(f"❌ Error en IA: {e}")
            await self.connection_manager.send_personal_message({
                "type": "error",
                "message": f"Error en IA: {str(e)}"
            }, websocket)
            
    async def generate_audio(self, text: str) -> Optional[str]:
        if not await self.initialize_audio_engine():
            return None
            
        try:
            audio_path, duration = self.audio_engine.text_to_speech(text)
            return audio_path
        except Exception as e:
            logger.error(f"❌ Error al generar audio: {e}")
            return None
            
    async def handle_start_listening(self, websocket: WebSocket):
        if not await self.initialize_audio_engine():
            return
            
        try:
            await self.connection_manager.send_personal_message({
                "type": "voice_status",
                "status": "listening"
            }, websocket)
        except Exception as e:
            logger.error(f"❌ Error al iniciar escucha: {e}")
            
    async def handle_stop_listening(self, websocket: WebSocket):
        if not self.audio_engine:
            return
            
        try:
            await self.connection_manager.send_personal_message({
                "type": "voice_status",
                "status": "idle"
            }, websocket)
        except Exception as e:
            logger.error(f"❌ Error al detener escucha: {e}")
            
    async def start_background_tasks(self):
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
        
    async def cleanup(self):
        logger.info("🧹 Limpiando recursos de Cilix...")
        
        for task in self.background_tasks:
            task.cancel()
            
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
            
        if self.audio_engine:
            self.audio_engine.cleanup()
            
        if self.vtuber_engine:
            self.vtuber_engine.cleanup()
            
        await self.ai_system.cleanup()

# Crear aplicación FastAPI
app = FastAPI(title="Cilix Server Local", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

server_instance = None

@app.on_event("startup")
async def startup_event():
    global server_instance
    dev_mode = "--dev" in sys.argv
    server_instance = CilixServer(dev_mode=dev_mode)
    await server_instance.start_background_tasks()
    logger.info("🚀 Servidor Cilix 100% local iniciado")
    
@app.on_event("shutdown")
async def shutdown_event():
    global server_instance
    if server_instance:
        await server_instance.cleanup()
    logger.info("🛑 Servidor Cilix detenido")
    
@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Cilix Server Local v1.2",
        "version": "1.2",
        "backend": "Ollama (100% local)",
        "websocket_endpoint": "/ws"
    }
    
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "ram_usage": psutil.virtual_memory().percent,
        "active_connections": len(server_instance.connection_manager.active_connections) if server_instance else 0
    }
    
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await server_instance.connection_manager.connect(websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            await server_instance.handle_websocket_message(websocket, data)
            
    except WebSocketDisconnect:
        await server_instance.connection_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"❌ Error en WebSocket: {e}")
        await server_instance.connection_manager.disconnect(websocket)

if __name__ == "__main__":
    dev_mode = "--dev" in sys.argv
    host = "127.0.0.1"
    port = 8765
    
    logger.info(f"🌐 Iniciando servidor Cilix en {host}:{port}")
    logger.info("📡 WebSocket disponible en: ws://localhost:8765/ws")
    logger.info("🚫 USO DE APIS EXTERNAS: DESACTIVADO")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info" if dev_mode else "warning",
        access_log=dev_mode
    )