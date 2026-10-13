"""Clasificador léxico-semántico de emociones para español (estilo VADER mini).

Sin dependencias ni modelo NLP: solo dos dicts en memoria (<5 MB) y aritmética
de pesos en milisegundos. Devuelve la emoción que debe mostrar el avatar
Live2D sobre el TEXTO ya generado por Ri (o por el usuario).

Diseño:
  · LEXICON: palabra/emoji → (valencia -1..1, activación 0..1, categoría).
    La categoría apunta a las 5 emociones del avatar; si una palabra vale
    (+) pero no indica categoría, se infiere por valencia+activación.
  · Modificadores tipo VADER: intensificadores (muy, súper, RE, jaja…),
    negaciones (no, nunca…) que invierten ~0.74, exclamaciones y MAYÚSCULAS
    que suben activación, y repetición de emojis.
  · Umbral: si el mejor marcador no supera NEUTRAL_MIN → None (el llamador
    decide; 'neutral' es una salida válida y deseable).
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

# ── Léxico básico ────────────────────────────────────────────────────────────
# (valencia, activación, categoría o None → se deriva de valencia/activación)
LEXICON: Dict[str, Tuple[float, float, Optional[str]]] = {
    # felicidad / celebración
    "feliz": (1.0, 0.6, "feliz"), "alegr": (1.0, 0.6, "feliz"),
    "content": (0.8, 0.4, "feliz"), "genial": (1.0, 0.7, "feliz"),
    "excelente": (1.0, 0.6, "feliz"), "maravillo": (1.1, 0.6, "feliz"),
    "increible": (1.0, 0.8, "feliz"), "increíble": (1.0, 0.8, "feliz"),
    "espectacular": (1.0, 0.7, "feliz"), "perfecto": (0.9, 0.5, "feliz"),
    "gracias": (0.6, 0.2, "feliz"), "encantad": (0.9, 0.5, "feliz"),
    "me encanta": (1.0, 0.6, "feliz"), "jaja": (0.8, 0.6, "feliz"),
    "jeje": (0.6, 0.3, "feliz"), "yay": (1.2, 0.8, "feliz"),
    "guay": (0.8, 0.5, "feliz"), "birria": (0.9, 0.5, "feliz"),
    "lo logramos": (1.1, 0.7, "feliz"), "bien hecho": (1.0, 0.5, "feliz"),
    "felicidades": (1.1, 0.6, "feliz"), "celebr": (1.0, 0.7, "feliz"),
    "😄": (1.2, 0.6, "feliz"), "😊": (1.0, 0.4, "feliz"), "🎉": (1.3, 0.8, "feliz"),
    "✨": (0.7, 0.4, "feliz"), "❤": (0.9, 0.4, "feliz"), "😍": (1.2, 0.6, "feliz"),
    # tristeza / consuelo
    "triste": (-1.2, 0.3, "triste"), "pena": (-0.9, 0.3, "triste"),
    "lástima": (-0.8, 0.3, "triste"), "lastima": (-0.8, 0.3, "triste"),
    "deprimid": (-1.3, 0.3, "triste"), "solo": (-0.6, 0.2, "triste"),
    "sola": (-0.6, 0.2, "triste"), "extrañ": (-0.8, 0.3, "triste"),
    "llor": (-1.1, 0.4, "triste"), "dolor": (-1.0, 0.4, "triste"),
    "cansad": (-0.7, 0.2, "triste"), "agotad": (-0.9, 0.2, "triste"),
    "frustrad": (-0.9, 0.5, "triste"), "decaid": (-0.8, 0.2, "triste"),
    "mal": (-0.9, 0.3, "triste"), "pésimo": (-1.2, 0.4, "triste"),
    "pesimo": (-1.2, 0.4, "triste"), "horrible": (-1.1, 0.5, "triste"),
    "terrible": (-1.0, 0.5, "triste"), "problema": (-0.6, 0.3, "triste"),
    "error": (-0.6, 0.3, "triste"), "falló": (-0.8, 0.4, "triste"),
    "fallo": (-0.7, 0.3, "triste"), "no funciona": (-0.8, 0.4, "triste"),
    "roto": (-0.6, 0.3, "triste"), "perd": (-0.7, 0.3, "triste"),
    "😔": (-1.1, 0.3, "triste"), "😢": (-1.2, 0.4, "triste"), "💔": (-1.3, 0.4, "triste"),
    "😞": (-1.0, 0.3, "triste"),
    # enfado
    "enojad": (-1.0, 0.8, "enfadado"), "enfad": (-1.0, 0.8, "enfadado"),
    "molesto": (-0.9, 0.6, "enfadado"), "rabia": (-1.1, 0.8, "enfadado"),
    "ira": (-1.0, 0.8, "enfadado"), "odio": (-1.2, 0.7, "enfadado"),
    "injusto": (-0.9, 0.6, "enfadado"), "absurdo": (-0.8, 0.6, "enfadado"),
    "imposible": (-0.7, 0.5, "enfadado"), "estupidez": (-1.1, 0.7, "enfadado"),
    "basura": (-1.0, 0.6, "enfadado"), "horripilante": (-1.0, 0.7, "enfadado"),
    "😠": (-1.3, 0.8, "enfadado"), "😡": (-1.4, 0.9, "enfadado"),
    # sorpresa
    "wow": (0.3, 1.0, "sorprendido"), "guau": (0.3, 1.0, "sorprendido"),
    "vaya": (0.2, 0.7, "sorprendido"), "en serio": (0.2, 0.8, "sorprendido"),
    "asombro": (0.4, 0.9, "sorprendido"), "impresionante": (0.8, 0.8, "sorprendido"),
    "sorprend": (0.4, 0.9, "sorprendido"), "shock": (0.2, 1.0, "sorprendido"),
    "no me digas": (0.1, 0.7, "sorprendido"),
    "omg": (0.4, 1.0, "sorprendido"), "😮": (0.2, 0.9, "sorprendido"),
    "😲": (0.2, 1.0, "sorprendido"), "🤯": (0.3, 1.0, "sorprendido"),
    # concentración / tarea técnica
    "código": (0.0, 0.4, "concentrado"), "codigo": (0.0, 0.4, "concentrado"),
    "python": (0.0, 0.3, "concentrado"), "javascript": (0.0, 0.3, "concentrado"),
    "bug": (-0.3, 0.4, "concentrado"), "debug": (-0.2, 0.4, "concentrado"),
    "error de": (-0.3, 0.4, "concentrado"), "compilar": (0.0, 0.4, "concentrado"),
    "refactor": (0.0, 0.4, "concentrado"), "función": (0.0, 0.3, "concentrado"),
    "script": (0.0, 0.3, "concentrado"), "reviso": (0.0, 0.4, "concentrado"),
    "déjame ver": (0.0, 0.4, "concentrado"), "analizo": (0.0, 0.4, "concentrado"),
    "🤔": (0.0, 0.5, "concentrado"),
    # cariño (→ feliz con rubor)
    "quiero": (0.7, 0.3, "feliz"), "te quiero": (1.0, 0.4, "feliz"),
    "amor": (0.9, 0.4, "feliz"), "guapo": (0.7, 0.3, "feliz"),
    "lindo": (0.7, 0.3, "feliz"), "adoro": (1.0, 0.5, "feliz"),
}

# ── Modificadores (VADER-español) ───────────────────────────────────────────
INTENSIFIERS: Dict[str, float] = {
    "muy": 0.4, "muchísimo": 0.6, "muchisimo": 0.6, "súper": 0.5, "super": 0.5,
    "re": 0.4, "ultra": 0.5, "mega": 0.4, "totalmente": 0.4, "completamente": 0.4,
    "absolutamente": 0.4, "increíblemente": 0.5, "tremendamente": 0.5, "jaja": 0.3,
}
NEGATORS = {"no", "nunca", "nada", "jamón", "jamon", "tampoco", "ni", "sin", "ningún", "ningun", "ninguno"}
NEG_SCALE = -0.74  # invierte y amortigua la valencia

# Fallback cuando una palabra puntúa valencia pero no tiene categoría clara
def _derive(v: float, a: float) -> Optional[str]:
    if a >= 0.8 and -0.4 <= v <= 0.6:
        return "sorprendido"
    if v > 0.5:
        return "feliz"
    if v < -0.5 and a >= 0.6:
        return "enfadado"
    if v < -0.5:
        return "triste"
    return None

_TOKEN_RE = re.compile(r"[a-záéíóúüñ]+")
NEUTRAL_MIN = 0.55   # mejor marcador por debajo → None (el llamador decide)
# Categorías puntuadas por ACTIVACIÓN (no valencia): 'vaya' o '🤔' apenas
# valen +/- pero sí indican cara; con valencia quedarían bajo el umbral.
_ACTIVATION_CATS = {"sorprendido", "concentrado"}


def classify_emotion(text: str) -> Optional[str]:
    """Devuelve 'feliz|triste|enfadado|sorprendido|concentrado' o None.

    None significa 'sin señal clara' — no forzar una cara si el texto es
    informativo/neutro (evita los errores del detector de keywords puro).
    """
    if not text:
        return None
    low = text.lower()
    scores: Dict[str, float] = {}
    tokens = _TOKEN_RE.findall(low)
    # emoji (multi-char) se buscan como substrings aparte
    for emo_key in (k for k in LEXICON if not k[0].isalpha()):
        if emo_key in low:
            v, a, cat = LEXICON[emo_key]
            if cat:
                contrib = a if cat in _ACTIVATION_CATS else v
                scores[cat] = scores.get(cat, 0.0) + contrib

    for i, tok in enumerate(tokens):
        entry = LEXICON.get(tok)
        # frases del léxico (2-3 palabras) → ventana simple hacia delante
        if entry is None and i + 1 < len(tokens):
            entry = LEXICON.get(tok + " " + tokens[i + 1])
        if entry is None and i + 2 < len(tokens):
            entry = LEXICON.get(tok + " " + tokens[i + 1] + " " + tokens[i + 2])
        if entry is None:
            # prefijos morfológicos: "alegr" cubre alegre/alegría/alegres
            for key, val in LEXICON.items():
                if key[0].isalpha() and len(key) >= 4 and tok.startswith(key):
                    entry = val
                    break
        if entry is None:
            continue
        v, a, cat = entry
        # modificadores en ventana de 2 tokens previos
        window = tokens[max(0, i - 2):i]
        for w in window:
            if w in NEGATORS:
                v *= NEG_SCALE
                break
            if w in INTENSIFIERS:
                v *= (1.0 + INTENSIFIERS[w])
        if "!" in low or (tok.isupper() and len(tok) > 2):
            a += 0.2
        target = cat or _derive(v, a)
        if target:
            contrib = a if target in _ACTIVATION_CATS else v
            scores[target] = scores.get(target, 0.0) + contrib

    if not scores:
        return None
    best = max(scores, key=scores.get)
    return best if abs(scores[best]) >= NEUTRAL_MIN else None
