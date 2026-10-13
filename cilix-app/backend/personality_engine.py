#!/usr/bin/env python3
"""
Motor de Personalidad de Cilix (Camino A)
=========================================
Da a Ri una personalidad con "días": un estado de ánimo persistente de 3 ejes
(valencia, energía, sociabilidad) que deriva con el tiempo y reacciona a la
interacción, más la lógica de PENSAMIENTO PROACTIVO (decidir cuándo comentar
algo por su cuenta).

Diseño deliberadamente LIGERO:
  · Sin PyTorch ni modelos extra → 0 RAM adicional.
  · Sin hilos: todo se apoya en el event loop asyncio del servidor.
  · Persistencia en el MISMO MemoryStore (SQLite) que ya guarda hechos.
No se porta el proactive_thinking.py de pr1/ (monolito con threading y motor de
reglas): aquí solo hace falta ánimo + un disparador de idle.
"""

import logging
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config import settings

logger = logging.getLogger(__name__)


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class MoodState:
    """Estado de ánimo en 3 ejes (-1..1) + marca temporal de la última update."""
    valence: float = 0.0       # ánimo general (positivo/negativo)
    energy: float = 0.2        # vitalidad (curva circadiana)
    sociability: float = 0.0   # ganas de hablar (suben con el idle)
    updated: float = 0.0

    def drift(self, now: float) -> None:
        """Hace evolucionar el ánimo hacia sus atractores según el tiempo
        transcurrido desde la última actualización (decaimiento exponencial)."""
        dt = max(0.0, now - self.updated) if self.updated else 0.0
        self.updated = now
        if dt <= 0:
            return
        # Valencia decae hacia 0 (neutral) con constante ~2 h.
        self.valence += (0.0 - self.valence) * (1 - math.exp(-dt / 7200))
        # Energía: atraída por una curva circadiana suave según la hora.
        hour = time.localtime(now).tm_hour
        target = -0.3 + 1.1 * max(0.0, math.sin((hour - 6) / 24 * 2 * math.pi))
        self.energy += (_clamp(target) - self.energy) * (1 - math.exp(-dt / 3600))
        # Sociabilidad: sube sola cuanto más tiempo sin interactuar (hasta 1).
        self.sociability += (1.0 - self.sociability) * (1 - math.exp(-dt / 5400))
        self.valence = _clamp(self.valence)
        self.energy = _clamp(self.energy)
        self.sociability = _clamp(self.sociability)

    def react(self, emotion: str, engaged: bool = True) -> None:
        """Modifica el ánimo por una interacción: la emoción detectada mueve la
        valencia y hablar con el usuario sacia la sociabilidad."""
        delta = {
            "feliz": 0.15, "sorprendido": 0.10, "concentrado": 0.05,
            "triste": -0.15, "enfadado": -0.15,
        }.get(emotion, 0.0)
        self.valence = _clamp(self.valence + delta)
        if engaged:
            self.sociability = _clamp(self.sociability - 0.5)  # saciada al charlar
            self.valence = _clamp(self.valence + 0.05)         # contenta de compañía
            self.energy = _clamp(self.energy - 0.05)           # socializar cansa

    def to_prompt_block(self) -> str:
        """Resume el estado interior en primera persona para el system prompt."""
        v = self.valence
        e = self.energy
        s = self.sociability
        animo = ("muy bien" if v > 0.5 else "de buen humor" if v > 0.15
                 else "un poco baja" if v > -0.3 else "apagada/triste" if v > -0.6
                 else "poca cosa hoy")
        energia = ("con mucha energía" if e > 0.4 else "tranquila" if e > 0.0
                   else "con flojera y poca energía")
        social = ("con muchas ganas de charlar contigo" if s > 0.6
                  else "agradando tu compañía" if s > 0.2
                  else "más bien en modo tranquilo/observador")
        return (
            f"Tu estado interior AHORA (déjalo traslucir con naturalidad, no lo "
            f"enuncies en frío): te sientes {animo}, {energia}, y estás {social}."
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valence": round(self.valence, 3),
            "energy": round(self.energy, 3),
            "sociability": round(self.sociability, 3),
            "updated": self.updated,
        }


