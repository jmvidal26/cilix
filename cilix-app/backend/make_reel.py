#!/usr/bin/env python3
"""make_reel · generador de reels 100% aislado (CLI, sin chat ni WebSocket).

Un módulo independiente de SocialEngine: le dices TEMA por argumento y él
hace toda la cadena — guion + caption (qwen2.5:3b residente vía Ollama),
voz (Kokoro/Piper con el AudioEngine ya lazy-load), música opcional y vídeo
vertical 9:16 con ffmpeg en segundo plano — sin tocar main.py ni el frontend.

Uso:
    python make_reel.py "el renderizador local de reels"
    python make_reel.py "modo de aprobaciones de sudo" --musica ~/Música/loop.mp3
    python make_reel.py "post de build-in-public"        --solo-post
    python make_reel.py "estado de RAM"                  --tam 1080x1920 \
                                                    --plantilla ~/pics/fondo.png

Salidas (en ~/Documents/cilix-social/):
  · post_<ts>.md/.json            caption limpio + hashtags (para pegar en IG)
  · queue/job_<ts>/meta.json      estado del trabajo (productor→consumidor)
  · queue/job_<ts>/reel.mp4       resultado final (voz + música si se pasó)

Requisitos: Ollama corriendo (localhost:11434) y ffmpeg instalado.
No necesita que el backend de Cilix esté levantado: reutiliza los módulos
locales como librería.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

# El CLI vive junto a los módulos del backend: importarlos como librería.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core_ia import CoreIA                      # noqa: E402
from audio_engine import AudioEngine            # noqa: E402
from social_engine import (                     # noqa: E402
    QUEUE_DIR, ST_DONE, ST_ERROR, SocialEngine,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s · %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("make_reel")


# ══ Utilidades de consulta / espera sobre meta.json ══════════════════════
def leer_meta(job_dir: Path) -> dict:
    """Lee el meta.json del job (o dict vacío si aún no existe)."""
    try:
        return json.loads((job_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


async def esperar_render(job_dir: Path, timeout: float = 420.0) -> dict:
    """Vigila el job hasta que el worker del SocialEngine lo deje en done o
    error (imprime el estado cada pocos segundos para que el CLI 'cuente'
    la película). Devuelve el meta final."""
    t0 = time.time()
    ultimo = ""
    while time.time() - t0 < timeout:
        meta = leer_meta(job_dir)
        st = meta.get("status", "?")
        if st != ultimo:
            print(f"   · estado del job: {st}")
            ultimo = st
        if st in (ST_DONE, ST_ERROR):
            return meta
        await asyncio.sleep(2)
    return {"status": "timeout", "error": f"el render no terminó en {timeout}s"}


# ══ Extra: música de fondo opcional (mezcla post-render, mismo ffmpeg) ════
def anadir_musica(mp4: Path, musica: str, volumen: float = 0.25) -> Path:
    """Mezcla una pista de fondo al reel YA renderizado, en un paso aparte
    (así no complica el pipeline del engine). -shortest recorta al video y
    `-stream_loop -1` hace loop de la pista si es corta. Salida ligera:
    libx264 ultrafast + aac. Devuelve la ruta del mp4 musical (o original)."""
    if shutil.which("ffmpeg") is None:
        log.warning("ffmpeg ausente → sin música de fondo")
        return mp4
    pista = Path(musica).expanduser()
    if not pista.exists():
        log.warning("pista inexistente: %s → reel sin música", pista)
        return mp4
    out = mp4.parent / (mp4.stem + "_musica.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(mp4),
        "-stream_loop", "-1", "-i", str(pista),
        "-filter:a", f"volume={volumen}",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy",           # vídeo intacto: solo re-mux + audio nuevo
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(out),
    ]
    log.info("🎵 Añadiendo música de fondo (%s, vol %.2f)…", pista.name, volumen)
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, text=True, timeout=300)
    if proc.returncode == 0 and out.exists():
        return out
    log.error("mezcla de música falló: %s", (proc.stderr or "")[-200:])
    return mp4


# ══ Extras de edición (pasada post-render, solo ffmpeg) ══════════════
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def duracion(mp4: Path) -> float:
    """Duración del clip vía ffprobe (para situar el fade-out)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(mp4)],
            capture_output=True, text=True, timeout=15)
        return float(r.stdout.strip() or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def crear_fondo_bonito(dest: Path) -> None:
    """Fondo 9:16 con degradado Cilix + marca de agua, generado SOLO si el
    usuario no puso ya su plantilla en templates/reel_bg.png. Reemplaza al
    aburrido color plano negro-azulado del fallback del engine."""
    if dest.exists() or shutil.which("ffmpeg") is None:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    # OJO: drawtext NO interpreta escapes \uXXXX → el corazón va como carácter
    # UTF-8 literal (DejaVu Sans lo tiene en su glifo U+2665).
    marca = (f"drawtext=fontfile={FONT_BOLD}:text='Cilix ♥ Ri':"
             "fontsize=64:fontcolor=white@0.85:x=(w-text_w)/2:y=h*0.06")
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", ("gradients=s=1080x1920:c0=0x0a121c:c1=0x10355a:c2=0x7b5cff"
               ":x0=120:y0=100:x1=960:y1=1800:d=1"),
        "-vf", marca, "-frames:v", "1", str(dest),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=60)
    if proc.returncode == 0 and dest.exists():
        log.info("🖼️ Fondo Cilix generado con degradado → %s", dest)


