#!/usr/bin/env python3
"""Tests de persistencia de memoria (SQLite temporal, sin tocar ~/.config)."""

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from memory import MemoryStore  # noqa: E402


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "memory.db")
        self.mem = MemoryStore(db_path=self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_guarda_y_lee_mensajes_en_orden(self):
        self.mem.add_message("cilix", "user", "hola")
        self.mem.add_message("cilix", "assistant", "hey", emotion="feliz")
        rows = self.mem.recent_messages("cilix", limit=10)
        self.assertEqual([r["role"] for r in rows], ["user", "assistant"])
        self.assertEqual(rows[1]["emotion"], "feliz")

    def test_hechos_sobreviven_al_chat_nuevo(self):
        self.mem.remember_fact("user.name", "Jesús")
        self.mem.add_message("cilix", "user", "hola")
        self.mem.clear_session("cilix")
        self.assertEqual(self.mem.recent_messages("cilix"), [])
        self.assertEqual(self.mem.get_fact("user.name"), "Jesús")

    def test_float_fact(self):
        self.mem.set_float_fact("mood.valence", 0.4)
        self.assertAlmostEqual(self.mem.get_float_fact("mood.valence"), 0.4)
        self.assertEqual(self.mem.get_float_fact("no.existe", 1.5), 1.5)


if __name__ == "__main__":
    unittest.main()
