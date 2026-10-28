#!/usr/bin/env python3
"""Tests del puente de programación (sin lanzar Antigravity/Qoder)."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from coding_bridge import CoderBridge  # noqa: E402


def bridge_for(root: Path) -> CoderBridge:
    return CoderBridge(
        enabled=True, provider="agy", roots=str(root),
        workspace=str(root), mode="accept-edits", sandbox=True,
        timeout=60, max_turns=10,
    )


class CoderIntentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bridge = bridge_for(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_programa_una_tarea(self):
        req = self.bridge.interpret(
            "programa un script que sume dos números")
        self.assertIsNotNone(req)
        self.assertIn("script", req.task)

    def test_pasalo_a_qoder(self):
        req = self.bridge.interpret(
            "pásalo a Qoder: arregla el bug del login")
        self.assertIsNotNone(req)
        self.assertEqual(req.task, "arregla el bug del login")

    def test_arregla_con_contexto_de_codigo(self):
        req = self.bridge.interpret("arregla este bug en la API")
        self.assertIsNotNone(req)
        self.assertIn("bug", req.task)

    def test_charla_normal_no_se_delega(self):
        self.assertIsNone(self.bridge.interpret("hola, ¿qué tal?"))
        self.assertIsNone(self.bridge.interpret("el programa de la tele"))
        self.assertIsNone(self.bridge.interpret("programa de televisión"))
        self.assertIsNone(self.bridge.interpret("programa algo"))

    def test_extrae_workspace_permitido(self):
        project = self.root / "proyecto"
        req = self.bridge.interpret(
            f"arregla este bug en {project}")
        self.assertIsNotNone(req)
        self.assertEqual(req.workspace, str(project))
        self.assertNotIn(str(project), req.task)

    def test_modo_plan(self):
        req = self.bridge.interpret(
            "solo plan: analiza el bug de la API y dime qué falla")
        self.assertIsNotNone(req)
        self.assertEqual(req.mode, "plan")

    def test_workspace_fuera_de_raices_se_rechaza(self):
        target, error = self.bridge._resolve_workspace("/etc")
        self.assertIsNone(target)
        self.assertIn("fuera", error)

    def test_workspace_nuevo_dentro_de_raices_se_crea(self):
        project = self.root / "nuevo"
        target, error = self.bridge._resolve_workspace(str(project))
        self.assertIsNotNone(target, error)
        self.assertTrue(project.is_dir())


class CoderParsingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bridge = bridge_for(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def _parse(self, payload, stderr=b""):
        return self.bridge._parse(
            out=json.dumps(payload).encode(), err=stderr,
            provider="agy", workspace=self.root, task="tarea",
            started=time.time(),
        )

    def test_parsea_json_y_resumen(self):
        run = self._parse({
            "status": "SUCCESS", "conversation_id": "abc",
            "num_turns": 1, "duration_seconds": 3.2,
            "response": "Hecho.\nRESUMEN: creé suma.py y su test.",
        })
        self.assertTrue(run.ok)
        self.assertEqual(run.summary, "creé suma.py y su test.")
        self.assertEqual(run.conversation_id, "abc")

    def test_denied_actions_da_mensaje_util(self):
        run = self._parse({
            "status": "SUCCESS", "response": "",
            "denied_actions": [{"action": "command"}],
        })
        self.assertFalse(run.ok)
        self.assertIn("permisos", run.error)
        self.assertIn("CILIX_CODER_AUTO", run.error)

    def test_comando_incluye_sandbox_y_modo(self):
        cmd = self.bridge._build_command("hola", "accept-edits")
        self.assertIn("--sandbox", cmd)
        self.assertIn("accept-edits", cmd)
        self.assertIn("--print-timeout", cmd)

    def test_auto_approve_siempre_lleva_sandbox(self):
        self.bridge.auto_approve = True
        self.bridge.sandbox = False
        cmd = self.bridge._build_command("hola", "accept-edits")
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn("--sandbox", cmd)

    def test_modo_auto_pide_aprobacion_pero_con_sandbox(self):
        cmd = self.bridge._build_command("hola", "auto")
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertIn("accept-edits", cmd)
        self.assertNotIn("auto", cmd)

    def test_interpreta_modo_autonomo(self):
        req = self.bridge.interpret(
            "programa en modo autónomo un script que borre los temporales")
        self.assertIsNotNone(req)
        self.assertEqual(req.mode, "auto")

    def test_la_palabra_auto_no_activa_modo_autonomo(self):
        req = self.bridge.interpret(
            "programa un script que imprima AUTO por pantalla")
        self.assertIsNotNone(req)
        self.assertIsNone(req.mode)
        self.assertIn("AUTO", req.task)

    def test_format_reply_feliz(self):
        reply = CoderBridge.format_reply({
            "ok": True, "workspace": str(self.root / "demo"),
            "summary": "creé hola.py", "duration": 4.2,
        })
        self.assertIn("demo", reply)
        self.assertIn("creé hola.py", reply)
        self.assertIn("4 s", reply)


if __name__ == "__main__":
    unittest.main()
