"""SocialEngine · agente de contenido social para Cilix (Human-in-the-Loop).

Instagram/Meta son plataformas CERRADAS: cualquier script que publique por su
cuenta acaba baneado. Aquí Ri actúa como creadora autónoma que prepara el
paquete completo y lo deja LISTO en disco + como tarjeta en la UI; el humano
decide y publica. Cero APIs externas, cero RAM extra (usa el modelo residente
qwen2.5:3b vía CoreIA.complete y la voz ya cargada de Piper/Kokoro si existe).

Flujo:
  1) prepare(sub, topic) → LLM redacta: caption ES + hashtags técnicos +
     guion de 15 s para Reel (si aplica).
  2) Se guarda el borrador en ~/Documents/cilix-social/post_<ts>.md (y .json
     para consumo por scripts). Para Reels se crea además un JOB aislado en
     ~/Documents/cilix-social/queue/job_<ts>/ con meta.json + recursos.
  3) reel_voice(pack) sintetiza el guion a .wav DENTRO del job y encola el
     render. Un consumidor en hilo daemon (un solo trabajo a la vez) compone
     el .mp4 vertical 9:16 con el binario nativo `ffmpeg` (libx264
     -tune stillimage -preset ultrafast): CPU barata, sin navegadores ni
     librerías de vídeo pesadas, sin bloquear el event loop de FastAPI.
  4) El panel HITL consulta el estado leyendo meta.json (get_job_status /
     list_jobs): awaiting_audio → ready → rendering → done | error.

Nunca publica por sí sola: el humano revisa, copia o abre el resultado.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("cilix.social")

SOCIAL_DIR = Path.home() / "Documents" / "cilix-social"
QUEUE_DIR = SOCIAL_DIR / "queue"                 # cola de jobs Productor→Consumidor
TEMPLATE_DIR = SOCIAL_DIR / "templates"          # plantillas de fondo del usuario
REEL_BG_TEMPLATE = TEMPLATE_DIR / "reel_bg.png"  # fondo 9:16 preferido (si existe)

# Formato vertical 9:16 estándar de Reels; el fallback se pinta con ffmpeg
# (lavfi) para no arrastrar Pillow ni navegadores headless.
REEL_SIZE = "1080x1920"
REEL_FALLBACK_COLOR = "0x0a121c"                 # azulón Cilix oscuro

# Estados del ciclo de vida de un job (visibles desde meta.json):
ST_AWAIT = "awaiting_audio"    # pack creado, esperando la voz del TTS
ST_READY = "ready"             # audio listo, pendiente de render
ST_RENDERING = "rendering"     # ffmpeg en marcha
ST_DONE = "done"               # .mp4 finalizado y localizado
ST_ERROR = "error"             # fallo (ffmpeg ausente, audio roto, timeout…)

# Timeout defensivo del render: un stillimage de 15 s en CPU debe tardar
# segundos; 10 min es margen de sobra bajo swap sin colgar el worker.
RENDER_TIMEOUT_S = 600

# Prompt de redacción: salida JSON estricta (fácil de validar y guardar).
_PACK_PROMPT = (
    "Eres la creadora de contenido de un proyecto local de IA llamado Cilix "
    "(asistente VTuber de escritorio, Python/FastAPI/Live2D/Ollama, 100% "
    "offline en 8GB de RAM, estética build-in-public). Redacta para el tema "
    "indicado SOLO en JSON valido, sin markdown ni explicaciones, con las "
    'claves: "caption" (texto en español de 150 a 280 caracteres, tono '
    'personal y entusiasta, sin clickbait), "hashtags" (array de 8 a 12 '
    'hashtags tecnicos relevantes en minuscula, incluye #BuildInPublic y '
    '#Python), "guion_reel" (guion hablado de maximo 15 segundos, 2-3 frases '
    'cortas en espanol, tono natural).\n'
    "Tema: {topic}\n"
    "JSON:"
)


@dataclass
class SocialPack:
    """Paquete de contenido ya redactado y guardado en disco."""
    kind: str                    # 'post' | 'reel'
    topic: str
    caption: str
    hashtags: list
    script: str = ""             # guion del reel (vacío si es solo post)
    draft_path: str = ""
    audio_path: str = ""
    job_id: str = ""             # carpeta de trabajo del reel (queue/job_<ts>)
    created: float = field(default_factory=time.time)

    def summary(self) -> str:
        tags = " ".join("#" + h.lstrip("#") for h in self.hashtags[:8])
        out = f"📝 Caption: {self.caption}\n{tags}"
        if self.script:
            out += f"\n🎬 Guion (15 s): {self.script}"
        out += f"\n📁 Borrador: {self.draft_path}"
        if self.audio_path:
            out += f"\n🔊 Voz: {self.audio_path}"
        if self.job_id:
            out += f"\n🎞️ Job: ~/{self.job_id.replace(str(Path.home()) + '/', '')}"
        return out


class SocialEngine:
    """Redacción + ensamblaje local + render de Reels en segundo plano.

    NUNCA publica por sí sola. El render usa una cola productor→consumidor
    por archivos: cada job vive en su carpeta con meta.json, de modo que el
    panel HITL (o un reinicio del backend) puede consultar/retomar el estado
    sin depender de memoria compartida ni del event loop."""

    def __init__(self, ai: Any, get_audio=None) -> None:
        self.ai = ai                      # CoreIA (usa .complete)
        # callable → AudioEngine o None (puede no estar listo al construir)
        self.get_audio = get_audio or (lambda: None)
        SOCIAL_DIR.mkdir(parents=True, exist_ok=True)
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

        # ── Consumer (hilo daemon, un job a la vez: nada de picos de CPU) ──
        self._jobs_q: "queue.Queue[str]" = queue.Queue()
        self._worker_lock = threading.Lock()
        self._worker_started = False
        # Rescate de jobs huérfanos tras un reinicio (audio listo, sin mp4).
        self._recover_pending_jobs()

    # ══ Generación principal ═════════════════════════════════════════════
    async def prepare(self, kind: str = "post", topic: str = "") -> Optional[SocialPack]:
        """Redacta el pack (caption+hashtags+guion) y lo guarda en disco.

        Si es un Reel, abre además la carpeta de trabajo del job y deja el
        meta.json en estado 'awaiting_audio' a la espera del TTS."""
        topic = (topic or "").strip() or "un avance del proyecto Cilix de hoy"
        prompt = _PACK_PROMPT.replace("{topic}", topic[:200])
        raw = await self.ai.complete(prompt, num_predict=280, temperature=0.8,
                                     json_mode=True)
        data = self._extract_json(raw)
        if not data or not (data.get("caption") or "").strip():
            logger.warning("⚠️ social: el modelo no devolvió un pack válido: %r",
                           (raw or "")[:120])
            return None
        pack = SocialPack(
            kind=kind if kind in ("post", "reel") else "post",
            topic=topic,
            caption=str(data.get("caption", "")).strip()[:400],
            hashtags=[str(h).strip() for h in (data.get("hashtags") or []) if str(h).strip()][:12],
            script=str(data.get("guion_reel", "")).strip()[:300],
        )
        # Tolera al 3B "perezoso": a veces mete los hashtags DENTRO del caption
        # y devuelve el array vacío → se los extrae y limpia de ahí.
        if not pack.hashtags:
            found = re.findall(r"#\w+", pack.caption)
            if found:
                pack.hashtags = [t.lstrip("#") for t in dict.fromkeys(found)][:12]
                pack.caption = re.sub(r"\s*(?:#\w+\s*)+$", "", pack.caption).strip()

        if pack.kind == "reel":
            # Productor: abre el job (queue/job_<ts>/) y publica meta.json.
            job_dir = self._create_job(pack)
            pack.job_id = str(job_dir)
            pack.draft_path = await asyncio.to_thread(self._save_draft, pack, job_dir)
        else:
            pack.draft_path = await asyncio.to_thread(self._save_draft, pack, None)
        logger.info("📦 Pack social listo (%s): %s", pack.kind, pack.draft_path)
        return pack

    async def reel_voice(self, pack: SocialPack) -> str:
        """(Productor) Sintetiza el guion a .wav dentro del job y ENCOLA el
        render. No espera a ffmpeg: el worker lo componen en segundo plano
        para que FastAPI y el modelo residente no sufran bloqueos."""
        if not pack.script or pack.audio_path:
            return pack.audio_path
        audio = self.get_audio()
        if audio is None:
            return ""
        try:
            speech = await audio.synthesize(pack.script)
            if not speech:
                return ""
            wav = base64.b64decode(speech.wav_b64)
            # El job es la unidad de trabajo; si no existiera (p.ej. pack
            # antiguo), se crea ahora para no perder el render.
            job_dir = self._ensure_job(pack)
            p = job_dir / f"reel_voice_{int(pack.created)}.wav"
            await asyncio.to_thread(p.write_bytes, wav)
            pack.audio_path = str(p)
            # Actualiza meta.json (audio localizado) y pasa la antorcha al
            # consumidor: estado 'ready' + encolado.
            self._update_meta(job_dir, status=ST_READY, audio_path=str(p),
                              output_video="")
            self._enqueue_job(job_dir)
            logger.info("🔊 Voz del reel lista → render encolado: %s", p)
        except Exception as exc:  # noqa: BLE001
            logger.warning("social reel_voice: %s", exc)
        return pack.audio_path

    # ══ Consumer: render en segundo plano (ffmpeg puro) ══════════════════
    def _ensure_worker(self) -> None:
        """Levanta el hilo consumidor una sola vez (daemon: muere con el
        proceso; los jobs pendientes se rescatan en el próximo arranque)."""
        with self._worker_lock:
            if self._worker_started:
                return
            t = threading.Thread(target=self._render_worker,
                                 name="cilix-reel-render", daemon=True)
            t.start()
            self._worker_started = True

    def _enqueue_job(self, job_dir: Path) -> None:
        self._ensure_worker()
        self._jobs_q.put(str(job_dir))

    def _render_worker(self) -> None:
        """Bucle consumidor: UN job por vez (serializa el coste de ffmpeg y
        protege la máquina de 8 GB). Nunca lanza excepciones al exterior."""
        while True:
            job_path = self._jobs_q.get()
            try:
                self.render_reel_background(Path(job_path))
            except Exception as exc:  # noqa: BLE001
                logger.error("❌ render job %s: %s", job_path, exc)
                self._update_meta(Path(job_path), status=ST_ERROR,
                                  error=str(exc)[:200])
            finally:
                self._jobs_q.task_done()

    def render_reel_background(self, job_dir: Path) -> str:
        """Compone el .mp4 vertical 9:16 combinando la plantilla de fondo
        estática con el .wav del job usando SOLO el binario `ffmpeg`.

        Parámetros ligeros de CPU (los exactos del diseño):
          -loop 1 -i fondo -i audio -c:v libx264 -tune stillimage
          -c:a aac -b:a 128k -pix_fmt yuv420p -shortest -preset ultrafast

        Es una función BLOQUEANTE reservada al worker; desde código async se
        alcanza únicamente vía la cola (nunca llamarla en el event loop).
        Devuelve la ruta del .mp4 o cadena vacía si hubo que abortar."""
        meta = self._read_meta(job_dir)
        audio_path = meta.get("audio_path") or ""
        if not audio_path or not Path(audio_path).exists():
            self._update_meta(job_dir, status=ST_ERROR,
                              error="audio del job no encontrado")
            return ""
        if shutil.which("ffmpeg") is None:
            self._update_meta(job_dir, status=ST_ERROR,
                              error="ffmpeg no está instalado (sudo apt install ffmpeg)")
            logger.warning("🎞️ ffmpeg ausente → job %s en error", job_dir.name)
            return ""

        bg = self._ensure_background()          # plantilla real o generada
        out_path = job_dir / "reel.mp4"

        self._update_meta(job_dir, status=ST_RENDERING,
                          output_video="", render_started_at=time.time())
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(bg),
            "-i", audio_path,
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            "-preset", "ultrafast",
            str(out_path),
        ]
        t0 = time.time()
        try:
            # subprocess.run dentro del worker: no toca el event loop.
            # stdin devuelto a /dev/null y salida capturada solo en error.
            proc = subprocess.run(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=RENDER_TIMEOUT_S,
            )
            if proc.returncode != 0 or not out_path.exists():
                err = (proc.stderr or "").strip().splitlines()
                self._update_meta(job_dir, status=ST_ERROR,
                                  error=(err[-1] if err else "ffmpeg falló")[:200])
                logger.error("❌ ffmpeg (exit %s): %s", proc.returncode,
                             " ".join(err[-3:]) if err else "")
                return ""
        except subprocess.TimeoutExpired:
            self._update_meta(job_dir, status=ST_ERROR,
                              error=f"render excedió {RENDER_TIMEOUT_S}s")
            return ""

        self._update_meta(job_dir, status=ST_DONE,
                          output_video=str(out_path),
                          render_seconds=round(time.time() - t0, 1))
        logger.info("🎞️ Reel renderizado en %.1fs: %s",
                    time.time() - t0, out_path)
        return str(out_path)

    def _ensure_background(self) -> Path:
        """Devuelve el fondo 9:16: la plantilla del usuario si existe; si no,
        la genera UNA vez con el propio ffmpeg (color plano lavfi → PNG),
        sin Pillow ni assets externos. El usuario puede sustituir
        ~/Documents/cilix-social/templates/reel_bg.png por su diseño."""
        if REEL_BG_TEMPLATE.exists():
            return REEL_BG_TEMPLATE
        if shutil.which("ffmpeg"):
            try:
                proc = subprocess.run(
                    ["ffmpeg", "-y", "-f", "lavfi",
                     "-i", f"color=c={REEL_FALLBACK_COLOR}:s={REEL_SIZE}:d=1",
                     "-frames:v", "1", str(REEL_BG_TEMPLATE)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                if proc.returncode == 0 and REEL_BG_TEMPLATE.exists():
                    logger.info("🖼️ Fondo 9:16 generado (fallback color) → %s",
                                REEL_BG_TEMPLATE)
                    return REEL_BG_TEMPLATE
            except Exception:  # noqa: BLE001
                pass
        # Sin ffmpeg no hay nada que generar: el render ya abortará con error
        # claro en render_reel_background. Devolvemos la ruta igualmente.
        return REEL_BG_TEMPLATE

    # ══ Consultas del panel HITL (estado por archivos, sin IPC) ═══════════
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Lee meta.json de un job (ruta absoluta o nombre de carpeta)."""
        d = Path(job_id if job_id.startswith(str(QUEUE_DIR))
                 else str(QUEUE_DIR / Path(job_id).name))
        meta = self._read_meta(d)
        return meta or None

    def list_jobs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Empleados más recientes primero; útil para el panel HITL."""
        jobs: List[Dict[str, Any]] = []
        try:
            dirs = sorted(QUEUE_DIR.glob("job_*"), reverse=True)[:limit]
        except OSError:
            return jobs
        for d in dirs:
            meta = self._read_meta(d)
            if meta:
                jobs.append(meta)
        return jobs

    # ══ Carpeta de trabajo / meta.json ════════════════════════════════════
    def _create_job(self, pack: SocialPack) -> Path:
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(pack.created))
        job_dir = QUEUE_DIR / f"job_{ts}"
        job_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "job_id": ts,
            "kind": pack.kind,
            "topic": pack.topic,
            "caption": pack.caption,           # caption LIMPIO (hashtags fuera)
            "hashtags": ["#" + h.lstrip("#") for h in pack.hashtags],
            "script": pack.script,
            "audio_path": "",
            "output_video": "",
            "status": ST_AWAIT,
            "created": pack.created,
            "error": "",
        }
        self._write_meta(job_dir, meta)
        return job_dir

    def _ensure_job(self, pack: SocialPack) -> Path:
        """Ruta del job del pack (creándolo si el pack vino sin uno)."""
        if pack.job_id and Path(pack.job_id).is_dir():
            return Path(pack.job_id)
        job_dir = self._create_job(pack)
        pack.job_id = str(job_dir)
        return job_dir

    def _write_meta(self, job_dir: Path, meta: Dict[str, Any]) -> None:
        try:
            (job_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("meta.json %s: %s", job_dir, exc)

    def _read_meta(self, job_dir: Path) -> Dict[str, Any]:
        try:
            return json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _update_meta(self, job_dir: Path, **changes: Any) -> None:
        """Actualización quirúrgica de campos del meta.json (estado, rutas,
        tiempos). El panel HITL solo necesita leer este archivo."""
        meta = self._read_meta(job_dir)
        if not meta:
            return
        meta.update(changes)
        self._write_meta(job_dir, meta)

    def _recover_pending_jobs(self) -> None:
        """Reincio sin pérdidas: jobs 'ready' (audio escrito, sin mp4) que
        quedaron encolados por una caída del backend vuelven a la cola."""
        try:
            dirs = sorted(QUEUE_DIR.glob("job_*"))
        except OSError:
            return
        for d in dirs:
            meta = self._read_meta(d)
            if meta.get("status") == ST_READY and Path(
                    meta.get("audio_path") or "").exists():
                self._enqueue_job(d)
                logger.info("♻️ Job huérfano reencolado: %s", d.name)

    # ══ Ayudantes de borrador ═════════════════════════════════════════════
    @staticmethod
    def _extract_json(raw: str) -> Optional[Dict[str, Any]]:
        """Tolera modelos pequeños que envuelven el JSON en texto extra."""
        m = re.search(r"\{.*\}", raw or "", re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except ValueError:
            return None

    def _save_draft(self, pack: SocialPack, job_dir: Optional[Path]) -> str:
        """Guarda .md legible + .json machine-friendly. Los Reels escriben
        dentro de su job; los posts sueltos, en la raíz de cilix-social."""
        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(pack.created))
        target = job_dir if job_dir else SOCIAL_DIR
        md = target / f"post_{ts}.md"
        js = target / f"post_{ts}.json"
        body = (
            f"# Borrador {pack.kind} · {pack.topic}\n\n"
            f"**Caption**\n\n{pack.caption}\n\n"
            f"**Hashtags**\n\n"
            + " ".join(f"`#{h.lstrip('#')}`" for h in pack.hashtags) + "\n\n"
        )
        if pack.script:
            body += f"**Guion Reel (15 s)**\n\n{pack.script}\n\n"
        if job_dir:
            body += (f"**Job de render**\n\n`{job_dir}` → `reel.mp4` cuando "
                     f"el estado pase a `{ST_DONE}` (consultar `meta.json`).\n\n")
        body += ("\n> Ri prepara, TÚ publicas: revisa, edita si quieres y "
                 "copia/pega en la app de Instagram. 🤍\n")
        md.write_text(body, encoding="utf-8")
        js.write_text(json.dumps(pack.__dict__, ensure_ascii=False, indent=2),
                      encoding="utf-8")
        return str(md)
