"""
ai_backends.py — Sylix OS Core Assistant
Capa de abstracción multi-backend de IA:
  1. Google Gemini API  (online, primario)
  2. Anthropic Claude   (online, secundario)
  3. Ollama local       (offline, fallback ligero)

La detección de conectividad es automática y se reevalúa en cada turno.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable

logger = logging.getLogger("sylix.backends")


# ═══════════════════════════════════════════════════════════════════════════════
#  TIPOS Y ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class BackendType(str, Enum):
    GEMINI    = "gemini"
    ANTHROPIC = "anthropic"
    OLLAMA    = "ollama"


@dataclass
class AgentResponse:
    """Respuesta normalizada de cualquier backend de IA."""
    text:        str
    backend:     BackendType
    tool_calls:  list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "end_turn"
    raw:         Any = None


@dataclass
class ToolCall:
    """Llamada a herramienta normalizada entre backends."""
    id:    str
    name:  str
    input: dict[str, Any]


# ═══════════════════════════════════════════════════════════════════════════════
#  DETECCIÓN DE CONECTIVIDAD
# ═══════════════════════════════════════════════════════════════════════════════

_CONNECTIVITY_CACHE: dict[str, Any] = {"online": None, "ts": 0.0}
CONNECTIVITY_TTL = 15.0   # segundos entre re-checks


async def check_internet(host: str = "8.8.8.8", port: int = 53, timeout: float = 2.5) -> bool:
    """
    Verifica conectividad a Internet intentando una conexión TCP al DNS de Google.
    Usa caché de 15 segundos para no verificar en cada mensaje.

    Returns:
        True si hay conexión a Internet, False si está offline.
    """
    now = time.monotonic()
    if _CONNECTIVITY_CACHE["online"] is not None and (now - _CONNECTIVITY_CACHE["ts"]) < CONNECTIVITY_TTL:
        return _CONNECTIVITY_CACHE["online"]

    try:
        loop = asyncio.get_event_loop()
        conn = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        result = True
    except Exception:
        result = False

    _CONNECTIVITY_CACHE["online"] = result
    _CONNECTIVITY_CACHE["ts"] = now
    logger.info(f"[Network] Conectividad: {'✓ Online' if result else '✗ Offline'}")
    return result


def invalidate_connectivity_cache() -> None:
    """Fuerza re-evaluación en el próximo check."""
    _CONNECTIVITY_CACHE["online"] = None
    _CONNECTIVITY_CACHE["ts"] = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
#  CONVERSIÓN DE ESQUEMAS: Anthropic → Gemini / Ollama
# ═══════════════════════════════════════════════════════════════════════════════

def anthropic_tools_to_gemini(anthropic_tools: list[dict]) -> list[dict]:
    """
    Convierte la lista de tools en formato Anthropic al formato
    `function_declarations` que usa el SDK de Google Generative AI.

    Anthropic:
        {"name": "...", "description": "...", "input_schema": {JSON Schema}}

    Gemini:
        {"function_declarations": [{"name": "...", "description": "...", "parameters": {JSON Schema}}]}
    """
    declarations = []
    for tool in anthropic_tools:
        schema = dict(tool["input_schema"])
        # Gemini no acepta "default" dentro de las propiedades
        props = schema.get("properties", {})
        for prop_def in props.values():
            prop_def.pop("default", None)

        declarations.append({
            "name":        tool["name"],
            "description": tool["description"],
            "parameters":  schema,
        })
    return [{"function_declarations": declarations}]


def anthropic_tools_to_openai(anthropic_tools: list[dict]) -> list[dict]:
    """
    Convierte la lista de tools al formato OpenAI.
    """
    import copy
    result = []
    for tool in anthropic_tools:
        schema = copy.deepcopy(tool["input_schema"])
        props  = schema.get("properties", {})
        # OpenAI no acepta "default" en parameters
        for prop_def in props.values():
            prop_def.pop("default", None)
        result.append({
            "type": "function",
            "function": {
                "name":        tool["name"],
                "description": tool["description"],
                "parameters":  schema,
            },
        })
    return result


def anthropic_tools_to_slim_openai(anthropic_tools: list[dict]) -> list[dict]:
    """
    Convierte la lista de tools a una versión compacta (Slim Tools) para Ollama / modo local.
    Reduce tokens de entrada recortando descripciones extensas para acelerar TTFT
    y prevenir alucinaciones en modelos ligeros.
    """
    import copy
    SLIM_DESCRIPTIONS = {
        "execute_bash": "Ejecuta comandos de terminal Bash (diagnósticos, red, procesos, paquetes). Devuelve stdout y stderr.",
        "desktop_automation": "Controla ratón, teclado y aplicaciones en Linux.",
        "file_manager": "Operaciones con archivos y carpetas (crear, listar, mover, copiar, eliminar, leer, escribir).",
        "system_monitor": "Métricas en tiempo real de CPU, memoria, disco, red, procesos y batería.",
    }

    result = []
    for tool in anthropic_tools:
        name = tool.get("name", "")
        desc = SLIM_DESCRIPTIONS.get(name, tool.get("description", "").split(".")[0] + ".")
        schema = copy.deepcopy(tool.get("input_schema", {}))
        props = schema.get("properties", {})
        for prop_def in props.values():
            prop_def.pop("default", None)
            if "description" in prop_def and len(prop_def["description"]) > 90:
                prop_def["description"] = prop_def["description"][:87] + "..."
        result.append({
            "type": "function",
            "function": {
                "name":        name,
                "description": desc,
                "parameters":  schema,
            },
        })
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND 1: GOOGLE GEMINI
# ═══════════════════════════════════════════════════════════════════════════════

class GeminiBackend:
    """
    Backend usando el SDK oficial de Google Generative AI.
    Modelo por defecto: gemini-2.0-flash  (rápido y económico)
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model_name = model
        self._client = None
        self._initialized = False

    def _init(self):
        if self._initialized:
            return
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._genai = genai
            self._initialized = True
            logger.info(f"[Gemini] Inicializado → modelo: {self.model_name}")
        except ImportError:
            raise RuntimeError(
                "google-generativeai no instalado. "
                "Ejecuta: pip install google-generativeai"
            )

    async def run_turn(
        self,
        system_prompt: str,
        history: list[dict],
        tools_anthropic: list[dict],
        dispatch_fn: Callable,
        on_state: Callable,
        client_id: str,
    ) -> tuple[str, list[dict]]:
        """
        Ejecuta un turno completo del agente con Gemini, incluyendo
        el agentic loop de tool calling.

        history: formato interno Sylix (compatible Anthropic).
        Retorna: (texto_final, history_actualizado)
        """
        loop = asyncio.get_event_loop()
        self._init()

        import google.generativeai as genai

        # Convertir herramientas
        gemini_tools = anthropic_tools_to_gemini(tools_anthropic)

        # Convertir historial interno → formato Gemini (parts)
        gemini_history = _sylix_history_to_gemini(history)

        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_prompt,
            tools=gemini_tools,
        )

        final_text = ""
        MAX_ITER = 10
        iteration = 0

        # El último mensaje del usuario es el más reciente en history
        # Ya fue añadido por run_agent_turn antes de llamar a este método.

        # Iniciar chat con historial previo (sin el último mensaje)
        chat_history_for_gemini = _sylix_history_to_gemini(history[:-1])
        last_user_text = _extract_last_user_text(history)

        chat = model.start_chat(history=chat_history_for_gemini)

        # Enviar mensaje inicial del usuario
        def _send_initial():
            return chat.send_message(last_user_text)

        await on_state(client_id, "thinking", "[Gemini] Pensando...")
        try:
            response = await loop.run_in_executor(None, _send_initial)
        except Exception as e:
            logger.error(f"[Gemini] Error en send_message inicial: {e}")
            return f"Error Gemini: {e}", history

        while iteration < MAX_ITER:
            iteration += 1
            candidate = response.candidates[0] if (response and response.candidates) else None
            if not candidate:
                break

            # Extraer texto y function calls
            texts    = []
            fn_calls = []

            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    texts.append(part.text)
                if hasattr(part, "function_call") and part.function_call:
                    fn_calls.append(part.function_call)

            if texts:
                final_text = " ".join(texts).strip()

            if not fn_calls:
                # No hay llamadas a herramientas requeridas, respuesta final lista
                break

            # ── Ejecutar tool calls ─────────────────────────────────────────────
            await on_state(client_id, "executing", f"Ejecutando {len(fn_calls)} herramienta(s)...")

            fn_responses = []
            for fn_call in fn_calls:
                tool_name  = fn_call.name
                tool_input = dict(fn_call.args)

                logger.info(f"[Gemini] Tool call: {tool_name!r} | input: {tool_input}")
                result_str = await dispatch_fn(tool_name, tool_input)

                fn_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=tool_name,
                            response={"result": result_str},
                        )
                    )
                )

                await on_state(client_id, "executing", f"✓ {tool_name} completado")

            # Enviar resultados de vuelta a Gemini para continuar el razonamiento
            def _send_tool_results():
                return chat.send_message(fn_responses)

            try:
                await on_state(client_id, "thinking", f"[Gemini] Analizando resultados (paso {iteration})...")
                response = await loop.run_in_executor(None, _send_tool_results)
            except Exception as e:
                logger.error(f"[Gemini] Error enviando resultados de función: {e}")
                break

        # Actualizar historial interno con la respuesta final
        if final_text:
            history.append({"role": "assistant", "content": final_text})

        return final_text, history


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND 2: ANTHROPIC CLAUDE (ya existente, adaptado)
# ═══════════════════════════════════════════════════════════════════════════════

