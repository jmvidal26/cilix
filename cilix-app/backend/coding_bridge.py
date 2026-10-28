#!/usr/bin/env python3
"""
Puente Cilix ↔ agentes de programación (Antigravity CLI / Qoder CLI)
====================================================================
Permite que Cilix delegue una tarea de código a un agente externo sin
cargarlo en su propio proceso:

    Cilix (chat) → este puente → `agy -p ...` / `qoder -p ...`
                                   │
                                   └─ edita archivos en el proyecto

Ventajas de hacerlo por subproceso:
· RAM: el agente solo existe mientras dura la tarea (0 MB en reposo).
· Aislamiento: si el agente falla o se cuelga, Cilix sigue vivo.
· Control: se limita el directorio de trabajo, el modo de permisos y el
  tiempo máximo; por defecto NO se aprueban comandos arbitrarios.

Configuración (ver `.env.example`):
    CILIX_CODER_ENABLED   true|false
    CILIX_CODER_PROVIDER  auto|agy|qoder
    CILIX_CODER_BIN       ruta explícita al binario (opcional)
    CILIX_CODER_DIR       proyecto por defecto (vacío = autodetectado)
    CILIX_CODER_ROOTS     carpetas donde se permite programar (separadas por :)
    CILIX_CODER_MODE      plan|accept-edits
    CILIX_CODER_MODEL     modelo del agente (vacío = el suyo por defecto)
    CILIX_CODER_SANDBOX   true|false
    CILIX_CODER_AUTO      true = --dangerously-skip-permissions (siempre con sandbox)
    CILIX_CODER_TIMEOUT   segundos máximos por tarea
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("cilix.coder")

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

# Una ruta absoluta o con ~, normalmente detrás de "en", "@" o "proyecto".
WORKSPACE_RE = re.compile(
    r"(?:@|(?:\ben|\bdentro de|\bproyecto|\bcarpeta|\brepo(?:sitorio)?|\bdir(?:ectorio)?)\s+)"
    r"(~?/[^\s,;:!?()\[\]{}'\"`]+)",
    re.IGNORECASE,
)

CODEX_WORDS = re.compile(
    r"\b(?:c[oó]digo|script|programa|funci[oó]n|m[eé]todo|clase|repo(?:sitorio)?|"
    r"proyecto|bug|error|test|prueba|api|backend|frontend|app|web|commit)\b",
    re.IGNORECASE,
)

# Verbos que, al principio del mensaje, indican una orden de programación.
DELEGATE_START_RE = re.compile(
    r"^\s*(?:cilix\s*[,:]\s*)?(?:"
    r"programa(?:r|me|le|s)?|"
    r"delega(?:r|me|lo|le)?|"
    r"p[aá]salo|p[aá]sale|m[aá]ndalo|m[aá]ndale|"
    r"codea"
    r")\b[\s:,\-]*(.*)$",
    re.IGNORECASE,
)

TOOL_RE = re.compile(r"\b(antigravity|qoder|agy)\b", re.IGNORECASE)

# Tareas demasiado vagas: mejor que las resuelva la personalidad de Cilix o
# la actividad de aburrimiento del frontend.
VAGUE_TASKS = {
    "algo", "lo que quieras", "lo que sea", "un rato", "un poco",
    "lo que te apetezca", "lo que te guste",
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _which(name: str) -> Optional[str]:
    """Busca un ejecutable también en ~/.local/bin (PATH de systemd)."""
    found = shutil.which(name)
    if found:
        return found
    for candidate in (Path.home() / ".local" / "bin" / name,
                      Path("/usr/local/bin") / name,
                      Path("/usr/bin") / name):
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue
    return None


def _clean(text: str, limit: int = 1200) -> str:
    """Quita ANSI, markdown y enlaces para poder decirlo en voz alta."""
    text = ANSI_RE.sub("", text or "")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)   # [texto](url)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}[>*+-]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut + "…"
    return text


@dataclass
class CoderRequest:
    """Tarea ya interpretada a partir del mensaje del usuario."""
    task: str
    workspace: Optional[str] = None
    mode: Optional[str] = None


@dataclass
class CoderRun:
    """Resultado de una ejecución del agente."""
    ok: bool
    provider: str
    workspace: str = ""
    task: str = ""
    response: str = ""
    summary: str = ""
    status: str = ""
    duration: float = 0.0
    conversation_id: str = ""
    num_turns: int = 0
    denied: List[str] = field(default_factory=list)
    error: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "ok": self.ok, "provider": self.provider,
            "workspace": self.workspace, "task": self.task,
            "response": self.response, "summary": self.summary,
            "status": self.status, "duration": round(self.duration, 3),
            "conversation_id": self.conversation_id,
            "num_turns": self.num_turns, "denied": self.denied,
            "error": self.error, "usage": self.usage,
        }
        return data


class CoderBridge:
    """Cliente local de Antigravity CLI / Qoder CLI para Cilix."""

    def __init__(
        self,
        enabled: bool = True,
        provider: str = "auto",
        binary: str = "",
        workspace: str = "",
        roots: str = "~/partes:~/Documents:~/Downloads/cilix",
        mode: str = "accept-edits",
        model: str = "",
        sandbox: bool = True,
        auto_approve: bool = False,
        timeout: float = 600.0,
        max_turns: int = 30,
    ) -> None:
        self.enabled = bool(enabled)
        self.requested_provider = (provider or "auto").strip().lower()
        self.binary_override = (binary or "").strip()
        self.roots = self._parse_roots(roots)
        self.mode = self._normalize_mode(mode)
        self.model = (model or "").strip()
        self.sandbox = bool(sandbox)
        # Aprobar todo sin sandbox sería peligroso: se fuerza el sandbox.
        self.auto_approve = bool(auto_approve)
        self.timeout = max(30.0, float(timeout or 600))
        self.max_turns = max(1, int(max_turns or 30))
        self.workspace = self._initial_workspace(workspace)
        self._lock = asyncio.Lock()
        self.last_run: Optional[Dict[str, Any]] = None

    # ── configuración ──────────────────────────────────────────────────
    @staticmethod
    def _parse_roots(raw: str) -> List[Path]:
        roots: List[Path] = []
        for piece in re.split(r"[:;,]", raw or ""):
            piece = piece.strip()
            if not piece:
                continue
            try:
                p = Path(piece).expanduser().resolve()
            except OSError:
                continue
            if p.is_dir() and p not in roots:
                roots.append(p)
        return roots

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        value = (mode or "accept-edits").strip().lower().replace("_", "-")
        return value if value in ("plan", "accept-edits", "auto") else "accept-edits"

    def _allowed_path(self, path: Path) -> Optional[Path]:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return None
        for root in self.roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        return None

    def _initial_workspace(self, requested: str) -> Optional[Path]:
        candidates: List[Path] = []
        if requested:
            candidates.append(Path(requested).expanduser())
        for fallback in (
            Path.home() / "partes" / "Le-fil",
            Path.home() / "partes",
            Path.home() / "Documents",
        ):
            candidates.append(fallback)
        for candidate in candidates:
            allowed = self._allowed_path(candidate)
            if allowed is not None and allowed.is_dir():
                return allowed
        return self.roots[0] if self.roots else None

    # ── detección del proveedor ────────────────────────────────────────
    @property
    def provider(self) -> Optional[str]:
        if not self.enabled:
            return None
        if self.requested_provider in ("agy", "antigravity", "antigravity-cli"):
            return "agy"
        if self.requested_provider in ("qoder", "qoder-cli"):
            return "qoder"
        # auto: se prefiere Antigravity (su CLI headless ya funciona sin login
        # adicional); Qoder queda como alternativa si se instala.
        if _which("agy"):
            return "agy"
        if _which("qoder"):
            return "qoder"
        return None

    @property
    def binary(self) -> Optional[str]:
        if self.binary_override:
            return self.binary_override if Path(self.binary_override).is_file() else None
        provider = self.provider
        if provider == "agy":
            return _which("agy")
        if provider == "qoder":
            return _which("qoder")
        return None

    @property
    def available(self) -> bool:
        return self.binary is not None and self.workspace is not None

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider or "none",
            "binary": self.binary or "",
            "available": self.available,
            "workspace": str(self.workspace) if self.workspace else "",
            "roots": [str(r) for r in self.roots],
            "mode": self.mode,
            "model": self.model,
            "sandbox": self.sandbox,
            "auto_approve": self.auto_approve,
            "timeout": self.timeout,
            "max_turns": self.max_turns,
            "last_run": self.last_run,
        }

    # ── interpretación del mensaje ─────────────────────────────────────
    def interpret(self, text: str) -> Optional[CoderRequest]:
        """Devuelve la tarea si el mensaje pide programar de verdad.

        Es deliberadamente conservador: la charla normal, «programa algo» o
        «haz algo» (actividades de aburrimiento) no se delegan.
        """
        raw = (text or "").strip()
        if not raw or not self.enabled:
            return None
        low = _norm(raw)

        workspace = self._extract_workspace(raw)
        mode = self._extract_mode(low)
        task = ""

        match = DELEGATE_START_RE.match(raw)
        if match:
            task = match.group(1).strip()
            task = self._strip_tool_prefix(task)
        else:
            tool = TOOL_RE.search(raw)
            delegate_hint = re.search(
                r"\b(?:pasa(?:lo|le)|delega(?:r|lo)?|manda(?:lo|le)|"
                r"que\s+(?:programe|haga|escriba|arregle|implemente|cree)|"
                r"programa(?:r|me|le)?)\b",
                low,
            )
            if tool and delegate_hint:
                # "pásalo a Qoder y arregla el bug" → "arregla el bug"
                after = re.search(
                    r"\b(?:antigravity|qoder|agy)\b\s*(?:que\s*)?[:,\-]?\s*(.*)$",
                    raw, re.IGNORECASE)
                task = (after.group(1) if after else raw).strip()
                task = self._strip_tool_prefix(task)
            elif mode == "plan" and CODEX_WORDS.search(low):
                task = re.sub(
                    r"^\s*(?:solo\s+)?plan(?:ifica|ificalo|ear)?\s*[:,\-]\s*",
                    "", raw, flags=re.IGNORECASE).strip() or raw
            elif re.match(
                r"^\s*(?:haz|crea|escribe|implementa|arregla|corrige|"
                r"refactoriza|a[nñ]ade|monta|analiza|revisa|estudia)\b", low,
            ) and CODEX_WORDS.search(low):
                task = raw

        if not task:
            return None

        # Quita la ruta del proyecto de la tarea (el agente ya trabaja en ella).
        if workspace:
            task = re.sub(re.escape(workspace), " ", task)
            task = re.sub(r"\b(?:en|dentro\s+de|para)\s+(?:el\s+|la\s+)?"
                          r"(?:repo(?:sitorio)?|proyecto|carpeta|directorio|dir)?\s*$",
                          "", task, flags=re.IGNORECASE)
            task = task.strip(" ,.;:-")

        if mode == "auto":
            task = re.sub(r"\b(?:en\s+)?modo\s+(?:auto|aut[oó]nomo)\b|"
                          r"\baut[oó]nomo\b", " ", task, flags=re.IGNORECASE)
        elif mode == "plan":
            task = re.sub(r"\b(?:solo\s+)?plan(?:ifica|ificalo|ear)?\b|"
                          r"\bsin\s+(?:tocar|cambiar|modificar)\s+"
                          r"(?:nada|archivos|c[oó]digo)\b", " ", task,
                          flags=re.IGNORECASE)
        task = re.sub(r"\s+", " ", task).strip(" ,.;:-")

        if _norm(task) in VAGUE_TASKS:
            return None
        if len(task) < 3:
            return None
        # "programa de televisión" es un sustantivo, no una orden. Si la
        # tarea empieza por preposición y no se nombró un agente, no delegar.
        if (TOOL_RE.search(raw) is None
                and re.match(r"^(?:de|del|para|por|sobre|con)\b", _norm(task))):
            return None

        return CoderRequest(task=task, workspace=workspace, mode=mode)

    @staticmethod
    def _strip_tool_prefix(task: str) -> str:
        task = re.sub(
            r"^\s*a\s+(?:antigravity|qoder|agy)\b\s*(?:que\s*)?[:,\-]?\s*",
            "", task, flags=re.IGNORECASE)
        task = re.sub(
            r"^\s*(?:antigravity|qoder|agy)\b\s*(?:que\s*)?[:,\-]?\s*",
            "", task, flags=re.IGNORECASE)
        task = re.sub(r"^\s*(?:y|que)\s+", "", task, flags=re.IGNORECASE)
        return task.strip()

    def _extract_workspace(self, text: str) -> Optional[str]:
        found: Optional[str] = None
        for match in WORKSPACE_RE.finditer(text):
            candidate = match.group(1).rstrip(".,;:!?")
            try:
                path = Path(candidate).expanduser()
            except (OSError, ValueError):
                continue
            # Solo rutas dentro de las carpetas permitidas (evita confundir
            # una ruta de código como /api/foo con un proyecto).
            allowed = self._allowed_path(path)
            if allowed is None:
                continue
            if allowed.is_dir() or len(allowed.parts) >= 2:
                found = candidate
        return found

    @staticmethod
    def _extract_mode(low: str) -> Optional[str]:
        if re.search(r"\b(?:solo\s+)?plan(?:ifica|ificalo|ear)?\b|"
                     r"\bsin\s+(?:tocar|cambiar|modificar)\s+"
                     r"(?:nada|archivos|c[oó]digo)\b|"
                     r"\bsolo\s+(?:analiza|revisa|mira)\b", low):
            return "plan"
        if re.search(r"\b(?:en\s+)?modo\s+(?:auto|aut[oó]nomo)\b|"
                     r"\baut[oó]nomo\b|"
                     r"\bsin\s+(?:preguntar|confirmar|pedir\s+permisos)\b|"
                     r"\ba\s+saco\b", low):
            return "auto"
        return None

    # ── resolución del directorio de trabajo ───────────────────────────
    def _resolve_workspace(
        self, requested: Optional[str],
    ) -> Tuple[Optional[Path], str]:
        if not self.roots:
            return None, ("No hay carpetas de trabajo permitidas. Configura "
                          "CILIX_CODER_ROOTS en el .env.")
        if requested:
            path = Path(requested).expanduser()
        else:
            path = self.workspace
        if path is None:
            return None, ("No encuentro una carpeta de proyecto. Dime una ruta "
                          "dentro de tus carpetas permitidas.")
        allowed = self._allowed_path(path)
        if allowed is None:
            roots = ", ".join(str(r) for r in self.roots)
            return None, (f"No puedo programar en {path}: está fuera de las "
                          f"carpetas permitidas ({roots}).")
        if not allowed.exists():
            try:
                allowed.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return None, f"No pude crear la carpeta {allowed}: {exc}"
        if not allowed.is_dir():
            return None, f"{allowed} no es una carpeta."
        return allowed, ""

    # ── ejecución ──────────────────────────────────────────────────────
    def _build_command(self, prompt: str, mode: str) -> List[str]:
        provider = self.provider
        binary = self.binary or (provider or "")
        auto = (mode == "auto") or self.auto_approve
        if provider == "qoder":
            permission = "plan" if mode == "plan" else "accept_edits"
            cmd = [binary, "-p", prompt, "--output-format", "json",
                   "--permission-mode", permission]
            if self.model:
                cmd += ["--model", self.model]
            cmd += ["--max-turns", str(self.max_turns)]
            # Qoder no expone un flag de sandbox equivalente; su modo de
            # permisos controla qué herramientas puede usar.
            if auto:
                cmd.append("--yolo")
            return cmd

        # El modo "auto" de Antigravity no está disponible para todas las
        # cuentas: se traduce a accept-edits + aprobación total dentro del
        # sandbox (nunca sin sandbox).
        agy_mode = "accept-edits" if mode == "auto" else mode
        cmd = [binary, "-p", prompt, "--output-format", "json",
               "--mode", agy_mode, "--print-timeout", f"{int(self.timeout)}s"]
        if self.model:
            cmd += ["--model", self.model]
        if auto:
            cmd.append("--dangerously-skip-permissions")
            if "--sandbox" not in cmd:
                cmd.append("--sandbox")
        elif self.sandbox:
            cmd.append("--sandbox")
        return cmd

    @staticmethod
    def _prompt(task: str, workspace: Path) -> str:
        return (
            "Eres el agente de programación de Cilix. Trabaja directamente en "
            f"el directorio actual ({workspace}).\n"
            f"Tarea de programación: {task}\n"
            "Reglas: responde en español y sé breve; inspecciona el proyecto "
            "con las herramientas de lectura/escritura de archivos y evita la "
            "terminal salvo que sea imprescindible (en modo headless puede no "
            "tener permiso); no toques archivos fuera de este directorio; si "
            "un comando necesita un permiso que no tienes, dilo en vez de "
            "inventar el resultado. Al terminar, escribe una última línea con "
            "el formato 'RESUMEN: <qué hiciste y qué archivos tocaste>'."
        )

    async def run(
        self,
        task: str,
        workspace: Optional[str] = None,
        mode: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return CoderRun(
                ok=False, provider="none",
                error="La programación delegada está desactivada "
                      "(CILIX_CODER_ENABLED=false).").to_dict()
        provider = self.provider
        if provider is None:
            return CoderRun(
                ok=False, provider="none",
                error="No encuentro Antigravity CLI (`agy`) ni Qoder CLI "
                      "(`qoder`). Instala uno o configura CILIX_CODER_BIN.").to_dict()
        binary = self.binary
        if not binary:
            return CoderRun(
                ok=False, provider=provider,
                error=f"No encuentro el binario de {provider}.").to_dict()

        target, ws_error = self._resolve_workspace(workspace)
        if target is None:
            return CoderRun(ok=False, provider=provider, error=ws_error).to_dict()

        chosen_mode = self._normalize_mode(mode or self.mode)
        limit = max(30.0, float(timeout or self.timeout))
        prompt = self._prompt(task.strip(), target)
        cmd = self._build_command(prompt, chosen_mode)
        started = time.time()

        env = os.environ.copy()
        env.setdefault("NO_COLOR", "1")
        env.setdefault("TERM", "dumb")
        env.setdefault("GIT_PAGER", "cat")

        logger.info("🧑‍💻 Delegando a %s en %s (modo %s, %ss): %s",
                    provider, target, chosen_mode, int(limit), task[:120])

        async with self._lock:  # una tarea de programación a la vez
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, cwd=str(target),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env, start_new_session=True,
                )
            except FileNotFoundError:
                return CoderRun(
                    ok=False, provider=provider, workspace=str(target), task=task,
                    error=f"No pude ejecutar {binary}.").to_dict()
            except Exception as exc:  # noqa: BLE001
                return CoderRun(
                    ok=False, provider=provider, workspace=str(target), task=task,
                    error=f"No pude lanzar {provider}: {exc}").to_dict()

            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=limit)
            except asyncio.TimeoutError:
                self._kill(proc)
                await proc.communicate()
                return CoderRun(
                    ok=False, provider=provider, workspace=str(target), task=task,
                    duration=time.time() - started,
                    error=f"{provider} tardó más de {int(limit)} s. "
                          "La tarea se ha detenido; prueba a dividirla.").to_dict()

        result = self._parse(
            out=out or b"", err=err or b"", provider=provider,
            workspace=target, task=task, started=started)
        self.last_run = {
            "ts": time.time(), "provider": provider, "workspace": str(target),
            "task": task[:300], "ok": result.ok, "summary": result.summary,
            "duration": round(result.duration, 1), "status": result.status,
        }
        logger.info("🧑‍💻 %s terminó en %.1fs (ok=%s): %s",
                    provider, result.duration, result.ok, result.summary[:120])
        return result.to_dict()

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    def _parse(
        self, out: bytes, err: bytes, provider: str,
        workspace: Path, task: str, started: float,
    ) -> CoderRun:
        stdout = ANSI_RE.sub("", out.decode("utf-8", "replace")).strip()
        stderr = ANSI_RE.sub("", err.decode("utf-8", "replace")).strip()
        payload: Optional[Dict[str, Any]] = None

        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
                break
        if payload is None and stdout:
            try:
                candidate = json.loads(stdout)
                if isinstance(candidate, dict):
                    payload = candidate
            except json.JSONDecodeError:
                pass

        duration = time.time() - started
        if payload is None:
            raw = _clean(stdout or stderr, limit=600)
            return CoderRun(
                ok=bool(stdout), provider=provider, workspace=str(workspace),
                task=task, response=stdout[:4000], summary=raw,
                duration=duration, error="" if stdout else (stderr[:400] or
                f"{provider} no devolvió nada."))

        response = str(
            payload.get("response") or payload.get("result") or
            payload.get("content") or payload.get("message") or ""
        ).strip()
        status = str(payload.get("status") or "").strip()
        denied_raw = payload.get("denied_actions") or []
        denied: List[str] = []
        if isinstance(denied_raw, list):
            for item in denied_raw:
                if isinstance(item, dict):
                    denied.append(str(item.get("action") or item.get("display_name") or ""))
                else:
                    denied.append(str(item))
        denied = [d for d in denied if d]

        result = CoderRun(
            ok=True, provider=provider, workspace=str(workspace), task=task,
            response=response, status=status,
            duration=duration,
            conversation_id=str(payload.get("conversation_id") or ""),
            num_turns=int(payload.get("num_turns") or 0),
            denied=denied,
            usage=payload.get("usage") or {},
        )

        if not response:
            result.ok = False
            if "not installed" in (stdout + stderr).lower():
                result.error = (
                    "Qoder CLI no está instalado. Instálalo desde "
                    "https://qoder.com o usa Antigravity (CILIX_CODER_PROVIDER=agy).")
            elif denied:
                result.error = (
                    f"{provider} no pudo ejecutar la acción '{denied[0]}': en "
                    "modo headless no puede pedir permisos. Los archivos sí se "
                    "pueden editar; para permitir comandos añade reglas en "
                    "~/.gemini/antigravity-cli/settings.json o activa "
                    "CILIX_CODER_AUTO=true (siempre con sandbox).")
            elif status and status.upper() not in ("SUCCESS", "OK", "COMPLETED"):
                result.error = (stderr.splitlines()[-1] if stderr else
                                f"{provider} terminó con estado {status} sin respuesta.")
            else:
                result.error = (stderr.splitlines()[-1] if stderr else
                                f"{provider} no devolvió respuesta.")
            return result

        result.summary = self._summary(response)
        return result

    @staticmethod
    def _summary(response: str) -> str:
        match = re.search(r"RESUMEN\s*:\s*(.+)$", response,
                          flags=re.IGNORECASE | re.DOTALL)
        text = match.group(1) if match else response
        return _clean(text, limit=450)

    # ── formato hablado ────────────────────────────────────────────────
    @staticmethod
    def format_reply(data: Dict[str, Any]) -> str:
        if not data.get("ok"):
            reason = _clean(str(data.get("error") or "error desconocido"), 300)
            return f"No he podido programarlo: {reason}"
        name = Path(str(data.get("workspace") or "")).name or "el proyecto"
        summary = _clean(str(data.get("summary") or ""), 380)
        secs = data.get("duration") or 0
        if not summary:
            summary = "El agente terminó sin dejar un resumen."
        return f"Listo en {name} ({float(secs):.0f} s). {summary}"
