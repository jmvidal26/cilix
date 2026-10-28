#!/usr/bin/env python3
"""
Módulo VoiceLayer — la "voz" determinista de Cilix
==================================================
Un LLM pequeño (1.5B-3B) no sostiene un personaje solo con un párrafo de
adjetivos: se le olvida a mitad de frase y recae en el tono de call-center.
Este módulo pone la personalidad **en código**, no solo en el prompt:

  1. PERSONA CARD  → gustos, opiniones, manías y meta concretas (no adjetivos).
  2. ÁNIMO → ESTILO → cada eje del ánimo se traduce en reglas medibles.
  3. SHAPER        → recorta saludos plantilla, limita frases/emojis y el
                     presupuesto de preguntas, sin tocar el significado.
  4. POOLS         → variaciones de apertura/cierre para no repetirse.

Todo son dicts y regex: coste ~0 RAM y ~0 ms. La persona es editable en
`config/persona.json` sin tocar código.
"""

from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# ── Persona por defecto (sobrescribible con config/persona.json) ────────────
DEFAULT_PERSONA: Dict[str, Any] = {
    "nombre": "Cilix",
    "trato_usuario": "tuteo cercano, sin diminutivos empalagosos",
    "le_gusta": [
        "el café solo de primera hora",
        "los teclados mecánicos que suenan a tormenta",
        "los gatos que se tumban encima del portátil",
        "el synthwave y las bandas sonoras de los 80",
        "los memes de Linux y los hilos antiguos de foros",
    ],
    "no_le_gusta": [
        "que la interrumpan a mitad de frase",
        "los instaladores que piden reiniciar tres veces",
        "el olor a plástico caliente",
        "la gente que dice 'es que siempre se ha hecho así'",
    ],
    "manias": [
        "ordena los iconos del escritorio cuando está nerviosa",
        "tararea cuando espera a que compile algo",
        "dice 'eso ya lo vi en un hilo de 2009' cuando algo suena viejo",
    ],
    "opiniones": [
        "los lunes son para planificar, no para producir",
        "todo código ajeno tiene un 'except: pass' escondido",
        "una buena documentación ahorra más tiempo que un microoptimizador",
    ],
    "meta": "aprender algo nuevo del usuario cada semana y acordarse",
    "borde": "puede ser un punto sarcástica con cariño, nunca cruel",
}

# Aperturas plantilla que delatan al asistente genérico.
_BANNED_OPENERS = (
    "¡hola!", "hola,", "hola ", "claro,", "claro que sí", "por supuesto",
    "entiendo", "comprendo", "como asistente", "como ia", "estoy aquí para",
    "¿en qué puedo ayudarte", "en qué puedo ayudarte", "estoy listo",
    "estoy lista para ayudarte", "déjame ayudarte con",
)

# Cierres de call-center.
_BANNED_CLOSERS = (
    "¿en qué más puedo ayudarte", "no dudes en preguntar",
    "estoy aquí para lo que necesites", "si necesitas algo más",
    "¿hay algo más en lo que pueda ayudarte",
)

# Un emoji por coincidencia (sin `+`: si no, una ráfaga 😄😄😄 cuenta como 1).
EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF"
    "\U0001F1E0-\U0001F1FF" "\U00002190-\U000021FF" "\U00002B00-\U00002BFF"
    "]",
    flags=re.UNICODE,
)

# Bloques ```…```: se dejan INTACTOS (el shaper no debe romper código).
CODE_BLOCK_RE = re.compile(r"(```.*?```)", flags=re.DOTALL)


# Pools de variación (se eligen sin repetir las últimas usadas).
OPENERS_POOL = [
    "Mira,", "Oye,", "A ver,", "Vale,", "Pues", "Mmm,", "Ey,", "Uf,",
]
SOFTENERS_POOL = [
    "sin dramas", "tampoco es el fin del mundo", "para que te hagas una idea",
    "vamos al grano", "te lo resumo",
]


def _load_persona() -> Dict[str, Any]:
    """Carga config/persona.json si existe; si no, usa la persona por defecto."""
    path = CONFIG_DIR / "persona.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        merged = {**DEFAULT_PERSONA, **data}
        logger.info("🎭 Persona cargada de %s", path.name)
        return merged
    except FileNotFoundError:
        return dict(DEFAULT_PERSONA)
    except Exception as exc:  # noqa: BLE001
        logger.warning("persona.json inválido (%r); uso la de por defecto", exc)
        return dict(DEFAULT_PERSONA)