class AnthropicBackend:
    """
    Backend Anthropic Claude. Usa el cliente AsyncAnthropic existente.
    """

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key   = api_key
        self.model     = model
        self._client   = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def run_turn(
        self,
        system_prompt: str,
        history: list[dict],
        tools_anthropic: list[dict],
        dispatch_fn: Callable,
        on_state: Callable,
        client_id: str,
    ) -> tuple[str, list[dict]]:
        """Agentic loop completo con Anthropic (lógica original)."""
        import anthropic

        client = self._get_client()
        final_text = ""
        MAX_ITER   = 10
        iteration  = 0

        while iteration < MAX_ITER:
            iteration += 1
            await on_state(client_id, "thinking", f"[Claude] Turno {iteration}")

            try:
                response = await client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=tools_anthropic,
                    messages=_sylix_history_for_anthropic(history),
                )
            except anthropic.AuthenticationError:
                return "Error de autenticación Anthropic: API key inválida.", history
            except anthropic.RateLimitError:
                await asyncio.sleep(2)
                continue
            except anthropic.APIError as e:
                return f"Error API Anthropic: {e}", history

            stop_reason   = response.stop_reason
            content_blocks = response.content

            texts = [b.text for b in content_blocks if b.type == "text"]
            if texts:
                final_text = " ".join(texts).strip()

            history.append({"role": "assistant", "content": content_blocks})

            if stop_reason == "tool_use":
                tool_blocks = [b for b in content_blocks if b.type == "tool_use"]
                tool_names  = [b.name for b in tool_blocks]

                await on_state(client_id, "executing", f"Ejecutando: {', '.join(tool_names)}")

                results = await asyncio.gather(*[
                    _run_tool_block_anthropic(b, dispatch_fn) for b in tool_blocks
                ])

                history.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": b.id, "content": r}
                        for b, r in zip(tool_blocks, results)
                    ],
                })
                continue

            break

        return final_text, history