def default_avatar() -> str:
    """Avatar por defecto del CLI: el PNG del personaje capturado del frontend
    (con fondo ya chroma-keyteado a transparente). Si no existe, sin overlay."""
    candidatos = [
        Path(__file__).resolve().parent.parent / "assets" / "ri_avatar.png",
        Path.home() / "Documents" / "cilix-social" / "templates" / "avatar.png",
    ]
    for c in candidatos:
        if c.exists() and c.stat().st_size > 1024:  # ignora placeholders de 18B
            return str(c)
    return ""


def editar_reel(mp4: Path, caption: str, hashtags: list,
                avatar: str = "", avatar_grande: bool = True) -> Path:
    """Pasada de EDICIÓN sobre el reel ya renderizado (re-encode barato de un
    stillimage): fundido de entrada/salida, caption de Ri en la zona inferior
    (caja semitransparente, envuelto a mano), hashtags en fila fina arriba y
    avatar opcional superpuesto arriba-derecha si el usuario pasa un PNG.
    Todo con filtros nativos de ffmpeg: cero RAM extra, cero librerías."""
    if shutil.which("ffmpeg") is None:
        return mp4
    out = mp4.parent / "reel_editado.mp4"
    dur = duracion(mp4) or 5.0
    # Texto multilínea por ARCHIVO (textfile) para no pelear con los escapes
    # de drawtext: acentos, comas, comillas… viajan literales.
    import textwrap
    cap_txt = mp4.parent / ".caption.txt"
    tags_txt = mp4.parent / ".hashtags.txt"
    cap_txt.write_text("\n".join(textwrap.wrap(caption, 26)) or "Cilix",
                       encoding="utf-8")
    # Hashtags envueltos a ~32 chars (2-3 líneas): si van en una sola fila el
    # drawtext desborda el ancho 1080 y se corta por los bordes.
    tags_txt.write_text("\n".join(textwrap.wrap(" ".join(hashtags), 32))[:180],
                        encoding="utf-8")
    filtros = [
        "fade=t=in:st=0:d=0.5",
        f"fade=t=out:st={max(dur - 0.5, 0.1):.2f}:d=0.5",
        (f"drawtext=fontfile={FONT_BOLD}:textfile={cap_txt}:"
         "fontsize=52:fontcolor=white:line_spacing=10"
         ":box=1:boxcolor=black@0.45:boxborderw=22"
         ":x=(w-text_w)/2:y=h*0.70"),
        (f"drawtext=fontfile={FONT_REG}:textfile={tags_txt}:"
         "fontsize=28:fontcolor=0x00f5d4@0.9:line_spacing=8"
         ":box=1:boxcolor=black@0.35:boxborderw=12"
         ":x=(w-text_w)/2:y=h*0.90"),
    ]
    inputs = ["-i", str(mp4)]
    vf = ",".join(filtros)
    if avatar and Path(avatar).expanduser().exists():
        av = Path(avatar).expanduser()
        # Composición del personaje: por defecto GRANDE y centrado (es la
        # estrella del reel), terminando justo sobre la caja del caption
        # (y=h*0.70 → 1344 px en 1920). Con --sin-avatar-style pequeño sería
        # un simple picture-in-picture en la esquina superior derecha.
        if avatar_grande:
            # 1190 px ≈ 62% del alto 1920 (ojo: en scale, ih es el alto del
            # propio PNG, no del vídeo → mejor medida absoluta).
            avf = ("[1:v]scale=-2:1190:force_original_aspect_ratio=decrease,"
                   "format=rgba[av];[0:v][av]overlay=(W-w)/2:H*0.70-h")
        else:
            avf = ("[1:v]scale=368:-2:force_original_aspect_ratio=decrease,"
                   "format=rgba[av];[0:v][av]overlay=W-w-60:80")
        cmd = (["ffmpeg", "-y"] + inputs +
               ["-i", str(av),
                "-filter_complex", avf + "," + vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
                "-c:a", "copy", str(out)])
    else:
        cmd = (["ffmpeg", "-y"] + inputs +
               ["-vf", ",".join(filtros),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24",
                "-c:a", "copy", str(out)])
    log.info("✂️ Editando el reel (%.1fs, caption + hashtags%s)…",
             dur, " + avatar" if avatar else "")
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, text=True, timeout=300)
    if proc.returncode == 0 and out.exists():
        cap_txt.unlink(missing_ok=True)
        tags_txt.unlink(missing_ok=True)
        return out
    log.error("edición falló: %s", (proc.stderr or "")[-250:])
    return mp4


