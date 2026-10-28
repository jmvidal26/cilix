#!/usr/bin/env python3
"""
Utilidades de seguridad de Cilix
================================
Dos comprobaciones pequeñas y sin estado, usadas por `main.py` y testeables
sin levantar el servidor:

  · `origin_allowed()` → solo páginas servidas desde localhost pueden abrir el
    WebSocket. Sin esto, CUALQUIER web abierta en el navegador podía conectar a
    `ws://127.0.0.1:8765` y ejecutar comandos locales (el navegador no aplica
    CORS a WebSockets).
  · `path_within()` → resuelve symlinks y confirma que una ruta del cliente
    sigue dentro de la carpeta permitida (p. ej. la cola social), evitando
    `../../` y enlaces maliciosos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# Hosts desde los que se sirve la interfaz (modo navegador y Electron).
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def origin_allowed(origin: Optional[str], hosts: frozenset = LOCAL_HOSTS) -> bool:
    """¿El `Origin` de un WebSocket es local (o no existe)?

    - Sin cabecera `Origin` → cliente no-navegador (script local, tests): OK.
    - `http(s)://localhost|127.0.0.1|[::1]` → OK.
    - `file://` / `null` / cualquier dominio externo → RECHAZADO. Un iframe
      sandboxed también manda `null`, así que no se puede confiar en él.
    """
    if origin is None or origin == "":
        return True
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host in hosts


def path_within(path: str, root: Path) -> Optional[Path]:
    """Resuelve `path` y lo devuelve solo si está dentro de `root`.

    Devuelve `None` si la ruta no existe, no se puede resolver o escapa del
    directorio raíz (incluidos symlinks que apunten fuera).
    """
    if not path:
        return None
    try:
        real_root = Path(root).expanduser().resolve()
        real_path = Path(path).expanduser().resolve()
        real_path.relative_to(real_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return real_path
