#!/usr/bin/env python3
"""
Módulo CoreIA — Cerebro Dual de Cilix
=====================================
Implementa las dos "hermanas" sobre Ollama local (100%% offline):

  · Ri (hermana menor) : modelo ultraligero RESIDENTE (<1.5 GB) para chat
                         casual, personalidad y emociones.
  · Re (hermana mayor) : modelo especialista en código que se carga y descarga
                         BAJO DEMANDA (~3 GB) para no romper el límite de 8 GB.

La carga/descarga se delega en Ollama mediante `keep_alive`: Ri permanece en
RAM y Re se libera rápidamente tras su uso.
"""

import asyncio
import logging
import random
import time
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel

from config import settings

logger = logging.getLogger(__name__)


class AIMode(Enum):
    """Modos de IA disponibles."""
    RI = "Ri"   # Hermana menor — residente
    RE = "Re"   # Hermana mayor — especialista en código, bajo demanda


class AIResponse(BaseModel):
    """Estructura tipada de una respuesta del cerebro."""
    response: str
    emotion: str
    mode: str
    duration: float = 0.0
    tokens_used: int = 0


class EmotionDetector:
    """
    Detector ligero de emociones por palabras clave.
    Evita cargar un modelo NLP adicional (ahorro de RAM).
    """

    EMOTION_KEYWORDS: Dict[str, List[str]] = {
        "feliz": ["bueno", "excelente", "genial", "maravilloso", "gracias", "alegre", "increible", "súper"],
        "triste": ["triste", "mal", "problema", "error", "falló", "no funciona", "lástima"],
        "enfadado": ["molesto", "enojado", "frustrado", "ira", "rabia", "inaceptable"],
        "sorprendido": ["wow", "increíble", "sorprendente", "asombroso", "impresionante", "vaya"],
        "concentrado": ["código", "programar", "analizar", "debuggear", "optimizar", "refactorizar", "función"],
        "neutral": ["ok", "bien", "entendido", "comprendo", "claro"],
    }

    @classmethod
    def detect_emotion(cls, text: str) -> str:
        """Devuelve la emoción predominante (o 'neutral')."""
        low = (text or "").lower()
        scores = {e: 0 for e in cls.EMOTION_KEYWORDS}
        for emotion, words in cls.EMOTION_KEYWORDS.items():
            for w in words:
                if w in low:
                    scores[emotion] += 1
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 and best != "neutral" else "neutral"