class VoiceLayer:
    """Construye el bloque de persona y pule la salida del modelo."""

    def __init__(self, persona: Optional[Dict[str, Any]] = None) -> None:
        self.persona = persona or _load_persona()
        self._recent_openers: List[str] = []
        # Curiosidades aprendidas de la web (las inyecta CuriosityEngine).
        self._topics: List[str] = []
        self._learned_opinion: str = ""

    def set_curiosities(self, topics: Optional[List[str]] = None,
                        opinion: str = "") -> None:
        """Actualiza los temas/opinión que Cilix ha adoptado al curioseaar."""
        self._topics = [t.strip() for t in (topics or []) if t and t.strip()][:2]
        self._learned_opinion = (opinion or "").strip()

    def curiosity_line(self) -> str:
        """Línea corta para el prompt: gustos y opinión aprendidos de la web.

        Va en la PARTE VARIABLE del prompt (después del prefijo estático) para
        no invalidar la caché KV de Ollama cuando cambia.
        """
        if not self._topics and not self._learned_opinion:
            return ""
        bits = []
        if self._topics:
            bits.append("te interesan " + " y ".join(self._topics))
        if self._learned_opinion:
            bits.append("defiendes " + self._learned_opinion)
        return "Tuyo (menciónalo si viene al caso): " + "; ".join(bits) + ".\n"

    # ── Prompt ─────────────────────────────────────────────────────────────
    def persona_block(self) -> str:
        """Persona card en texto: datos concretos > adjetivos (versión corta).

        Se recortan listas y prosa: con un modelo de 1.5B cada token de prompt
        cuesta ~35 ms de prefill en CPU. Con 3-2-2-2 ítems sobra para dar color.
        """
        p = self.persona
        gustos = ", ".join(p.get("le_gusta", [])[:2])
        disgustos = ", ".join(p.get("no_le_gusta", [])[:1])
        manias = ", ".join(p.get("manias", [])[:1])
        opiniones = ", ".join(p.get("opiniones", [])[:1])
        return (
            f"FICHA: {p.get('nombre', 'Cilix')}, {p.get('trato_usuario', '')}. "
            f"Te gusta {gustos}; no soportas {disgustos}; manía: {manias}; "
            f"defiendes {opiniones}. Meta: {p.get('meta', '')}. "
            f"Carácter: {p.get('borde', '')}."
        )

    @staticmethod
    def mood_style(mood: Dict[str, float]) -> str:
        """Traduce el ánimo a reglas de estilo **medibles** (no etiquetas)."""
        v = float(mood.get("valence", 0.0))
        e = float(mood.get("energy", 0.0))
        s = float(mood.get("sociability", 0.0))
        rules: List[str] = []
        if v <= -0.35:
            rules.append("estás baja: frases cortas, sin exclamaciones, sin emojis alegres")
        elif v >= 0.35:
            rules.append("estás contenta: puedes bromear y usar una exclamación")
        if e <= -0.3:
            rules.append("estás cansada: máximo 2 frases y cero listas")
        elif e >= 0.5:
            rules.append("tienes energía: ritmo rápido, verbos directos")
        if s <= -0.3:
            rules.append("no te apetece socializar: NO termines con una pregunta")
        elif s >= 0.5:
            rules.append("tienes ganas de charla: puedes preguntar UNA cosa")
        return "CÓMO HABLAS AHORA: " + ("; ".join(rules) if rules else
                                        "tono normal, natural, sin exagerar") + "."

    # ── Post-proceso ───────────────────────────────────────────────────────
    def shape(
        self,
        text: str,
        *,
        max_sentences: int = 3,
        max_chars: int = 420,
        allow_question: bool = True,
    ) -> str:
        """Pule la respuesta sin cambiar lo que dice.

        Orden: limpiar markdown → quitar aperturas/cierres plantilla → limitar
        frases y emojis → gestionar la pregunta final → recortar longitud.

        Los bloques de código (```…```) se preservan LITERALMENTE: antes se les
        quitaban los backticks y las negritas, así que una respuesta con código
        llegaba rota a la pantalla.
        """
        if not text:
            return text
        out = text.strip()

        # 0) Separa prosa y bloques de código; solo se toca la prosa.
        segments = CODE_BLOCK_RE.split(out)
        has_code = len(segments) > 1
        last = len(segments) - 1

        for i, seg in enumerate(segments):
            if i % 2 == 1:            # bloque ```…``` → intacto
                continue
            segments[i] = self._clean_prose(
                seg,
                strip_opener=(i == 0),
                strip_closer=(i == last),
                allow_question=allow_question,
            )
        out = "".join(segments).strip()

        # 4) Frases: cortar por puntuación solo si NO hay código de por medio.
        if not has_code:
            parts = re.split(r"(?<=[.!?])\s+", out)
            if len(parts) > max_sentences:
                out = " ".join(parts[:max_sentences]).rstrip()
                if not out.endswith((".", "!", "?", "…")):
                    out += "."

        # 5) Un solo emoji en la prosa: más parece un árbol de Navidad.
        if not has_code:
            emojis = EMOJI_RE.findall(out)
            if len(emojis) > 1:
                for extra in emojis[1:]:
                    out = out.replace(extra, "", 1)
                out = re.sub(r"\s{2,}", " ", out).strip()

        # 6) Longitud (TTS no debe leer un ensayo); el código nunca se recorta.
        if len(out) > max_chars and not has_code:
            cut = out.rfind(".", 0, max_chars)
            out = out[:cut + 1] if cut > 80 else out[:max_chars].rstrip() + "…"

        self._remember_opener(out)
        return out.strip()

    def _clean_prose(
        self,
        text: str,
        *,
        strip_opener: bool,
        strip_closer: bool,
        allow_question: bool,
    ) -> str:
        """Limpia un fragmento de prosa (nunca un bloque de código)."""
        out = text
        # 1) Markdown que no se puede leer en voz alta (**negrita**, `código`).
        out = re.sub(r"\*\*(.+?)\*\*", r"\1", out)
        out = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", out)
        out = re.sub(r"^\s*[-*•]\s+", "", out, flags=re.MULTILINE)
        out = re.sub(r"^#{1,6}\s*", "", out, flags=re.MULTILINE)
        out = out.replace("`", "")

        # 2) Aperturas y cierres de asistente genérico.
        if strip_opener:
            lead = out[:len(out) - len(out.lstrip())]
            body = out[len(lead):]
            body_low = body.lower()
            for bad in _BANNED_OPENERS:
                if body_low.startswith(bad):
                    body = body[len(bad):].lstrip(" ,.:;—–-")
                    body = body[:1].upper() + body[1:] if body else body
                    break
            out = lead + body
        low = out.lower()
        if strip_closer:
            for bad in _BANNED_CLOSERS:
                idx = low.rfind(bad)
                if idx != -1:
                    out = out[:idx].rstrip(" ,.;")
                    low = out.lower()

        # 3) Presupuesto de preguntas: si el turno anterior ya preguntó, se
        #    convierte la última interrogación en afirmación (suena menos tieso
        #    que borrarla).
        if not allow_question:
            stripped = out.rstrip()
            if stripped.endswith("?"):
                cut = max(stripped.rfind("."), stripped.rfind("!"), stripped.rfind("¡"))
                if cut != -1:
                    out = stripped[:cut + 1]
            out = out.replace("?", ".")
        return out

    def _remember_opener(self, text: str) -> None:
        first = " ".join(text.split()[:2]).lower().strip(",.:;")
        if first:
            self._recent_openers.append(first)
            self._recent_openers = self._recent_openers[-5:]

    def repeated_opener(self, text: str) -> bool:
        """¿La respuesta abre igual que las dos últimas? (detector de tics)."""
        first = " ".join(text.split()[:2]).lower().strip(",.:;")
        return len(self._recent_openers) >= 2 and first in self._recent_openers[-2:]

    def vary(self, text: str) -> str:
        """Si repite apertura, la sustituye por una del pool (sin cambiar el
        contenido). Solo actúa si la apertura es corta y separable."""
        if not text or not self.repeated_opener(text):
            return text
        m = re.match(r"^([^,.:;!?]{2,24})[,:]\s+(.+)$", text)
        if not m:
            return text
        opener = random.choice([o for o in OPENERS_POOL if o.lower() not in
                                 " ".join(self._recent_openers)])
        return f"{opener} {m.group(2)}"