# ══ Pipeline principal (aislado) ═════════════════════════════════════════
async def generar(tema: str, solo_post: bool = False,
                  musica: str = "", plantilla: str = "",
                  avatar: str = "", editar: bool = True) -> int:
    """Cadena completa: guion+caption → voz → render → (música). Devuelve 0
    si el reel/post quedó DONE. Usa los módulos existentes sin reescribir
    NADA: CoreIA.complete (temp 0.1-free, residente), AudioEngine (lazy),
    SocialEngine (productor-consumidor con jobs por archivos)."""
    # 0) Dependencias externas, chequeadas sin cargar nada.
    import httpx
    try:
        httpx.get("http://localhost:11434/api/tags", timeout=5).raise_for_status()
    except Exception:  # noqa: BLE001
        log.error("Ollama no responde en localhost:11434 (arranca con: ollama serve)")
        return 2
    if shutil.which("ffmpeg") is None:
        log.error("ffmpeg no está instalado (sudo apt install ffmpeg)")
        return 2

    # 1) Cerebro + voz + engine (todo lazy: Piper/Kokoro se cargan al hablar).
    ai = CoreIA()
    await ai.initialize()
    audio = AudioEngine()
    await audio.initialize()
    eng = SocialEngine(ai, get_audio=lambda: audio)

    # 1b) Fondo: si el usuario trae plantilla propia, se instala en la ruta
    #     canónica del engine; si no, se crea un fondo Cilix con degradado
    #     (solo cuando no existe ya ninguno) para evitar el negro plano.
    if plantilla:
        p = Path(plantilla).expanduser()
        if p.exists() and plantilla_kind_ok(p):
            dest = eng_bg_path()
            shutil.copy(p, dest)
            log.info("🖼️ plantilla de fondo: %s", dest)
        elif p.exists():
            log.warning("plantilla %s no es png/jpg → se ignora", p)
    else:
        await asyncio.to_thread(crear_fondo_bonito, eng_bg_path())

    # 2) Productor: guion + caption + hashtags (el 3B redacta; meta del job).
    kind = "post" if solo_post else "reel"
    print(f"🧠 Ri redactando el {kind} sobre «{tema}»… (30-90 s en CPU)")
    pack = await eng.prepare(kind, tema)
    if pack is None:
        log.error("el modelo no devolvió un pack válido — reintenta el tema")
        await cleanup(ai, audio)
        return 3
    print("✅ Caption:", pack.caption)
    print("   Hashtags:", " ".join("#" + h for h in pack.hashtags[:10]))
    if solo_post:
        print("📁 Borrador:", pack.draft_path)
        await cleanup(ai, audio)
        return 0

    # 3) Voz de Ri sobre el guion del reel (TTS lazy → wav dentro del job).
    print(f"🎙️ Guion ({len(pack.script)} car.): {pack.script}")
    print("🔊 Sintetizando la voz… (Kokoro/Piper se cargan ahora)")
    wav = await eng.reel_voice(pack)
    if not wav:
        log.error("no hubo voz (motor de audio no disponible o texto vacío)")
        await cleanup(ai, audio)
        return 4

    # 4) El worker de ffmpeg toma la antorcha (cola por archivos, sin bloquear).
    job_dir = Path(pack.job_id)
    print(f"🎞️ Render 9:16 en cola: {job_dir.name}")
    meta = await esperar_render(job_dir)
    if meta.get("status") != ST_DONE:
        log.error("render no completado: %s (%s)",
                  meta.get("status"), meta.get("error", ""))
        await cleanup(ai, audio)
        return 5

    # 5) Resultado + EDICIÓN (textos/fades/avatar) + música opcional.
    #    Orden: editar re-encodea el vídeo (copia el audio); la música se
    #    mezcla al final para que suene sobre la versión editada.
    final = Path(meta["output_video"])
    if editar:
        av = avatar or default_avatar()   # ← Ri centrada por defecto
        final = await asyncio.to_thread(
            editar_reel, final, pack.caption, pack.hashtags, av)
    if musica:
        final = await asyncio.to_thread(anadir_musica, final, musica)
    if str(final) != meta["output_video"]:
        await asyncio.to_thread(actualizar_meta, job_dir, final_video=str(final))
    print("════════════════════════════════════════")
    print(f"🎬 Reel listo: {final}  ({final.stat().st_size // 1024} KB)")
    print(f"📁 Job (todo el rastro): {job_dir}")
    print("════════════════════════════════════════")

    # 6) Libera RAM (Ri se queda residente por Ollama; el TTS se descarga).
    await cleanup(ai, audio)
    return 0


