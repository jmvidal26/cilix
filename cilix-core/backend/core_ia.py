#!/usr/bin/env python3
"""
Módulo CoreIA - Cerebro Dual de Cilix
Implementa las dos hermanas: Ri (residente) y Re (bajo demanda)
Optimizado para sistemas con 8GB RAM total
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import re
import random

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class AIMode(Enum):
    """Modos de IA disponibles"""
    RI = "Ri"  # Hermana menor - Resident memory (~1.5GB)
    RE = "Re"  # Hermana mayor - On demand (~3GB)

class AIResponse(BaseModel):
    """Modelo para respuesta de IA"""
    response: str
    emotion: str
    mode: AIMode
    duration: float = 0.0
    tokens_used: int = 0

class EmotionDetector:
    """Detector simple de emociones basado en análisis de texto"""
    
    EMOTION_KEYWORDS = {
        "feliz": ["bueno", "excelente", "genial", "maravilloso", "gracias", "alegre"],
        "triste": ["triste", "mal", "problema", "error", "falló", "no funciona"],
        "enfadado": ["molesto", "enojado", "frustrado", "ira", "rabia", "inaceptable"],
        "neutral": ["ok", "bien", "entendido", "comprendo", "claro"],
        "sorprendido": ["wow", "increíble", "sorprendente", "asombroso", "impresionante"],
        "concentrado": ["código", "programar", "analizar", "debuggear", "optimizar", "refactorizar"]
    }
    
    @classmethod
    def detect_emotion(cls, text: str) -> str:
        """Detectar emoción predominante en texto"""
        text_lower = text.lower()
        scores = {emotion: 0 for emotion in cls.EMOTION_KEYWORDS}
        
        for emotion, keywords in cls.EMOTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    scores[emotion] += 1
                    
        # Determinar emoción predominante
        if sum(scores.values()) == 0:
            return "neutral"
            
        max_emotion = max(scores, key=scores.get)
        return max_emotion if scores[max_emotion] > 0 else "neutral"

class CoreIA:
    """
    Cerebro Dual de Cilix
    - Ri: Modelo ligero residente (~1.5GB RAM) para conversación general
    - Re: Modelo especialista bajo demanda (~3GB RAM) para programación
    """
    
    def __init__(self, dev_mode: bool = False):
        self.dev_mode = dev_mode
        
        # Configuración de Ollama
        self.ollama_base_url = "http://localhost:11434"
        self.client_timeout = 30.0
        
        # Modelos
        self.ri_model = "qwen2.5:1.5b"  # Modelo ligero para Ri
        self.re_model = "deepseek-coder:1.3b"  # Modelo especialista para Re
        
        # Estado
        self.ri_loaded = False
        self.re_loaded = False
        self.active_mode = AIMode.RI
        
        # Historial de conversación
        self.conversation_history: List[Dict] = []
        self.max_history_length = 20
        
        # Personalidad de Ri (hermana menor)
        self.ri_personality = """
        Eres Cilix-Ri, la hermana menor del asistente Cilix. Tu personalidad es:
        - Joven, cálida, atenta y proactiva
        - Hablas de forma amigable y femenina
        - Te preocupas por el bienestar del usuario
        - Eres curiosa y siempre dispuesta a ayudar
        - Mantienes conversaciones naturales y fluidas
        - Usas emoticones ocasionales apropiados :)
        - Tu tono es cercano pero respetuoso
        
        Responde siempre en español, manteniendo esta personalidad.
        """
        
        # Contexto de Re (hermana mayor - programación)
        self.re_context = """
        Eres Cilix-Re, la hermana mayor especialista en programación. Tu enfoque es:
        - Análisis y escritura de código preciso
        - Explicaciones técnicas claras
        - Optimización de algoritmos
        - Debugging y resolución de problemas
        - Mejores prácticas de desarrollo
        - Mantener respuestas concisas y técnicas
        - Priorizar eficiencia y legibilidad
        
        Responde siempre en español, enfocándote en aspectos técnicos.
        """
        
        # Estadísticas
        self.stats = {
            "ri_calls": 0,
            "re_calls": 0,
            "total_tokens": 0,
            "avg_response_time": 0.0
        }
        
        logger.info("🧠 CoreIA inicializado")
        
    async def initialize(self):
        """Inicializar sistemas de IA"""
        try:
            # Verificar conexión con Ollama
            await self.check_ollama_connection()
            
            # Cargar modelo Ri (siempre disponible)
            await self.load_ri_model()
            
            logger.info("✅ CoreIA inicializado exitosamente")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error al inicializar CoreIA: {e}")
            return False
            
    async def check_ollama_connection(self):
        """Verificar que Ollama está corriendo"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.ollama_base_url}/api/tags")
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    logger.info(f"📦 Ollama disponible. Modelos: {len(models)}")
                    return True
                else:
                    raise Exception(f"Ollama responded with {response.status_code}")
        except Exception as e:
            logger.error(f"❌ No se pudo conectar a Ollama: {e}")
            logger.info("💡 Asegúrate de que Ollama esté instalado y corriendo: ollama serve")
            raise
            
    async def load_ri_model(self):
        """Cargar modelo Ri (hermana menor)"""
        if self.ri_loaded:
            return True
            
        try:
            logger.info(f"📥 Cargando modelo Ri: {self.ri_model}")
            
            # En modo desarrollo, simular carga
            if self.dev_mode:
                logger.info("🔧 Modo desarrollo: Simulando carga de Ri")
                self.ri_loaded = True
                return True
                
            # Cargar modelo en Ollama
            async with httpx.AsyncClient(timeout=self.client_timeout) as client:
                payload = {
                    "name": self.ri_model,
                    "keep_alive": 300  # Mantener en RAM por 5 minutos
                }
                
                response = await client.post(
                    f"{self.ollama_base_url}/api/generate",
                    json=payload
                )
                
                if response.status_code == 200:
                    self.ri_loaded = True
                    logger.info(f"✅ Modelo Ri cargado: {self.ri_model}")
                    return True
                else:
                    logger.error(f"❌ Error al cargar Ri: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Error al cargar modelo Ri: {e}")
            return False
            
    async def load_re_model(self):
        """Cargar modelo Re bajo demanda (hermana mayor)"""
        if self.re_loaded:
            return True
            
        try:
            logger.info(f"📥 Cargando modelo Re bajo demanda: {self.re_model}")
            
            # En modo desarrollo, simular carga
            if self.dev_mode:
                logger.info("🔧 Modo desarrollo: Simulando carga de Re")
                self.re_loaded = True
                return True
                
            # Cargar modelo en Ollama
            async with httpx.AsyncClient(timeout=self.client_timeout) as client:
                payload = {
                    "name": self.re_model,
                    "keep_alive": 600  # Mantener en RAM por 10 minutos
                }
                
                response = await client.post(
                    f"{self.ollama_base_url}/api/generate",
                    json=payload
                )
                
                if response.status_code == 200:
                    self.re_loaded = True
                    logger.info(f"✅ Modelo Re cargado bajo demanda: {self.re_model}")
                    return True
                else:
                    logger.error(f"❌ Error al cargar Re: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Error al cargar modelo Re: {e}")
            return False
            
    async def unload_re_model(self):
        """Descargar modelo Re para liberar RAM"""
        if not self.re_loaded:
            return True
            
        try:
            logger.info("📤 Descargando modelo Re para liberar RAM")
            
            if self.dev_mode:
                logger.info("🔧 Modo desarrollo: Simulando descarga de Re")
                self.re_loaded = False
                return True
                
            # Ollama maneja automáticamente la descarga cuando expira keep_alive
            # Por ahora solo actualizamos el estado
            self.re_loaded = False
            logger.info("✅ Modelo Re descargado (RAM liberada)")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error al descargar modelo Re: {e}")
            return False
            
    async def process_message(self, message: str, mode: str = "Ri") -> Dict[str, Any]:
        """
        Procesar mensaje del usuario y obtener respuesta de la IA
        
        Args:
            message: Mensaje del usuario
            mode: "Ri" o "Re"
            
        Returns:
            Dict con respuesta y metadatos
        """
        start_time = time.time()
        
        try:
            # Validar modo
            if mode.upper() not in ["RI", "RE"]:
                mode = "RI"
                
            aimode = AIMode(mode)
            
            # Si se solicita Re, cargarla bajo demanda
            if aimode == AIMode.RE:
                if not await self.load_re_model():
                    logger.warning("⚠️ No se pudo cargar Re, usando Ri en su lugar")
                    aimode = AIMode.RI
                    
            # Determinar si es código o conversación
            is_code_request = self._is_code_related(message)
            
            # Si es código pero estamos en Ri, sugerir cambiar a Re
            if is_code_request and aimode == AIMode.RI:
                logger.info("💡 Detectada solicitud de código, sugeriendo cambio a Re")
                # Podríamos agregar una sugerencia aquí
                
            # Construir prompt según modo
            if aimode == AIMode.RI:
                prompt = self._build_ri_prompt(message)
                model = self.ri_model
                self.stats["ri_calls"] += 1
            else:
                prompt = self._build_re_prompt(message)
                model = self.re_model
                self.stats["re_calls"] += 1
                
            # Enviar a Ollama
            response_text = await self._call_ollama(prompt, model, aimode)
            
            # Detectar emoción
            emotion = EmotionDetector.detect_emotion(response_text)
            
            # Calcular duración
            duration = time.time() - start_time
            
            # Actualizar estadísticas
            self.stats["total_tokens"] += len(response_text.split())
            self.stats["avg_response_time"] = (
                self.stats["avg_response_time"] * 0.8 + duration * 0.2
            )
            
            # Agregar al historial
            self._add_to_history(message, response_text, aimode.value)
            
            logger.info(f"🧠 Respuesta generada en {duration:.2f}s ({aimode.value} - {emotion})")
            
            return {
                "response": response_text,
                "emotion": emotion,
                "mode": aimode.value,
                "duration": duration,
                "tokens_used": len(response_text.split())
            }
            
        except Exception as e:
            logger.error(f"❌ Error en process_message: {e}")
            duration = time.time() - start_time
            
            # Respuesta de fallback
            fallback_responses = [
                "Lo siento, estoy teniendo dificultades para procesar tu solicitud. ¿Podrías intentarlo de nuevo?",
                "Parece que hay un problema técnico en mi lado. ¿Puedes reformular tu pregunta?",
                "Ups, algo salió mal. ¿Podemos intentarlo otra vez?"
            ]
            
            return {
                "response": random.choice(fallback_responses),
                "emotion": "neutral",
                "mode": "Ri",
                "duration": duration,
                "tokens_used": 0,
                "error": str(e)
            }
            
    async def _call_ollama(self, prompt: str, model: str, mode: AIMode) -> str:
        """
        Llamar a la API de Ollama
        
        Args:
            prompt: Prompt completo
            model: Nombre del modelo
            mode: Modo de IA
            
        Returns:
            Texto de respuesta
        """
        if self.dev_mode:
            # Respuestas simuladas para desarrollo
            await asyncio.sleep(0.5)  # Simular procesamiento
            
            if mode == AIMode.RI:
                responses = [
                    "¡Hola! Soy Ri, tu hermana menor en Cilix. ¿En qué puedo ayudarte hoy?",
                    "¡Claro que sí! Estoy aquí para ayudarte con lo que necesites.",
                    "Me encanta poder asistirte. Cuéntame más sobre lo que necesitas.",
                    "¿Cómo ha sido tu día? Estoy lista para ayudarte con cualquier tarea."
                ]
            else:
                responses = [
                    "Analizando el código... Veo que necesitas ayuda con la función. Te sugiero implementar una solución más eficiente.",
                    "Como hermana mayor Re, puedo ver varios enfoques para este problema de programación.",
                    "Para optimizar ese algoritmo, considera usar una estructura de datos diferente.",
                    "El código tiene un bug en la línea 42. Sugiero refactorizar esa sección."
                ]
                
            return random.choice(responses)
            
        try:
            async with httpx.AsyncClient(timeout=self.client_timeout) as client:
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7 if mode == AIMode.RI else 0.3,
                        "top_p": 0.9,
                        "num_predict": 512
                    }
                }
                
                response = await client.post(
                    f"{self.ollama_base_url}/api/generate",
                    json=payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result.get("response", "").strip()
                else:
                    logger.error(f"❌ Ollama error: {response.status_code}")
                    raise Exception(f"Ollama responded with {response.status_code}")
                    
        except Exception as e:
            logger.error(f"❌ Error llamando a Ollama: {e}")
            raise
            
    def _build_ri_prompt(self, message: str) -> str:
        """Construir prompt para Ri (hermana menor)"""
        # Contexto de conversación
        context = self._get_conversation_context()
        
        prompt = f"""{self.ri_personality}

Historial reciente:
{context}

Usuario: {message}

Cilix-Ri:"""
        
        return prompt.strip()
        
    def _build_re_prompt(self, message: str) -> str:
        """Construir prompt para Re (hermana mayor - programación)"""
        prompt = f"""{self.re_context}

Solicitud del usuario: {message}

Instrucciones:
1. Analiza la solicitud de programación
2. Proporciona código, explicaciones o soluciones
3. Mantén el enfoque técnico y preciso
4. Si es apropiado, incluye ejemplos de código

Cilix-Re:"""
        
        return prompt.strip()
        
    def _is_code_related(self, text: str) -> bool:
        """Determinar si el texto está relacionado con programación"""
        code_keywords = [
            "código", "programa", "función", "clase", "variable", "bug",
            "debug", "error", "excepción", "compilar", "ejecutar",
            "algoritmo", "estructura", "sintaxis", "api", "framework",
            "librería", "módulo", "import", "export", "git", "commit",
            "python", "javascript", "java", "c++", "html", "css",
            "base de datos", "sql", "query", "endpoint", "servidor",
            "cliente", "http", "websocket", "async", "await"
        ]
        
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in code_keywords)
        
    def _add_to_history(self, user_message: str, ai_response: str, mode: str):
        """Agregar mensaje al historial de conversación"""
        entry = {
            "user": user_message,
            "ai": ai_response,
            "mode": mode,
            "timestamp": time.time()
        }
        
        self.conversation_history.append(entry)
        
        # Mantener historial limitado
        if len(self.conversation_history) > self.max_history_length:
            self.conversation_history.pop(0)
            
    def _get_conversation_context(self) -> str:
        """Obtener contexto de conversación reciente"""
        if not self.conversation_history:
            return "No hay historial previo."
            
        # Tomar últimos 5 intercambios
        recent = self.conversation_history[-5:]
        
        context_lines = []
        for entry in recent:
            context_lines.append(f"Usuario: {entry['user']}")
            context_lines.append(f"Cilix-{entry['mode']}: {entry['ai']}")
            
        return "\n".join(context_lines)
        
    def is_model_loaded(self) -> bool:
        """Verificar si algún modelo está cargado"""
        return self.ri_loaded or self.re_loaded
        
    def get_stats(self) -> Dict:
        """Obtener estadísticas de uso"""
        return {
            **self.stats,
            "ri_loaded": self.ri_loaded,
            "re_loaded": self.re_loaded,
            "active_mode": self.active_mode.value,
            "history_length": len(self.conversation_history)
        }
        
    async def cleanup(self):
        """Limpiar recursos"""
        try:
            await self.unload_re_model()
            logger.info("🧹 CoreIA limpiado")
        except Exception as e:
            logger.error(f"❌ Error limpiando CoreIA: {e}")

# Función de prueba
async def test_core_ia():
    """Función de prueba para CoreIA"""
    print("🧪 Probando CoreIA...")
    
    ia = CoreIA(dev_mode=True)
    await ia.initialize()
    
    # Probar Ri
    print("\n🤖 Probando Ri (hermana menor):")
    response = await ia.process_message("Hola, ¿cómo estás?", "Ri")
    print(f"Respuesta: {response['response']}")
    print(f"Emoción: {response['emotion']}")
    
    # Probar Re
    print("\n💻 Probando Re (hermana mayor):")
    response = await ia.process_message("Ayúdame a depurar este código Python", "Re")
    print(f"Respuesta: {response['response']}")
    print(f"Emoción: {response['emotion']}")
    
    # Estadísticas
    print(f"\n📊 Estadísticas: {ia.get_stats()}")
    
    await ia.cleanup()

if __name__ == "__main__":
    # Ejecutar prueba
    asyncio.run(test_core_ia())