#!/usr/bin/env python3
"""
Compañía en silencio — Cilix habla sola cuando el usuario lleva mucho rato callado
====================================================================================
Módulo independiente del pensamiento proactivo clásico. Introduce **niveles**
según cuánto tiempo lleva el usuario sin escribir/hablar:

    · 5 min  → "checkin": un saludo breve y cálido, sin interrogar.
    · 15 min → "curiosity": comparte un dato que aprendió y qué le hace sentir.
    · 40 min → "company": propone tema, plan o pregunta ligera.
    · Después → se calla (no insiste).

Reglas de convivencia:
  · horas de silencio configurables (por defecto 23:00–08:00)
  · máximo N intervenciones por hora (por defecto 3)
  · separación mínima entre intervenciones (por defecto 15 min)
  · se pausa con «cállate un rato» y vuelve con «ya puedes hablar»
  · nunca habla si la RAM está crítica (lo comprueba main.py)

No usa LLM para decidir: solo aritmética y azar ponderado. El texto lo genera
el cerebro normal (proactive_turn), así mantiene el personaje y el ánimo.
"""

from __future__ import annotations

import random
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config import settings


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


_PAUSE_RE = re.compile(
    r"\b(?:callate(?: un rato| ya)?|modo silencio|no hables(?: por un rato)?|"
    r"deja de hablar(?: un rato)?|silencio total)\b", re.I)
_RESUME_RE = re.compile(
    r"\b(?:ya puedes hablar|vuelve a hablar|puedes hablar(?: otra vez)?|"
    r"rompe el silencio|desactiva el modo silencio)\b", re.I)


@dataclass
class Moment:
    """Una intervención decidida: nivel, semilla para el cerebro y espera."""
    tier: str
    seed: str
    idle: float


class SilenceCompanion:
    """Decide cuándo y de qué puede hablar Cilix en el silencio."""

    TIERS = (
        (2400, "company", 0.55),     # ≥ 40 min
        (900, "curiosity", 0.50),    # ≥ 15 min
        (0, "checkin", 0.30),        # ≥ idle mínimo (5 min)
    )

    def __init__(self, curiosity=None) -> None:
        self.enabled = bool(settings.companion_enabled)
        self.idle = max(60, int(settings.companion_idle))
        self.repeat = max(300, int(settings.companion_repeat))
        self.max_per_hour = max(1, int(settings.companion_max_per_hour))
        self.quiet_start = int(settings.companion_quiet_start)
        self.quiet_end = int(settings.companion_quiet_end)
        self.voice = bool(settings.companion_voice)
        self.curiosity = curiosity
        self._spoke: List[float] = []
        self._paused_until = 0.0
        self._last_tier = ""

    # ── control manual ───────────────────────────────────────────────────
    def pause(self, minutes: int = 30) -> float:
        self._paused_until = time.time() + max(1, minutes) * 60
        return self._paused_until

    def resume(self) -> None:
        self._paused_until = 0.0

    @property
    def paused(self) -> bool:
        return time.time() < self._paused_until

    def status(self) -> Dict[str, Any]:
        now = time.time()
        return {
            "enabled": self.enabled,
            "paused": self.paused,
            "paused_minutes_left": round(max(0.0, self._paused_until - now) / 60, 1),
            "idle_seconds": self.idle,
            "repeat_seconds": self.repeat,
            "max_per_hour": self.max_per_hour,
            "quiet_hours": f"{self.quiet_start:02d}:00–{self.quiet_end:02d}:00",
            "spoken_last_hour": len([t for t in self._spoke if now - t < 3600]),
            "voice": self.voice,
        }

    @staticmethod
    def interpret(text: str) -> Optional[str]:
        """Devuelve 'pause' | 'resume' si el usuario lo pide explícitamente."""
        low = _norm(text or "")   # sin tildes: "cállate" → "callate"
        if _RESUME_RE.search(low):
            return "resume"
        if _PAUSE_RE.search(low):
            return "pause"
        return None

    # ── decisión ─────────────────────────────────────────────────────────
    @staticmethod
    def _in_quiet_hour(hour: int, start: int, end: int) -> bool:
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def mark_spoke(self, when: Optional[float] = None) -> None:
        self._spoke.append(when or time.time())

    def due(self, now: float, last_user_ts: float) -> Optional[Moment]:
        """Devuelve un Moment si toca hablar, o None para seguir callada."""
        if not self.enabled or self.paused:
            return None
        idle = now - last_user_ts
        if idle < self.idle:
            return None
        hour = time.localtime(now).tm_hour
        if self._in_quiet_hour(hour, self.quiet_start, self.quiet_end):
            return None

        self._spoke = [t for t in self._spoke if now - t < 3600]
        if self._spoke and (now - self._spoke[-1]) < self.repeat:
            return None
        if len(self._spoke) >= self.max_per_hour:
            return None

        # Nivel según el tiempo de silencio. No repetir el mismo dos veces.
        tier, probability = self.TIERS[-1][1], self.TIERS[-1][2]
        for minimum, name, prob in self.TIERS:
            if idle >= minimum:
                tier, probability = name, prob
                break
        if tier == self._last_tier:
            probability *= 0.5
        if random.random() > probability:
            return None

        return Moment(tier=tier, seed=self._seed(tier), idle=idle)

    # ── semillas (el cerebro las convierte en una frase con su voz) ─────
    def _seed(self, tier: str) -> str:
        self._last_tier = tier
        if tier == "curiosity":
            fact = ""
            if self.curiosity:
                items = self.curiosity.discoveries(4)
                if items:
                    rec = random.choice(items)
                    fact = f" «{rec.get('fact', '')}»"
                    return (
                        "comparte este dato que aprendiste hace poco y di qué te "
                        f"hace sentir, sin sonar a enciclopedia: {fact}"
                    )
            return ("comparte algo curioso que te ronde la cabeza, como si lo "
                    "pensaras en voz alta")

        if tier == "company":
            return random.choice([
                "pregúntale algo personal y ligero sobre cómo va su día",
                "propón un plan pequeño y concreto para hoy o esta noche",
                "cuenta una ocurrencia tuya y deja espacio para que responda",
                "dile que te apetece charlar un rato y pregunta qué le ronda",
            ])

        return random.choice([
            "nota que lleva un rato callado y di algo breve y cálido",
            "comenta en voz baja que sigues por aquí, sin exigir respuesta",
            "haz una observación tranquila sobre el momento del día",
        ])

