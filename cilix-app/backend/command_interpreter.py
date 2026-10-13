#!/usr/bin/env python3
"""
Intérprete de intenciones de comando para Cilix
===============================================
Convierte frases en lenguaje natural (español) en acciones concretas que el
`OSController` puede ejecutar: lanzar aplicaciones, crear carpetas, listar
archivos o consultar el estado del sistema.

Diseño defensivo:
· Solo devuelve una acción cuando la coincidencia es CLARA; si no, devuelve
  None y el mensaje se deja al cerebro (Ri/Re) para conversación normal.
· Los comandos generados pasan SIEMPRE por el sandbox de `OSController`
  (lista blanca/negra, saneado y límites), nunca se ejecutan directo aquí.
· Prefijo explícito `!` o `$` → se trata como comando de shell literal.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional


def _norm(text: str) -> str:
    """Minúsculas y sin tildes, para que 'abre/ábreme/Abre' coincidan."""
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


# Sinónimos → ejecutable real (el OSController valida que esté instalado)
APP_SYNONYMS = {
    "navegador": "firefox", "browser": "firefox", "chrome": "chromium",
    "chromium": "chromium", "firefox": "firefox",
    "carpeta": "nautilus", "archivador": "nautilus", "explorador": "nautilus",
    "gestor de archivos": "nautilus", "files": "nautilus",
    "editor": "gedit", "texto": "gedit", "bloc de notas": "gedit",
    "terminal": "gnome-terminal", "consola": "gnome-terminal",
    "codigo": "code", "vscode": "code", "visual studio": "code",
    "editor de codigo": "code",
    "musica": "vlc", "reproductor": "vlc", "video": "vlc", "vlc": "vlc",
    "imagen": "gimp", "foto": "gimp", "gimp": "gimp", "fotos": "gimp",
    "correo": "thunderbird", "email": "thunderbird", "thunderbird": "thunderbird",
    "office": "libreoffice", "word": "libreoffice", "excel": "libreoffice",
}

LAUNCH_VERBS = r"(?:abre|abrir|abreme|lanza|lanzar|ejecuta|ejecutar|inicia|iniciar|arranca|arrancar|levanta|levanta|corre|correr|activa|activar)"
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_\-\. ]+")


@dataclass
class Intent:
    """Acción a ejecutar. `kind` es 'launch' (app) o 'command' (shell)."""
    kind: str
    reply_hint: str = ""
    app: Optional[str] = None
    args: List[str] = field(default_factory=list)
    command: Optional[str] = None


class CommandInterpreter:
    """Reconoce intenciones de acción en un mensaje de texto."""

    def interpret(self, message: str) -> Optional[Intent]:
        raw = (message or "").strip()
        if not raw:
            return None
        low = _norm(raw)

        # 1) Comando literal explícito:  "!ls -la"  /  "$uptime"
        if raw[0] in ("!", "$"):
            cmd = raw[1:].strip()
            if cmd:
                return Intent(kind="command", command=cmd, reply_hint="Ejecuté el comando.")
            return None

        # 2) Lanzar aplicación:  "abre firefox", "lanza el navegador"
        m = re.search(rf"^\s*{LAUNCH_VERBS}\s+(?:el|la|los|las|un|una|mi)?\s*(.+?)\s*$", low)
        if m:
            target = m.group(1).strip()
            app = self._resolve_app(target)
            if app:
                return Intent(kind="launch", app=app,
                              reply_hint=f"Lanzando {app}.")

        # 3) Crear carpeta:  "crea una carpeta llamada pruebas"
        m = re.search(r"(?:crea|crear|nueva)\s+(?:una?\s+)?carpeta\s+(?:llamada\s+|de\s+nombre\s+)?([a-z0-9_\- ]+)", low)
        if m:
            name = SAFE_NAME_RE.sub("", m.group(1).strip()).strip() or "nueva_carpeta"
            return Intent(kind="command", command=f'mkdir -p ~/Documents/{name}',
                          reply_hint=f"Creé la carpeta «{name}» en Documentos.")

        # 4) Consultas del sistema (patrones concretos para no secuestrar charla)
        sysmap = [
            (r"\b(que|cual es|dime).*(hora)\b", "date '+%H:%M del %d/%m/%Y'"),
            (r"\b(fecha|que dia)\b", "date"),
            (r"\b(ram|memoria)\b", "free -h"),
            (r"\b(cpu|procesador|carga)\b", "uptime"),
            (r"\b(disco|espacio libre|almacenamiento)\b", "df -h"),
            (r"\b(quien soy|usuario actual|mi usuario)\b", "whoami"),
            (r"\b(info del sistema|estado del sistema|mi pc|mi equipo)\b", "uname -a"),
            (r"\b(procesos|que se esta ejecutando)\b", "ps aux"),
            (r"\b(nombre del equipo|hostname)\b", "hostname"),
        ]
        for pat, cmd in sysmap:
            if re.search(pat, low):
                return Intent(kind="command", command=cmd, reply_hint="Aquí tienes el dato del sistema.")

        # 5) Listar archivos:  "lista los archivos de Descargas"
        if re.search(r"\b(lista|muestra|ensena|enseña|dime que hay|que archivos)\b", low) and \
           re.search(r"\b(archivos|ficheros|contenido|carpeta|directorios)\b", low):
            path = self._extract_path(raw)
            return Intent(kind="command", command=f"ls -la {path}",
                          reply_hint="Esto es lo que encontré.")

        return None  # no es una acción clara → conversación normal

    # ── Ayudantes ──────────────────────────────────────────────────────────
    def _resolve_app(self, target: str) -> Optional[str]:
        target = target.strip()
        if target in APP_SYNONYMS:
            return APP_SYNONYMS[target]
        # ¿menciona un sinónimo dentro de la frase? ("el navegador de internet")
        for syn, exe in APP_SYNONYMS.items():
            if re.search(rf"\b{re.escape(syn)}\b", target):
                return exe
        # ¿es ya un ejecutable plausible (solo letras/números/-)?
        if re.fullmatch(r"[a-z0-9\-]+", target):
            return target
        return None

    @staticmethod
    def _extract_path(message: str) -> str:
        """Deduce una ruta (~/...) a partir de la frase; por defecto el home."""
        m = re.search(r"(?:de|en|del|desde)\s+([A-Za-z0-9_\-/\.\~ ]+)", message)
        if not m:
            return "~"
        frag = m.group(1).strip().rstrip("?.!,")
        known = {
            "descargas": "~/Downloads", "downloads": "~/Downloads",
            "documentos": "~/Documents", "documents": "~/Documents",
            "imagenes": "~/Pictures", "imágenes": "~/Pictures",
            "musica": "~/Music", "música": "~/Music",
            "videos": "~/Videos", "escritorio": "~/Desktop",
        }
        key = _norm(frag)
        return known.get(key, f"~/{frag}" if "/" not in frag else frag)