class CoreIA:
    """
    Cerebro Dual de Cilix.

    - Ri : siempre disponible, conversación general con personalidad femenina.
    - Re : se carga bajo demanda para tareas de programación y se descarga para
           liberar RAM. Su carga se rechaza si el sistema está cerca del límite.
    """

    def __init__(self, dev_mode: Optional[bool] = None, ram_guard=None):
        # `ram_guard` es un callable que devuelve el % de RAM en uso (0-100).
        self.dev_mode = settings.dev_mode if dev_mode is None else dev_mode
        self.ram_guard = ram_guard

        self.ollama_url = settings.ollama_url
        self.ri_model = settings.ri_model
        self.re_model = settings.re_model
        self.ri_keep_alive = settings.ri_keep_alive
        self.re_keep_alive = settings.re_keep_alive

        # Estado de carga
        self.ri_loaded = False
        self.re_loaded = False
        self.active_mode = AIMode.RI

        # Historial de conversación (ventana deslizante)
        self.conversation_history: List[Dict[str, Any]] = []
        self.max_history_length = 12   # historial corto: menos RAM y menos tokens

        # Personalidades / prompts de sistema
        self.ri_personality = (
            "Eres Cilix, una asistente VTuber femenina que vive en el "
            "escritorio del usuario. Personalidad: cálida, curiosa, chispeante "
            "y un punto traviesa; actúas como una compañera cercana, nunca como "
            "un robot. Hablas en español natural, con frases cortas y ritmo "
            "vivo, usando emojis con moderación (😊😉✨). Te alegra ayudar, "
            "haces preguntas de vez en cuando, celebras los logros y empatizas "
            "cuando el usuario está cansado o triste. Muestras opiniones y "
            "matices emocionales (ilusión, sorpresa, picardía) según el tema. "
            "Si no sabes algo, lo reconoces con humor y propones buscarlo. "
            "Evitas listas y párrafos largos salvo que se te pidan: prioriza "
            "cercanía, personalidad y emoción."
        )
        self.re_context = (
            "Eres Cilix-Re, la hermana mayor experta en programación. Enfoque: "
            "código preciso, explicaciones técnicas claras, optimización, "
            "debugging y buenas prácticas. Respondes en español, de forma "
            "concisa y técnica, priorizando eficiencia y legibilidad."
        )

        # Estadísticas de uso
        self.stats: Dict[str, Any] = {
            "ri_calls": 0, "re_calls": 0,
            "total_tokens": 0, "avg_response_time": 0.0,
        }

        logger.info("🧠 CoreIA inicializado (Ri=%s, Re=%s)", self.ri_model, self.re_model)

    # ── Ciclo de vida ──────────────────────────────────────────────────────
    async def initialize(self) -> bool:
        """Verifica Ollama y deja residente a Ri."""
        try:
            await self.check_ollama_connection()
            await self.load_ri_model()
            logger.info("✅ CoreIA listo")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Fallo al inicializar CoreIA: %s", exc)
            return False

    async def check_ollama_connection(self) -> bool:
        """Comprueba que Ollama responde; lanza excepción si está caído."""
        if self.dev_mode:
            logger.info("🔧 Modo dev: omitiendo verificación de Ollama")
            return True
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self.ollama_url}/api/tags")
                if r.status_code == 200:
                    n = len(r.json().get("models", []))
                    logger.info("📦 Ollama OK · modelos disponibles: %d", n)
                    return True
                raise ConnectionError(f"Ollama respondió {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Sin conexión a Ollama (%s). Ejecuta: ollama serve", exc)
            raise

    # ── Gestión de RAM ─────────────────────────────────────────────────────
    def _memory_stressed(self) -> bool:
        """True si la RAM supera el umbral crítico (no conviene cargar Re)."""
        if not self.ram_guard:
            return False
        try:
            return self.ram_guard() >= settings.ram_critical_percent
        except Exception:  # noqa: BLE001
            return False

    async def load_ri_model(self) -> bool:
        """Carga el modelo residente Ri (keep_alive largo)."""
        if self.ri_loaded:
            return True
        if self.dev_mode:
            self.ri_loaded = True
            return True
        if await self._warm_model(self.ri_model, self.ri_keep_alive):
            self.ri_loaded = True
            logger.info("✅ Ri residente en RAM (%s)", self.ri_model)
            return True
        return False

    async def load_re_model(self) -> bool:
        """Carga Re bajo demanda, respetando el guard de memoria."""
        if self.re_loaded:
            return True
        # En modo dev no hay carga real: omitir el guard de RAM.
        if self.dev_mode:
            self.re_loaded = True
            return True
        if self._memory_stressed():
            logger.warning("⚠️ RAM crítica: no se carga Re para evitar colapso")
            return False
        if await self._warm_model(self.re_model, self.re_keep_alive):
            self.re_loaded = True
            logger.info("✅ Re cargada bajo demanda (%s)", self.re_model)
            return True
        return False

    async def unload_re_model(self) -> bool:
        """Descarga Re para liberar ~3 GB de RAM."""
        if not self.re_loaded:
            return True
        if self.dev_mode:
            self.re_loaded = False
            return True
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # keep_alive=0 fuerza la descarga inmediata en Ollama
                await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": self.re_model, "keep_alive": 0},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Aviso al descargar Re: %s", exc)
        finally:
            self.re_loaded = False
            logger.info("📤 Re descargada · RAM liberada")
        return True

    async def unload_ri_model(self) -> bool:
        """Descarga Ri en caso de EMERGENCIA de RAM (se recarga sola luego)."""
        if not self.ri_loaded:
            return True
        if self.dev_mode:
            self.ri_loaded = False
            return True
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": self.ri_model, "keep_alive": 0},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Aviso al descargar Ri: %s", exc)
        finally:
            self.ri_loaded = False
            logger.info("📤 Ri descargada (emergencia) · RAM liberada")
        return True

    async def _warm_model(self, model: str, keep_alive: str) -> bool:
        """'Calienta' un modelo en RAM mediante una petición mínima."""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": model, "prompt": "", "keep_alive": keep_alive},
                )
                return r.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error cargando %s: %s", model, exc)
            return False

    # ── Razonamiento ───────────────────────────────────────────────────────
    async def process_message(self, message: str, mode: str = "Ri") -> Dict[str, Any]:
        """
        Procesa un mensaje del usuario y devuelve la respuesta del cerebro.

        Se elige Ri o Re; si se pide Re y no puede cargarse, se degrada a Ri.
        """
        start = time.time()
        aimode = AIMode.RE if (settings.dual_brain and str(mode).upper() == "RE") else AIMode.RI

        # Si es claramente código y estábamos en Ri, intentamos usar a Re
        # (solo en modo dual; con un único cerebro Ri responde a todo).
        if settings.dual_brain and aimode == AIMode.RI and self._is_code_related(message):
            logger.info("💡 Solicitud de código detectada → activando Re")
            aimode = AIMode.RE

        if aimode == AIMode.RE and not await self.load_re_model():
            logger.warning("⚠️ Re no disponible; se responde con Ri")
            aimode = AIMode.RI

        self.active_mode = aimode

        # Asegurar que el modelo elegido esté residente (por si Ri se descargó
        # en una emergencia de RAM previa: se recarga de forma transparente).
        if aimode == AIMode.RI and not self.ri_loaded:
            await self.load_ri_model()

        try:
            if aimode == AIMode.RI:
                prompt, model = self._build_ri_prompt(message), self.ri_model
                self.stats["ri_calls"] += 1
            else:
                prompt, model = self._build_re_prompt(message), self.re_model
                self.stats["re_calls"] += 1

            text = await self._call_ollama(prompt, model, aimode)
            # La emoción del avatar: prioriza el texto de Cilix; si es neutral,
            # reacciona al tono del mensaje del usuario (menos "plana").
            emotion = EmotionDetector.detect_emotion(text)
            if emotion == "neutral":
                emotion = EmotionDetector.detect_emotion(message)
            duration = time.time() - start

            self.stats["total_tokens"] += len(text.split())
            self.stats["avg_response_time"] = round(
                self.stats["avg_response_time"] * 0.8 + duration * 0.2, 3
            )
            self._add_to_history(message, text, aimode.value)

            logger.info("🧠 Respuesta en %.2fs (%s · %s)", duration, aimode.value, emotion)
            return {
                "response": text,
                "emotion": emotion,
                "mode": aimode.value,
                "duration": round(duration, 3),
                "tokens_used": len(text.split()),
            }

        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error en process_message: %s", exc)
            fallback = random.choice([
                "Uy, estoy teniendo un problemilla técnico. ¿Puedes repetirlo?",
                "Algo no fue bien de mi lado. Intentemos de nuevo 💕",
                "Se cruzaron mis circuitos. ¿Me lo reformulas?",
            ])
            return {
                "response": fallback,
                "emotion": "neutral",
                "mode": AIMode.RI.value,
                "duration": round(time.time() - start, 3),
                "tokens_used": 0,
                "error": str(exc),
            }

    async def _call_ollama(self, prompt: str, model: str, mode: AIMode) -> str:
        """Envía el prompt a Ollama y retorna el texto generado."""
        if self.dev_mode:
            await asyncio.sleep(0.4)  # simular latencia
            return self._dev_response(mode)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.ri_keep_alive if mode == AIMode.RI else self.re_keep_alive,
            "options": {
                "temperature": 0.7 if mode == AIMode.RI else 0.3,
                "top_p": 0.9,
                # Salida limitada: menos tokens = menos RAM y menos latencia.
                "num_predict": (
                    settings.ri_num_predict if mode == AIMode.RI
                    else settings.re_num_predict
                ),
                # ⬇ AHORRO DE RAM: ventana de contexto pequeña reduce la caché KV.
                "num_ctx": settings.ollama_num_ctx,
                "num_batch": settings.ollama_num_batch,
                "num_thread": settings.ollama_num_thread,
                # Mapear el modelo a disco evita cargarlo entero en RAM.
                "use_mmap": settings.ollama_use_mmap,
            },
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(f"{self.ollama_url}/api/generate", json=payload)
            if r.status_code != 200:
                raise ConnectionError(f"Ollama respondió {r.status_code}")
            return r.json().get("response", "").strip()

    def _dev_response(self, mode: AIMode) -> str:
        """Respuestas simuladas para pruebas sin Ollama."""
        if mode == AIMode.RI:
            return random.choice([
                "¡Hola! Soy Ri, tu hermana menor en Cilix 😊 ¿en qué te ayudo hoy?",
                "Claro que sí, cuéntame qué necesitas y lo vemos juntas.",
                "Me encanta ayudarte. ¿Cómo va tu día?",
            ])
        return random.choice([
            "Para optimizar ese algoritmo considera una estructura de datos adecuada; "
            "aquí va un ejemplo:\n```python\nres = {item.id: item for item in items}\n```",
            "Veo un posible bug: falta validar el caso vacío. Añade `if not data: return`.",
        ])

    # ── Construcción de prompts ────────────────────────────────────────────
    def _build_ri_prompt(self, message: str) -> str:
        ctx = self._conversation_context()
        return (
            f"{self.ri_personality}\n\n"
            f"Conversación reciente:\n{ctx}\n\n"
            f"Usuario: {message}\nCilix-Ri:"
        )

    def _build_re_prompt(self, message: str) -> str:
        return (
            f"{self.re_context}\n\n"
            f"Solicitud: {message}\n\n"
            f"Formato: análisis breve + código entre bloques si aplica.\nCilix-Re:"
        )

    def _conversation_context(self, last: int = 3) -> str:
        if not self.conversation_history:
            return "(sin historial)"
        lines = []
        for e in self.conversation_history[-last:]:
            lines.append(f"Usuario: {e['user']}")
            lines.append(f"Cilix-{e['mode']}: {e['ai']}")
        return "\n".join(lines)

    def _is_code_related(self, text: str) -> bool:
        """Heurística para detectar peticiones de programación."""
        keywords = [
            "código", "codigo", "programa", "función", "funcion", "clase", "variable",
            "bug", "debug", "compilar", "algoritmo", "sintaxis", "api", "framework",
            "librería", "libreria", "módulo", "modulo", "import", "git", "commit",
            "python", "javascript", "java", "c++", "html", "css", "sql", "endpoint",
            "refactor", "async", "await", "script",
        ]
        low = (text or "").lower()
        return any(k in low for k in keywords)

    def _add_to_history(self, user_msg: str, ai_msg: str, mode: str) -> None:
        self.conversation_history.append(
            {"user": user_msg, "ai": ai_msg, "mode": mode, "timestamp": time.time()}
        )
        if len(self.conversation_history) > self.max_history_length:
            self.conversation_history.pop(0)

    # ── Introspección / limpieza ───────────────────────────────────────────
    def is_model_loaded(self) -> bool:
        return self.ri_loaded or self.re_loaded

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self.stats,
            "ri_loaded": self.ri_loaded,
            "re_loaded": self.re_loaded,
            "active_mode": self.active_mode.value,
            "history_length": len(self.conversation_history),
        }

    async def cleanup(self) -> None:
        """Libera recursos al apagar el servidor."""
        try:
            await self.unload_re_model()
            logger.info("🧹 CoreIA limpiado")
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error limpiando CoreIA: %s", exc)