def plantilla_kind_ok(p: Path) -> bool:
    """Acepta solo imágenes de fondo (png/jpg) — ffmpeg las come sin re-encode."""
    return p.suffix.lower() in (".png", ".jpg", ".jpeg")


def eng_bg_path() -> Path:
    """Ruta canónica donde SocialEngine busca la plantilla (misma convención)."""
    from social_engine import REEL_BG_TEMPLATE
    REEL_BG_TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    return REEL_BG_TEMPLATE


def actualizar_meta(job_dir: Path, **cambios) -> None:
    """Extensión del meta.json con el CLI (final_video). Mismo contrato por
    archivos que ya usa el panel HITL; no require tocar el engine."""
    meta = leer_meta(job_dir)
    if not meta:
        return
    meta.update(cambios)
    (job_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


async def cleanup(ai: CoreIA, audio: AudioEngine) -> None:
    """Apagado limpio de los motores locales cargados por este CLI."""
    try:
        audio.cleanup()
    except Exception:  # noqa: BLE001
        pass
    try:
        await ai.cleanup()
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Genera caption + guion + voz + reel 9:16 (todo local).")
    ap.add_argument("tema", help="de qué trata el reel/post")
    ap.add_argument("--solo-post", action="store_true",
                    help="solo caption + hashtags, sin vídeo ni voz")
    ap.add_argument("--musica", default="", metavar="ARCHIVO",
                    help="pista de fondo mp3/ogg (mezcla al reel ya renderizado)")
    ap.add_argument("--plantilla", default="", metavar="IMAGEN",
                    help="fondo vertical propio (png/jpg 9:16)")
    ap.add_argument("--avatar", default="", metavar="IMAGEN",
                    help="png del personaje (por defecto usa assets/ri_avatar.png)")
    ap.add_argument("--sin-avatar", action="store_true",
                    help="no superponer al personaje en la edición")
    ap.add_argument("--sin-edicion", action="store_true",
                    help="no aplicar textos/fades/avatar al reel")
    args = ap.parse_args()
    avatar_arg = "" if args.sin_avatar else args.avatar

    try:
        return asyncio.run(generar(args.tema, args.solo_post,
                                   args.musica, args.plantilla,
                                   avatar_arg, not args.sin_edicion))
    except KeyboardInterrupt:
        print("\n⏹ cancelado")
        return 130


if __name__ == "__main__":
    sys.exit(main())
