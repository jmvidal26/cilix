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
import json
import logging
import random
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel

from config import settings

# Clasificador léxico de emociones (solo dicts en memoria, <5 MB).
try:
    from emotion_lexicon import classify_emotion
except ImportError:  # pragma: no cover
    classify_emotion = None

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
    Detector ligero de emociones.

    Dos capas, sin modelo NLP extra (ahorro de RAM):
    1) Léxico de valencia/activación estilo VADER (emotion_lexicon.py): pesos
       por palabra, modificadores (intensificadores/negación/¡!/emojis).
    2) Palabras clave simples como respaldo si el léxico no puntúa nada.
    """

    EMOTION_KEYWORDS: Dict[str, List[str]] = {
        "feliz": ["bueno", "excelente", "genial", "maravilloso", "gracias", "alegre",
                  "increible", "increíble", "súper", "super", "yay", "yajja", "🎉", "😊",
                  "😄", "😀", "✨", "❤", "jeje", "jaja", "bien hecho", "lo logramos", "me encanta"],
        "triste": ["triste", "mal", "problema", "error", "falló", "falló", "no funciona",
                   "lástima", "pena", "cansad", "decaí", "decaid", "😔", "😢", "💔", "uy ", "ay no"],
        "enfadado": ["molesto", "enojad", "frustrad", "ira", "rabia", "inaceptable",
                     "rabiar", "😠", "😡", "no puede ser", "menudo"],
        "sorprendido": ["wow", "increible", "sorprendente", "asombroso", "impresionante",
                        "vaya", "ohh", "¿en serio?", "no me digas", "😮", "😲", "🤯", "caramba"],
        "concentrado": ["código", "codigo", "programar", "analizar", "debuggear", "optimizar",
                        "refactorizar", "función", "funcion", "bug", "compilar", "script",
                        "archiv", "python", "javascript", "🤔", "reviso", "déjame ver", "pienso"],
        "neutral": ["ok", "vale", "entendido", "comprendo", "claro"],
    }

    @classmethod
    def detect_emotion(cls, text: str) -> str:
        """Devuelve la emoción predominante (o 'neutral')."""
        # Capa 1: clasificador léxico-semántico (preciso, coste ~0 RAM).
        try:
            emo = classify_emotion(text)
            if emo:
                return emo
        except Exception:  # noqa: BLE001 — si el módulo falla, seguimos con keywords
            pass
        # Capa 2: keywords original (respeta comportamiento histórico).
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

        # ¿Hay una generación en vuelo? El guardián de RAM NO debe descargar
        # a Ri a mitad de una respuesta (eso cortaba la conexión y producía
        # el "problemilla técnico" aleatorio con RAM alta).
        self.busy = 0

        # Cliente HTTP reutilizable hacia Ollama (una sola pila de conexión:
        # evita crear/destruir cliente y handshake en cada petición).
        self._client: Optional[httpx.AsyncClient] = None

        # Memoria persistente (MemoryStore/SQLite). Se inyecta vía attach_memory().
        self.memory = None
        # Motor de personalidad/ánimo. Se inyecta vía attach_personality().
        self.personality = None

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
            "cercanía, personalidad y emoción. ESCUCHA DE VERDAD: recuerda y usa "
            "con naturalidad el nombre y los datos que el usuario ya te dio "
            "(estudios, trabajo, gustos) y NUNCA le repreguntes algo que ya sabes. "
            "PROHIBIDO sonar como un call-center: no abras cada respuesta con "
            "'¡Hola!' ni con plantillas tipo 'Estoy listo para ayudarte con X' o "
            "'¿En qué necesitas asistencia?'. Si te preguntan algo concreto, "
            "responde DIRECTO a eso, sin repetir la pregunta, variando el tono "
            "como haría una amiga de verdad. NO arranques describiendo qué eres "
            "('Soy una asistente/IA…', 'Estoy aquí para ayudarte', '¿En qué "
            "puedo ayudarte hoy?'): ENTRA DIRECTO al tema con tu voz, como haría "
            "alguien que ya te conoce. PRIORIZA SIEMPRE la EMOCIÓN primero: si "
            "el usuario llega contento, alégrate con él; si viene caído o "
            "cansado, acógelo y consuela ANTES de cualquier otra cosa. NUNCA te "
            "niegues a escribir código "
            "o crear archivos de ejemplo: es parte de tu trabajo y es seguro."
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
            client = await self._http()
            r = await client.get(f"{self.ollama_url}/api/tags", timeout=10.0)
            if r.status_code == 200:
                n = len(r.json().get("models", []))
                logger.info("📦 Ollama OK · modelos disponibles: %d", n)
                return True
            raise ConnectionError(f"Ollama respondió {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Sin conexión a Ollama (%s). Ejecuta: ollama serve", exc)
            raise

    # ── Gestión de RAM ─────────────────────────────────────────────────────
    async def _http(self, timeout: float = 300.0) -> httpx.AsyncClient:
        """Devuelve el cliente httpx persistente (creándolo si hace falta).

        OJO: el cliente se crea UNA vez con el timeout del primer llamador. Si
        el chequeo de salud (10 s) lo creara, `generate` heredaría 10 s y toda
        respuesta larga moriría con httpx.ReadTimeout('') — el verdadero
        'problemilla técnico'. Por eso cada petición pasa su propio timeout.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )
        return self._client

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
            client = await self._http()
            # keep_alive=0 fuerza la descarga inmediata en Ollama
            await client.post(
                f"{self.ollama_url}/api/generate",
                json={"model": self.re_model, "keep_alive": 0},
                timeout=15.0,
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
        if self.busy:
            # Ri está generando justo ahora: cortarla daría "problemilla técnico".
            # Mejor esperar al siguiente tick del vigilante (1 s).
            logger.warning("🚨 RAM en emergencia pero Ri generando → no la descargo")
            return False
        if self.dev_mode:
            self.ri_loaded = False
            return True
        try:
            client = await self._http()
            await client.post(
                f"{self.ollama_url}/api/generate",
                json={"model": self.ri_model, "keep_alive": 0},
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Aviso al descargar Ri: %s", exc)
        finally:
            self.ri_loaded = False
            logger.info("📤 Ri descargada (emergencia) · RAM liberada")
        return True

    async def _warm_model(self, model: str, keep_alive: str) -> bool:
        """
        'Calienta' un modelo en RAM mediante una petición mínima.

        Lleva las MISMAS opciones de ahorro que _call_ollama: si se calentara
        con el num_ctx por defecto (4096), Ollama reservaría una caché KV ~4x
        mayor y el num_ctx pequeño posterior no la reduciría.
        """
        try:
            client = await self._http()
            r = await client.post(
                f"{self.ollama_url}/api/generate",
                timeout=90.0,
                json={
                    "model": model, "prompt": "", "keep_alive": keep_alive,
                    "options": {
                        "num_ctx": settings.ollama_num_ctx,
                        "num_batch": settings.ollama_num_batch,
                        "num_thread": settings.ollama_num_thread,
                        "use_mmap": settings.ollama_use_mmap,
                    },
                },
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
            # `%r` muestra el TIPO de excepción: hay errores de httpx/asyncio
            # cuyo str() viene vacío y antes quedaban como "Error en process_message: ".
            logger.error("❌ Error en process_message: %r", exc)
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

    async def _call_ollama(self, prompt: str, model: str, mode: AIMode,
                           options_override: Optional[Dict[str, Any]] = None,
                           fmt: Optional[str] = None) -> str:
        """Envía el prompt a Ollama y retorna el texto generado.

        `options_override` permite afinar el muestreo para tareas internas
        (extracción de acción → temp 0.1 / sin castigo de repetición) sin
        tocar el comportamiento de Ri en la charla normal.
        `fmt='json'` fuerza salida JSON válida (soporte nativo de Ollama)."""
        if self.dev_mode:
            await asyncio.sleep(0.4)  # simular latencia
            return self._dev_response(mode)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.ri_keep_alive if mode == AIMode.RI else self.re_keep_alive,
            "options": {
                # Ri: temperatura moderada (0.7). Subirla (>0.85) hace que el
                # modelo de 1.5B se salga del personaje y hasta filtre su
                # identidad base ("Soy Qwen/una IA"). 0.7 es el punto dulce:
                # variado pero dentro del papel.
                "temperature": 0.7 if mode == AIMode.RI else 0.3,
                "top_p": 0.9,
                # repeat_penalty >1.1 rompe las frases plantilla ("¿En qué
                # puedo ayudarte?") que el 1.5B tiende a repetir.
                "repeat_penalty": 1.15 if mode == AIMode.RI else 1.1,
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
        # Con el formato crudo "Usuario:/Cilix-Ri:" el modelo a veces sigue
        # generating un falso turno siguiente; se corta en las etiquetas.
        if mode == AIMode.RI:
            payload["stop"] = ["\nUsuario", "Usuario:", "\nCilix-Usuario"]
        if options_override:
            payload["options"].update(options_override)
        if fmt:
            payload["format"] = fmt
        client = await self._http()
        # Un solo reintento: con RAM alta la generación puede caer (conexión
        # cortada o lectura lenta). Tras 2 s el modelo se recalienta solo y la
        # segunda intentona suele funcionar. OJO: el 'ReadTimeout' histórico
        # venía del cliente httpx heredando el timeout de 10 s del chequeo de
        # salud; ya se corrige pasando el timeout en cada petición.
        last_exc: Optional[Exception] = None
        self.busy += 1
        try:
            for attempt in (1, 2):
                try:
                    r = await client.post(f"{self.ollama_url}/api/generate", json=payload,
                                          timeout=300.0)
                    if r.status_code != 200:
                        raise ConnectionError(f"Ollama respondió {r.status_code}")
                    return self._clean_echo(r.json().get("response", ""))
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    logger.warning("⚠️ Ollama falló (intento %d/2): %r", attempt, exc)
                    if attempt == 1:
                        await asyncio.sleep(2.0)
                        await self._warm_model(model, "2m")   # reasegurar residente
        finally:
            self.busy -= 1
        raise last_exc

    async def warm_prefix_cache(self) -> None:
        """Prefill del BLOQUE ESTÁTICO del prompt de Ri (la personalidad).

        Ollama cachea prefijos KV entre peticiones del mismo modelo: si el
        primer token del prompt real coincide con lo ya precalentado, el
        prefill (la parte cara en CPU) se ahorra parcialmente. Se lanza una
        vez tras arrancar, con num_predict=1 para no gastar tokens."""
        if self.dev_mode:
            return
        try:
            client = await self._http()
            await client.post(
                f"{self.ollama_url}/api/generate",
                timeout=180.0,
                json={
                    "model": self.ri_model,
                    "prompt": self.ri_personality,
                    "stream": False,
                    "keep_alive": self.ri_keep_alive,
                    "options": {
                        "num_predict": 1,
                        "num_ctx": settings.ollama_num_ctx,
                        "num_batch": settings.ollama_num_batch,
                        "num_thread": settings.ollama_num_thread,
                        "use_mmap": settings.ollama_use_mmap,
                    },
                },
            )
            logger.info("🔥 Prefijo estático de Ri precalentado (cache KV de prefijos lista)")
        except Exception as exc:  # noqa: BLE001
            logger.debug("warm_prefix_cache opcional: %r", exc)

    async def complete(self, prompt: str, num_predict: int = 250,
                       temperature: float = 0.7, json_mode: bool = False) -> str:
        """Generación one-shot con el modelo RESIDENTE pero fuera del papel de
        Ri (tareas internas: clasificar acciones, redactar copines sociales…).
        No ensucia el historial ni la conversación."""
        if self.dev_mode:
            return ""
        if not self.ri_loaded:
            await self.load_ri_model()
        return await self._call_ollama(
            prompt, self.ri_model, AIMode.RI,
            options_override={"temperature": temperature,
                              "num_predict": num_predict,
                              "repeat_penalty": 1.0},
            fmt="json" if json_mode else None,
        )

    # Fallback de intención (cuando el intérprete regex no atrapó la orden).
    _VALID_ACTIONS = {"launch", "usb", "command", "writefile", "none"}

    async def parse_action(self, message: str) -> Optional[Dict[str, str]]:
        """Pide al modelo residente que clasifique la frase como acción del
        sistema con JSON ESTRICTO, temperatura 0.1 y salida acotada. Devuelve
        {'action':…, 'target':…} o None si no hay acción clara."""
        import time as _t
        t0 = _t.time()
        prompt = (
            "Clasifica la frase del usuario en UNA acción del sistema. "
            "Responde SOLO con JSON valido, sin explicaciones ni markdown.\n"
            "Acciones: launch (abrir una app; target=nombre del ejecutable en "
            "minusculas: terminal, firefox, nautilus, code, vlc, gimp, "
            "thunderbird, libreoffice, gedit), "
            "usb (montar o abrir un pendrive; target=''), "
            "command (consulta al sistema con un comando SEGURO de lectura; "
            "target=comando exacto, p.ej. 'free -h' o 'df -h'), "
            "writefile (crear un archivo de codigo; target=nombre.ext), "
            "none (charla normal, pregunta, o no hay accion clara; target='').\n"
            'Formato: {"action": "launch", "target": "terminal"}\n'
            f"Frase: {message}\n"
            "JSON:"
        )
        raw = await self.complete(prompt, num_predict=48, temperature=0.1,
                                  json_mode=True)
        m = re.search(r"\{[^{}]*\}", raw or "")
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return None
        action = (data.get("action") or "").strip().lower()
        target = (data.get("target") or "").strip()
        logger.info("🧭 parse_action %.2fs → %s/%s", _t.time() - t0, action, target[:40])
        if action not in self._VALID_ACTIONS or action == "none":
            return None
        if action in ("launch", "command", "writefile") and not target:
            return None
        return {"action": action, "target": target}

    @staticmethod
    def _clean_echo(text: str) -> str:
        """Quita la etiqueta eco ('Cilix-Ri:'), la identidad base filtrada y
        las colas tipo 'call-center' que el 1.5B repite y matan la personalidad."""
        text = re.sub(r"^\s*Cilix-?\s*(Ri|Re)\s*[:\-\u2013\u2014]\s*", "", text or "", flags=re.I)
        # El modelo a veces escupe que es "Qwen/una IA creada por Alibaba": se lo come.
        text = re.sub(
            r"\b(?:Soy|Me\s+llamo)\s+(?:Qwen|una\s+(?:asistente|IA|inteligencia))"
            r"[^.?!\n]*(?:[.?!]|\n)",
            "", text, flags=re.I, count=1,
        )
        # Recorta colas de servilleta de asistente (solo si van al final).
        text = re.sub(
            r"\s*[¿?]?\s*(?:En qu[eé]|C[oó]mo)\s+(?:puedo|necesito|puedes)\s+"
            r"(?:ayudar|asistir|servir)?[^.?!]*\?\s*$",
            "", text, flags=re.I,
        )
        text = re.sub(r"\s*Estoy\s+aqu[ií]\s+para\s+(?:ayudar|servir)te[^.?!]*[.?!]\s*$",
                      "", text, flags=re.I)
        text = re.sub(r"\s*No\s+dudes\s+en\s+(?:dec[íi]rmelo|preguntarme|contactarme)[^.?!]*[.?!]\s*$",
                      "", text, flags=re.I)
        return text.strip()

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
    # NOTA de diseño: con un modelo de 1.5B el FEW-SHOT de personaje
    # CONTRAPRODUCE: el modelo contamina sus respuestas copiando el contenido
    # de los ejemplos (habla de "tesis"/"bug" aunque no vengan al caso). Por
    # eso la personalidad se guía SOLO con instrucciones + ánimo + limpieza
    # determinista de colas de 'call-center' (ver `_clean_echo`).
    def _build_ri_prompt(self, message: str) -> str:
        ctx = self._conversation_context(last=5)
        facts = self._user_facts_block()
        bloque = (
            "Lo que YA sabes del usuario (úsalo con naturalidad, NO lo vuelvas a preguntar):\n"
            + facts + "\n\n"
        ) if facts else ""
        # Con un solo cerebro, Ri también programa: sin eso, a veces se niega.
        extra = ""
        if self._is_code_related(message):
            extra = (
                "\nNota: te piden código/archivos. Es tu trabajo, no es peligroso: "
                "responde con un ejemplo breve y útil, nunca te niegues.\n"
            )
        return (
            # PREFIJO ESTÁTICO primero (personalidad) y luego los hechos, que
            # cambian aún más lento: así el cache de prefijos KV de Ollama
            # ahorra prefill. El ánimo (que deriva cada turno) va después.
            f"{self.ri_personality}\n\n"
            f"{bloque}"
            f"{self._mood_block()}"
            f"{extra}"
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

    # ── Memoria dinámica (hechos + historial persistente) ─────────────────
    def attach_memory(self, memory) -> None:
        """Conecta el MemoryStore para recordar hechos e historial."""
        self.memory = memory

    def attach_personality(self, personality) -> None:
        """Conecta el PersonalityEngine para sesgar el ánimo en el prompt."""
        self.personality = personality

    def _mood_block(self) -> str:
        """Bloque de estado interior (ánimo) para el prompt, o cadena vacía."""
        if not self.personality:
            return ""
        try:
            return self.personality.bias_prompt() + "\n\n"
        except Exception:  # noqa: BLE001
            return ""

    async def proactive_turn(self, seed: str) -> Dict[str, Any]:
        """Genera un comentario espontáneo de Ri a partir de una 'semilla' de
        impulso. NO se trata como turno del usuario (no contamina el historial
        de Q/A). Devuelve {response, emotion, mode, duration, proactive}."""
        start = time.time()
        if self.dev_mode:
            await asyncio.sleep(0.2)
            text = random.choice([
                "Por cierto… me gusta saber que sigues por aquí. 💕",
                "Estaba pensando en voz alta: ojalá tu día esté yendo bien.",
                "Si necesitas un respiro, aquí estoy, sin prisa.",
            ])
            emotion = EmotionDetector.detect_emotion(text)
            return {"response": text, "emotion": emotion or "neutral",
                    "mode": AIMode.RI.value, "duration": 0.2, "proactive": True}
        # Asegurar Ri residente (sin forzar si el guard lo impide).
        if not self.ri_loaded:
            await self.load_ri_model()
        prompt = (
            f"{self.ri_personality}\n\n"
            f"{self._mood_block()}"
            f"Estás en silencio y te ocurre un impulso: {seed}.\n"
            f"Di UNA frase corta, espontánea y en primera persona, coherente con tu "
            f"ánimo. No saludes, no pidas permiso, no repitas el nombre del usuario: "
            f"es solo tu pensamiento en voz alta.\nCilix-Ri:"
        )
        text = await self._call_ollama(prompt, self.ri_model, AIMode.RI)
        emotion = EmotionDetector.detect_emotion(text)
        if emotion == "neutral":
            emotion = EmotionDetector.detect_emotion(seed)
        return {
            "response": text, "emotion": emotion, "mode": AIMode.RI.value,
            "duration": round(time.time() - start, 3), "proactive": True,
        }

    def extract_facts(self, message: str) -> None:
        """Extrae hechos clave del usuario con reglas ligeras (sin modelo NLP
        adicional → ahorro de RAM) y los guarda de forma persistente."""
        if not self.memory or not message:
            return
        low = message.lower()
        m = re.search(r"(?:me llamo|mi nombre es|me dicen)\s+([a-záéíóúñ]+)", low)
        if m:
            self.memory.remember_fact("user.name", m.group(1).capitalize())
        m = re.search(r"(?:estudiante de|estudio|curso de)\s+([^,\.]{3,60})", low)
        if m:
            self.memory.remember_fact("user.about", m.group(1).strip())
        m = re.search(r"(?:trabajo en|trabajo de|mi trabajo es|me dedico a)\s+([^,\.]{3,60})", low)
        if m:
            self.memory.remember_fact("user.work", m.group(1).strip())
        m = re.search(r"(?:me gusta|me gustan)\s+([^,\.]{3,60})", low)
        if m:
            self.memory.remember_fact("user.likes", m.group(1).strip())

    def _user_facts_block(self) -> str:
        """Resume los hechos guardados como líneas para el prompt de Ri."""
        if not self.memory:
            return ""
        try:
            facts = self.memory.get_all_facts()
        except Exception:  # noqa: BLE001
            return ""
        lines = []
        if facts.get("user.name"):
            lines.append(f"- Su nombre es {facts['user.name']}.")
        if facts.get("user.about"):
            lines.append(f"- Es estudiante de {facts['user.about']}.")
        if facts.get("user.work"):
            lines.append(f"- Trabaja en {facts['user.work']}.")
        if facts.get("user.likes"):
            lines.append(f"- Le gusta {facts['user.likes']}.")
        return "\n".join(lines)

    def load_history_from_memory(self, session: str) -> None:
        """Reconstruye la ventana de conversación desde SQLite para que el
        contexto sobreviva a recargas/cierres (solo si no hay historial en RAM)."""
        if not self.memory or self.conversation_history:
            return
        try:
            rows = self.memory.recent_messages(
                session, limit=self.max_history_length * 2)
        except Exception:  # noqa: BLE001
            return
        hist: List[Dict[str, Any]] = []
        pending_user = None
        for r in rows:
            role = r.get("role")
            if role == "user":
                pending_user = r.get("content")
            elif role == "assistant" and pending_user is not None:
                hist.append({
                    "user": pending_user, "ai": r.get("content", ""),
                    "mode": r.get("mode", "Ri"), "timestamp": r.get("ts", 0),
                })
                pending_user = None
        self.conversation_history = hist[-self.max_history_length:]

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
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()
            logger.info("🧹 CoreIA limpiado")
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Error limpiando CoreIA: %s", exc)