async def _run_tool_block_anthropic(block: Any, dispatch_fn: Callable) -> str:
    try:
        return await dispatch_fn(block.name, block.input)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND 3: OLLAMA (LOCAL, SIN INTERNET)
# ═══════════════════════════════════════════════════════════════════════════════

OLLAMA_BASE_URL  = os.environ.get("OLLAMA_BASE_URL",  "http://localhost:11434")
OLLAMA_MODEL     = os.environ.get("OLLAMA_MODEL",     "qwen2.5:1.5b")

# Modelos locales ligeros recomendados (en orden de preferencia por tamaño):
# - qwen2.5:0.5b  (~400 MB) — ultra ligero, respuestas básicas
# - qwen2.5:1.5b  (~900 MB) — buen balance velocidad/calidad
# - gemma2:2b     (~1.6 GB) — alta calidad para tareas complejas
# - llama3.2:1b   (~1.3 GB) — opción alternativa Meta

OLLAMA_TOOL_CALLING_MODELS = {
    "qwen2.5:1.5b", "qwen2.5:3b", "qwen2.5:7b",
    "llama3.1:8b",  "llama3.2:3b",
    "mistral:7b",   "gemma3:4b",
}


class OllamaBackend:
    """
    Backend para modelos locales vía Ollama (API compatible con OpenAI).
    Soporta tool calling nativo en modelos compatibles.
    Para modelos sin tool calling nativo usa prompt engineering con JSON.
    """

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model:    str = OLLAMA_MODEL,
    ):
        self.base_url = base_url.rstrip("/")
        self.model    = model
        self._available: bool | None = None
        self._client = None
        self._client_lock = asyncio.Lock()
        self.num_threads = max(1, os.cpu_count() or 4)
        # Configuración optimizada para modelos ligeros
        self.offline_config = {
            "temperature": 0.3,
            "num_predict": 256,  # Respuestas más cortas para latencia menor
            "num_ctx": 4096,
            "num_thread": self.num_threads,
            "repeat_penalty": 1.1,
            "mirostat": 2,  # Control mejorado de calidad/coherencia
            "mirostat_tau": 5.0,
            "mirostat_eta": 0.1,
        }

    async def _get_client(self):
        """Retorna o crea cliente HTTP persistente con connection pool optimizado."""
        import httpx
        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                # Timeout optimizado para respuestas rápidas
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=httpx.Timeout(
                        connect=3.0,      # Conexión rápida
                        read=30.0,        # Lectura generosa
                        write=10.0,       # Escritura rápida
                        pool=5.0,         # Pool management
                    ),
                    limits=httpx.Limits(
                        max_keepalive_connections=8,
                        max_connections=20,
                        keepalive_expiry=60.0,  # 60 segundos de keep-alive
                    ),
                    transport=httpx.AsyncHTTPTransport(
                        retries=2,  # Reintentos automáticos
                    ),
                )
                logger.info(f"[Ollama] Cliente HTTP persistente creado para {self.base_url}")
            return self._client

    async def aclose(self):
        """Cierra el cliente HTTP persistente si está abierto."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def is_available(self) -> bool:
        """Verifica si Ollama está corriendo y el modelo está disponible."""
        try:
            client = await self._get_client()
            # Intento rápido con timeout corto
            try:
                r = await client.get("/api/tags", timeout=2.0)
            except asyncio.TimeoutError:
                # Primer intento falló, intentar con timeout más corto
                try:
                    r = await client.get("/api/tags", timeout=1.5)
                except Exception:
                    return False
            
            if r.status_code == 200:
                models_data = r.json().get("models", [])
                models = [m["name"] for m in models_data]
                
                # Verificar si hay algún modelo compatible disponible
                if models:
                    # Preferir modelos con tool calling nativo
                    preferred_models = []
                    for m in models:
                        if any(pref in m for pref in ["qwen2.5", "llama3.1", "llama3.2", "gemma3", "mistral"]):
                            preferred_models.append(m)
                    
                    # Usar modelo preferido si existe
                    if preferred_models:
                        # Priorizar el modelo configurado si está disponible
                        if self.model in preferred_models:
                            logger.info(f"[Ollama] Usando modelo configurado con tool calling: {self.model}")
                            return True
                        # Si no, usar el primer modelo con tool calling
                        self.model = preferred_models[0]
                        logger.info(f"[Ollama] Modelo con tool calling seleccionado: {self.model}")
                        return True
                    
                    # Si no hay modelos con tool calling, usar el primero disponible
                    if self.model not in models:
                        self.model = models[0]
                        logger.info(f"[Ollama] Usando primer modelo disponible: {self.model}")
                    return True
            return False
        except Exception as e:
            logger.warning(f"[Ollama] No disponible: {e}")
            return False

    def _supports_native_tools(self) -> bool:
        """¿El modelo soporta tool calling nativo en Ollama?"""
        return any(m in self.model for m in ["qwen2.5", "llama3.1", "llama3.2", "mistral", "gemma3"])

    async def run_turn(
        self,
        system_prompt: str,
        history: list[dict],
        tools_anthropic: list[dict],
        dispatch_fn: Callable,
        on_state: Callable,
        client_id: str,
    ) -> tuple[str, list[dict]]:
        """
        Agentic loop con Ollama.
        Usa tool calling nativo si el modelo lo soporta,
        de lo contrario usa JSON prompt engineering.
        """
        if self._supports_native_tools():
            return await self._run_native_tools(
                system_prompt, history, tools_anthropic, dispatch_fn, on_state, client_id
            )
        else:
            return await self._run_json_prompt(
                system_prompt, history, tools_anthropic, dispatch_fn, on_state, client_id
            )

    async def _run_native_tools(
        self,
        system_prompt: str,
        history: list[dict],
        tools_anthropic: list[dict],
        dispatch_fn: Callable,
        on_state: Callable,
        client_id: str,
    ) -> tuple[str, list[dict]]:
        """Tool calling nativo vía API compatible con OpenAI."""
        import httpx

        openai_tools = anthropic_tools_to_slim_openai(tools_anthropic)
        final_text   = ""
        MAX_ITER     = 8
        iteration    = 0

        # Construir mensajes para OpenAI format
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(_sylix_history_to_openai(history))

        client = self._get_client()

        while iteration < MAX_ITER:
            iteration += 1
            await on_state(client_id, "thinking", f"[Ollama/{self.model}] Turno {iteration}")

            # Payload optimizado con configuración para latencia reducida
            payload = {
                "model":    self.model,
                "messages": messages,
                "tools":    openai_tools,
                "stream":   False,
                "keep_alive": "15m",  # Mantener modelo caliente en memoria
                "options":  self.offline_config,
            }

            try:
                r = await client.post("/v1/chat/completions", json=payload)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.error(f"[Ollama] Error en request: {e}")
                return f"Error Ollama: {e}", history

            choice      = data["choices"][0]
            message     = choice["message"]
            stop_reason = choice.get("finish_reason", "stop")
            content     = message.get("content") or ""

            if content:
                final_text = content.strip()

            messages.append(message)  # Agregar respuesta al contexto

            if stop_reason == "tool_calls":
                tool_calls = message.get("tool_calls", [])
                if not tool_calls:
                    break

                names = [tc["function"]["name"] for tc in tool_calls]
                await on_state(client_id, "executing", f"Ejecutando: {', '.join(names)}")

                tool_messages = []
                for tc in tool_calls:
                    fn   = tc["function"]
                    name = fn["name"]
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}

                    result_str = await dispatch_fn(name, args)

                    tool_messages.append({
                        "role":         "tool",
                        "tool_call_id": tc.get("id", name),
                        "name":         name,
                        "content":      result_str,
                    })

                messages.extend(tool_messages)
                continue

            break

        # Actualizar historial
        if final_text:
            history.append({"role": "assistant", "content": final_text})

        return final_text, history

    async def _run_json_prompt(
        self,
        system_prompt: str,
        history: list[dict],
        tools_anthropic: list[dict],
        dispatch_fn: Callable,
        on_state: Callable,
        client_id: str,
    ) -> tuple[str, list[dict]]:
        """
        Fallback: prompt engineering para modelos sin tool calling nativo.
        Instruye al modelo a responder con JSON estructurado cuando quiere
        usar una herramienta.
        """
        import httpx

        # Construir descripción de herramientas en texto
        tools_desc = _tools_to_text_description(tools_anthropic)

        enhanced_system = f"""{system_prompt}