class PersonalityEngine:
    """Gestiona el ánimo persistente y decide los impulsos proactivos de Ri."""

    def __init__(self, memory):
        self.memory = memory
        self.mood = self._load()

    # ── Persistencia del ánimo (reusa la tabla `facts` de MemoryStore) ──────
    def _load(self) -> MoodState:
        now = time.time()
        if not self.memory:
            return MoodState(0.0, 0.2, 0.0, now)
        try:
            return MoodState(
                valence=self.memory.get_float_fact("mood.valence", 0.0),
                energy=self.memory.get_float_fact("mood.energy", 0.2),
                sociability=self.memory.get_float_fact("mood.sociability", 0.0),
                updated=self.memory.get_float_fact("mood.updated", now),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo cargar el ánimo: %s", exc)
            return MoodState(0.0, 0.2, 0.0, now)

    def _save(self) -> None:
        if not self.memory:
            return
        try:
            self.memory.set_float_fact("mood.valence", self.mood.valence)
            self.memory.set_float_fact("mood.energy", self.mood.energy)
            self.memory.set_float_fact("mood.sociability", self.mood.sociability)
            self.memory.set_float_fact("mood.updated", self.mood.updated)
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo guardar el ánimo: %s", exc)

    # ── API para el cerebro ────────────────────────────────────────────────
    def bias_prompt(self) -> str:
        """Devuelve el bloque de estado interior (aplicando deriva previa)."""
        self.mood.drift(time.time())
        self._save()
        return self.mood.to_prompt_block()

    def on_interaction(self, user_text: str, ai_emotion: str) -> None:
        """Se llama tras cada intercambio con el usuario: deriva + reacciona."""
        self.mood.drift(time.time())
        self.mood.react(ai_emotion, engaged=True)
        self._save()

    # ── Disparador proactivo ───────────────────────────────────────────────
    @staticmethod
    def _in_quiet_hour(hour: int, start: int, end: int) -> bool:
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end   # ventana que cruza medianoche

    def should_speak(self, now: float, last_user_ts: float,
                     recent_utterances: List[float],
                     recent_topic: Optional[str] = None) -> Optional[str]:
        """Decide si Ri debe decir algo por su cuenta. Devuelve una 'semilla de
        impulso' (para que Ri la convierta en frase) o None si debe callar."""
        if not settings.proactive_enabled:
            return None

        # Umbrales temporales.
        idle = now - last_user_ts
        if idle < settings.proactive_idle_seconds:
            return None
        if recent_utterances and (now - recent_utterances[-1]) < settings.proactive_min_gap_seconds:
            return None
        last_hour = [t for t in recent_utterances if now - t < 3600]
        if len(last_hour) >= settings.proactive_max_per_hour:
            return None

        hour = time.localtime(now).tm_hour
        if self._in_quiet_hour(hour, settings.proactive_quiet_start, settings.proactive_quiet_end):
            return None

        # Deriva y probabilidad proporcional a la sociabilidad.
        self.mood.drift(now)
        self._save()
        p = _clamp(0.15 + self.mood.sociability * 0.5, 0.0, 0.8)
        if random.random() > p:
            return None

        return self._pick_seed(hour, recent_topic)

    def _pick_seed(self, hour: int, recent_topic: Optional[str]) -> str:
        """Elige una semilla de impulso curada según hora/ánimo/tema reciente."""
        period = ("la madrugada" if hour < 6 else "la mañana" if hour < 13
                  else "la tarde" if hour < 20 else "la noche")
        candidates = [
            f"es {period}; comenta algo breve y natural acorde a esa hora",
        ]
        if self.mood.energy < -0.2:
            candidates.append("comenta que tienes un poco de flojera o sueño")
        if self.mood.sociability > 0.5:
            candidates.append("muestra muchas ganas de saber algo del usuario")
        if self.mood.valence > 0.4:
            candidates.append("comparte algo positivo que te ronda la cabeza")
        if recent_topic:
            candidates.append(f"retoma con curiosidad el tema «{recent_topic}»")
        candidates.append("comparte una reflexión espontánea y tierna")
        return random.choice(candidates)

    def mood_emoji(self) -> str:
        """Emoji compacto para el chip de la UI."""
        v, e, s = self.mood.valence, self.mood.energy, self.mood.sociability
        if v > 0.4 and e > 0:
            return "😄"
        if v > 0.15:
            return "🙂"
        if v < -0.4:
            return "😔"
        if v < -0.15:
            return "😕"
        if e < -0.2:
            return "🥱"
        if s > 0.6:
            return "🗣️"
        return "😌"
