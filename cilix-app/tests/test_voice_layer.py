#!/usr/bin/env python3
"""Tests de la capa de voz determinista y del detector de emociones."""

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from core_ia import EmotionDetector  # noqa: E402
from voice_layer import VoiceLayer  # noqa: E402


class VoiceShapeTests(unittest.TestCase):
    def setUp(self):
        self.voice = VoiceLayer()

    def test_los_bloques_de_codigo_se_preservan(self):
        code = "print('**hola**')\n"
        text = f"Mira, esto te sirve:\n```python\n{code}```"
        out = self.voice.shape(text)
        self.assertIn("```python", out)
        self.assertIn(code, out)
        # Las negritas dentro del código no se tocan.
        self.assertIn("**hola**", out)

    def test_quita_apertura_de_asistente(self):
        out = self.voice.shape("¡Hola! Te cuento: el bug estaba en el import.")
        self.assertFalse(out.lower().startswith("¡hola!"))

    def test_limita_a_un_emoji(self):
        out = self.voice.shape("Qué bien 😄😄😄")
        self.assertEqual(len([c for c in out if c in "😄"]), 1)

    def test_presupuesto_de_preguntas(self):
        out = self.voice.shape("¿Te vienes? Hay café.", allow_question=False)
        self.assertNotIn("?", out)

    def test_recorta_prosa_larga(self):
        out = self.voice.shape("palabra " * 100, max_chars=120)
        self.assertLessEqual(len(out), 121)

    def test_no_recorta_codigo_largo(self):
        body = "x = 1\n" * 80
        text = f"Listo:\n```python\n{body}```"
        out = self.voice.shape(text, max_chars=120)
        self.assertIn("x = 1", out)
        self.assertGreater(len(out), 120)


class EmotionTests(unittest.TestCase):
    def test_normal_no_es_triste(self):
        # El bug: "mal" casaba dentro de "normal" → emoción triste falsa.
        self.assertEqual(EmotionDetector.detect_emotion("el examen fue normal"),
                         "neutral")

    def test_tristeza_real(self):
        self.assertEqual(EmotionDetector.detect_emotion("me siento mal"), "triste")

    def test_alegria(self):
        self.assertEqual(EmotionDetector.detect_emotion("qué alegría, gracias"),
                         "feliz")


if __name__ == "__main__":
    unittest.main()