[MODO LOCAL - SIN INTERNET]
Estás operando en modo offline con capacidades reducidas.
Cuando necesites usar una herramienta, responde EXACTAMENTE con este JSON (sin markdown):
{{"tool": "nombre_herramienta", "input": {{...parámetros...}}}}

Herramientas disponibles:
{tools_desc}

Si no necesitas herramienta, responde normalmente en texto."""

        messages = [{"role": "system", "content": enhanced_system}]
        messages.extend(_sylix_history_to_openai(history))

        final_text = ""
        MAX_ITER   = 5
        iteration  = 0

        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(90.0),
        ) as client:

            while iteration < MAX_ITER:
                iteration += 1
                await on_state(client_id, "thinking", f"[Ollama/{self.model}] Offline turno {iteration}")

                payload = {
                    "model":    self.model,
                    "messages": messages,
                    "stream":   False,
                    "keep_alive": "10m",
                    "options":  {"temperature": 0.2, "num_predict": 200, "num_ctx": 2048},
                }

                try:
                    r = await client.post("/v1/chat/completions", json=payload)
                    r.raise_for_status()
                    data    = r.json()
                    content = data["choices"][0]["message"].get("content", "").strip()
                except Exception as e:
                    return f"Error Ollama: {e}", history

                messages.append({"role": "assistant", "content": content})

                # ¿La respuesta es una llamada a herramienta?
                tool_call = _try_parse_json_tool_call(content)
                if tool_call:
                    tool_name  = tool_call.get("tool", "")
                    tool_input = tool_call.get("input", {})

                    await on_state(client_id, "executing", f"Ejecutando: {tool_name}")
                    result_str = await dispatch_fn(tool_name, tool_input)

                    messages.append({
                        "role":    "user",
                        "content": f"Resultado de {tool_name}:\n{result_str}\n\nAhora da una respuesta corta en texto.",
                    })
                    continue

                final_text = content
                break

        if final_text:
            history.append({"role": "assistant", "content": final_text})

        return final_text, history


# ═══════════════════════════════════════════════════════════════════════════════
#  ROUTER / SELECCIÓN AUTOMÁTICA DE BACKEND
# ═══════════════════════════════════════════════════════════════════════════════

class AIRouter:
    """
    Selecciona automáticamente el mejor backend disponible:

    Prioridad (online):
      1. Gemini API     (si GEMINI_API_KEY está configurada)
      2. Anthropic API  (si ANTHROPIC_API_KEY está configurada)

    Prioridad (offline):
      3. Ollama local   (si el servidor está corriendo)
      4. Respuesta de emergencia (sin IA)
    """

    def __init__(
        self,
        gemini_api_key:    str = "",
        anthropic_api_key: str = "",
        gemini_model:      str = "gemini-2.0-flash",
        anthropic_model:   str = "claude-3-5-sonnet-20241022",
        ollama_base_url:   str = OLLAMA_BASE_URL,
        ollama_model:      str = OLLAMA_MODEL,
    ):
        self.gemini_backend    = GeminiBackend(gemini_api_key, gemini_model)    if gemini_api_key    else None
        self.anthropic_backend = AnthropicBackend(anthropic_api_key, anthropic_model) if anthropic_api_key else None
        self.ollama_backend    = OllamaBackend(ollama_base_url, ollama_model)

        self._last_backend: BackendType | None = None

    async def select_backend(self) -> tuple[Any, BackendType]:
        """
        Retorna el backend más adecuado según conectividad y disponibilidad.
        """
        online = await check_internet()

        if online:
            # ── Preferencia 1: Gemini ──────────────────────────────────────────
            if self.gemini_backend and self.gemini_backend.api_key:
                logger.info("[Router] Seleccionado: Gemini (online, primario)")
                return self.gemini_backend, BackendType.GEMINI

            # ── Preferencia 2: Anthropic ───────────────────────────────────────
            if self.anthropic_backend and self.anthropic_backend.api_key:
                logger.info("[Router] Seleccionado: Anthropic Claude (online, secundario)")
                return self.anthropic_backend, BackendType.ANTHROPIC

            logger.warning("[Router] Online pero sin API keys configuradas. Intentando Ollama.")

        # ── Preferencia 3: Ollama local ────────────────────────────────────────
        if await self.ollama_backend.is_available():
            logger.info(f"[Router] Seleccionado: Ollama local ({self.ollama_backend.model}) — OFFLINE")
            return self.ollama_backend, BackendType.OLLAMA

        # ── Sin backend disponible ─────────────────────────────────────────────
        logger.error("[Router] ¡Sin backend de IA disponible!")
        return None, BackendType.OLLAMA

    async def run_turn(
        self,
        system_prompt:   str,
        history:         list[dict],
        tools_anthropic: list[dict],
        dispatch_fn:     Callable,
        on_state:        Callable,
        client_id:       str,
    ) -> tuple[str, list[dict], BackendType]:
        """
        Ejecuta un turno completo con selección automática de backend.
        Incluye fallback automático si el backend primario falla.

        Returns:
            (texto_final, history_actualizado, backend_usado)
        """
        backend, backend_type = await self.select_backend()

        if backend is None:
            msg = (
                "Sin conexión a Internet y Ollama no está disponible. "
                "Instala Ollama con: curl -fsSL https://ollama.com/install.sh | sh && ollama pull qwen2.5:1.5b"
            )
            history.append({"role": "assistant", "content": msg})
            return msg, history, BackendType.OLLAMA

        self._last_backend = backend_type

        try:
            text, updated_history = await backend.run_turn(
                system_prompt=system_prompt,
                history=history,
                tools_anthropic=tools_anthropic,
                dispatch_fn=dispatch_fn,
                on_state=on_state,
                client_id=client_id,
            )
            return text, updated_history, backend_type

        except Exception as e:
            logger.exception(f"[Router] Error en backend {backend_type}: {e}")

            # ── Fallback automático a Ollama ───────────────────────────────────
            if backend_type != BackendType.OLLAMA:
                logger.warning("[Router] Fallback automático → Ollama local")
                if await self.ollama_backend.is_available():
                    try:
                        text, updated_history = await self.ollama_backend.run_turn(
                            system_prompt=system_prompt,
                            history=history,
                            tools_anthropic=tools_anthropic,
                            dispatch_fn=dispatch_fn,
                            on_state=on_state,
                            client_id=client_id,
                        )
                        return text, updated_history, BackendType.OLLAMA
                    except Exception as e2:
                        logger.error(f"[Router] Ollama fallback también falló: {e2}")

            err_msg = f"Error en todos los backends disponibles: {e}"
            history.append({"role": "assistant", "content": err_msg})
            return err_msg, history, backend_type


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS DE CONVERSIÓN DE HISTORIAL
# ═══════════════════════════════════════════════════════════════════════════════

def _sylix_history_to_gemini(history: list[dict]) -> list[dict]:
    """
    Convierte el historial interno Sylix al formato Gemini.
    Sylix almacena: {"role": "user"|"assistant", "content": str | list}
    Gemini espera:  {"role": "user"|"model", "parts": [{"text": "..."}]}
    """
    gemini_history = []
    for msg in history:
        role    = msg["role"]
        content = msg["content"]

        if role == "assistant":
            gemini_role = "model"
        else:
            gemini_role = "user"

        # Extraer texto del content (puede ser str o lista de bloques Anthropic)
        text = _extract_text_from_content(content)
        if text:
            gemini_history.append({
                "role":  gemini_role,
                "parts": [{"text": text}],
            })

    return gemini_history


def _sylix_history_to_openai(history: list[dict]) -> list[dict]:
    """
    Convierte el historial interno al formato OpenAI/Ollama.
    Filtra bloques de tool_result del historial para evitar errores.
    """
    messages = []
    for msg in history:
        role    = msg["role"]
        content = msg["content"]

        if isinstance(content, list):
            # Filtrar: extraer solo texto de bloques Anthropic
            text = _extract_text_from_content(content)
            if text:
                messages.append({"role": role, "content": text})
        elif isinstance(content, str):
            messages.append({"role": role, "content": content})

    return messages


def _sylix_history_for_anthropic(history: list[dict]) -> list[dict]:
    """
    Retorna el historial tal cual para Anthropic (es el formato nativo).
    Elimina el último mensaje si es de tool_result sin herramienta previa.
    """
    return [
        msg for msg in history
        if not (
            msg["role"] == "user"
            and isinstance(msg.get("content"), list)
            and all(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in msg["content"]
            )
            and len(history) > 0
            and history[-1]["role"] != "assistant"
        )
    ]


def _extract_text_from_content(content: Any) -> str:
    """Extrae texto plano de cualquier formato de content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            elif hasattr(block, "type") and block.type == "text":
                parts.append(block.text or "")
        return " ".join(p for p in parts if p).strip()
    return str(content) if content else ""


def _extract_last_user_text(history: list[dict]) -> str:
    """Extrae el texto del último mensaje del usuario."""
    for msg in reversed(history):
        if msg["role"] == "user":
            return _extract_text_from_content(msg["content"])
    return ""


def _tools_to_text_description(tools: list[dict]) -> str:
    """Convierte herramientas a descripción de texto para prompt engineering."""
    lines = []
    for tool in tools:
        name   = tool["name"]
        desc   = tool["description"]
        schema = tool.get("input_schema", {})
        props  = schema.get("properties", {})
        req    = schema.get("required", [])

        params = []
        for pname, pdef in props.items():
            marker = "*" if pname in req else "?"
            ptype  = pdef.get("type", "any")
            pdesc  = pdef.get("description", "")[:60]
            params.append(f"  {marker}{pname} ({ptype}): {pdesc}")

        lines.append(f"• {name}: {desc[:100]}")
        lines.extend(params)

    return "\n".join(lines)


def _try_parse_json_tool_call(text: str) -> dict | None:
    """
    Intenta parsear una respuesta de modelo como JSON de tool call.
    Busca un objeto JSON con clave 'tool' y 'input', o bloques de código bash/comandos.
    """
    import re
    raw_text = text.strip()
    clean_text = raw_text

    # Eliminar markdown code fences si existen
    if clean_text.startswith("```"):
        lines = clean_text.split("\n")
        clean_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(clean_text)
        if isinstance(data, dict):
            if "tool" in data:
                return data
            if "name" in data and ("input" in data or "parameters" in data or "arguments" in data):
                return {"tool": data["name"], "input": data.get("input") or data.get("parameters") or data.get("arguments", {})}
    except json.JSONDecodeError:
        pass

    # Buscar JSON inline en cualquier parte del texto
    match = re.search(r'\{[^{}]*"(?:tool|name)"\s*:\s*"[^"]+"\s*,[^{}]*\}', raw_text, re.DOTALL)
    if match:
        try:
            cand = json.loads(match.group())
            if "tool" in cand:
                return cand
            if "name" in cand:
                return {"tool": cand["name"], "input": cand.get("input", {})}
        except json.JSONDecodeError:
            pass

    # Fallback 1: Si el modelo respondió con un bloque de código bash/sh (```bash ... ```)
    code_match = re.search(r'```(?:bash|sh)?\s*\n(.*?)\n```', raw_text, re.DOTALL)
    if code_match:
        cmd = code_match.group(1).strip()
        if cmd:
            return {"tool": "execute_bash", "input": {"command": cmd}}

    # Fallback 2: Si el modelo sugiere comandos directos en el texto (ej. "mkdir -p ...")
    cmd_match = re.search(r'^\s*(mkdir|sudo|ls|touch|chmod|chown|rm|systemctl|apt|pip)\s+[^\n]+', raw_text, re.MULTILINE)
    if cmd_match:
        cmd = cmd_match.group(0).strip()
        return {"tool": "execute_bash", "input": {"command": cmd}}

    return None
