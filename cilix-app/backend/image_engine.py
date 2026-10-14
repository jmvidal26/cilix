#!/usr/bin/env python3
"""image_engine · generador de imágenes 100% local y aislado (CLI).

Dos niveles, pensados para la caja de 8 GB sin GPU ni APIs de pago:

  · modo CARTEL (por defecto): póster/imagen social PROCEDURAL dibujado con
    filtros nativos de ffmpeg — degradado Cilix, avatar de Ri (si existe),
    título envuelto y partículas. Instantáneo, cero dependencias nuevas y
    cero RAM residente. Ideal para portadas de reels y posts.

  · modo IA: imagen GENERADA con Stable-Diffusion-turbo (2 pasos de
    deducción) en CPU. Tarda ~1-2 min y pico de ~3-4 GB de RAM, por lo que
    el módulo (a) exige RAM libre suficiente, (b) DESCARGA a Ri de Ollama
    antes de generar (keep_alive=0) y (c) avisa que la próxima respuesta del
    chat recargará el modelo. Sin torch/diffusers instalados, imprime las
    instrucciones de instalación y no descarga nada a espaldas del usuario.

Uso:
    python image_engine.py "portada del video inicial de Cilix"
    python image_engine.py " Ri y su avatar" --titulo "CILIX ya corre en 8GB"
    python image_engine.py "robot zorro neon" --modo ia --tam 768
    python image_engine.py "fondo galaxia" --modo cartel --cuadrado

Salidas: ~/Documents/cilix-social/images/<slug>_<ts>.png
Requisitos: ffmpeg (ambos modos) · Ollama + torch + diffusers (solo modo ia).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s · %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("image_engine")

# Rutas compartidas con el ecosistema Cilix (misma convención que social_engine
# y make_reel: todo por ARCHIVOS, sin IPC ni acoplamiento de código).
SOCIAL_DIR = Path.home() / "Documents" / "cilix-social"
IMAGES_DIR = SOCIAL_DIR / "images"
TEMPLATES_DIR = SOCIAL_DIR / "templates"
REEL_BG = TEMPLATES_DIR / "reel_bg.png"          # fondo Cilix reutilizable
AVATAR_CANDIDATES = [                            # personaje, si lo hay
    Path(__file__).resolve().parent.parent / "assets" / "ri_avatar.png",
    TEMPLATES_DIR / "avatar.png",
]
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
RAM_MIN_LIBRE_GB_IA = 3.5                        # umbral honesto para SD-turbo


# ══ Helpers ══════════════════════════════════════════════════════════════
def slug(texto: str, maximo: int = 28) -> str:
    """'¡Hola, Cilix!' → 'hola-cilix' para nombres de archivo limpios."""
    s = re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")
    return (s[:maximo].rstrip("-")) or "imagen"


def libre_ram_gb() -> float:
    """GB de RAM disponibles según `free` (columna available)."""
    try:
        out = subprocess.run(["free", "-b"], capture_output=True, text=True)
        for linea in out.stdout.splitlines():
            if linea.startswith("Mem:"):
                return int(linea.split()[-1]) / 1e9
    except Exception:  # noqa: BLE001
        pass
    return 99.0  # si no podemos medir, no bloquear


def buscar_avatar() -> Path | None:
    for c in AVATAR_CANDIDATES:
        if c.exists() and c.stat().st_size > 1024:
            return c
    return None


def ff(cmd: list[str], que: str) -> Path | None:
    """Ejecuta ffmpeg en silencio; devuelve la salida o None con el error."""
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, text=True, timeout=180)
    if proc.returncode != 0:
        log.error("%s falló: %s", que, (proc.stderr or "")[-300:])
        return None
    return cmd[-1] and Path(cmd[-1])


# ══ MODO CARTEL · póster procedural con ffmpeg puro ══════════════════════
def generar_cartel(titulo: str, salida: Path, tam: str = "1080x1920",
                   con_avatar: bool = True) -> Path | None:
    """Compón un cartel social sin IA: degradado de marca Cilix + título
    envuelto en caja + hashtags/partículas + avatar opcional. Cada capa es
    un filtro nativo de ffmpeg (gradients/drawtext/drawbox/overlay): coste
    ~1 s de CPU y nada de RAM persistente."""
    if shutil.which("ffmpeg") is None:
        log.error("ffmpeg no está instalado")
        return None
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    w, h = (int(v) for v in tam.split("x"))

    # 1) Lienzo: degradado de marca (mismo lenguaje visual que los reels).
    lienzo = (f"gradients=s={w}x{h}:c0=0x0a121c:c1=0x10355a:c2=0x7b5cff"
              f":x0={w//9}:y0={h//19}:x1={w*8//9}:y1={h*15//16}")

    # 2) Partículas: puntitos cian/blancos pseudoaleatorios (semilla fija del
    #    título → el mismo tema produce siempre el mismo cartel, reproducible).
    import random
    rng = random.Random(hash(titulo) & 0xFFFF)
    puntos = []
    for _ in range(26):
        x, y = rng.randint(0, w - 8), rng.randint(0, h - 8)
        col = "0x00f5d4" if rng.random() < 0.6 else "white"
        al = rng.choice(["0.35", "0.6", "0.85"])
        tam_pt = rng.choice([4, 6, 8])
        puntos.append(f"drawbox=x={x}:y={y}:w={tam_pt}:h={tam_pt}"
                      f":color={col}@{al}:t=fill")

    # 3) Título en caja, envuelto a ~16 caracteres (fuente grande vertical).
    txt = IMAGES_DIR / f".{salida.stem}.titulo.txt"
    txt.write_text("\n".join(textwrap.wrap(titulo, 16)) or "Cilix",
                   encoding="utf-8")
    titulo_f = (f"drawtext=fontfile={FONT_BOLD}:textfile={txt}:"
                f"fontsize={max(w // 12, 40)}:fontcolor=white:line_spacing=14"
                ":box=1:boxcolor=black@0.45:boxborderw=26"
                f":x=(w-text_w)/2:y=h*0.62-text_h")

    vf_base = ",".join(puntos + [titulo_f])
    # 4) Composición en dos pasadas (robusta y fácil de depurar):
    #    pasada 1 → lienzo degradado + partículas + título;
    #    pasada 2 → overlay del avatar de Ri (si existe y se permite).
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", lienzo,
           "-vf", vf_base, "-frames:v", "1", str(salida)]
    res = ff(cmd, "cartel (base)")
    txt.unlink(missing_ok=True)
    if res is None:
        return None
    av = buscar_avatar() if con_avatar else None
    if av:
        av_h = int(h * 0.42)
        tmp = salida.with_suffix(".base.png")
        cmd2 = ["ffmpeg", "-y", "-i", str(salida), "-i", str(av),
                "-filter_complex",
                f"[1:v]scale=-2:{av_h}[av];[0:v][av]overlay=(W-w)/2:H*0.62-h-40",
                "-frames:v", "1", str(tmp)]
        if ff(cmd2, "avatar sobre cartel") and tmp.exists():
            tmp.replace(salida)
        else:
            tmp.unlink(missing_ok=True)
            log.info("avatar no composable → cartel sin personaje")
    return salida


# ══ MODO IA · Stable-Diffusion-turbo en CPU (opt-in) ═════════════════════
def _descargar_ollama() -> None:
    """Vacía los modelos de Ollama de RAM (keep_alive=0) para dejar sitio a
    SD-turbo. Ri se recarga sola en su siguiente uso (lazy)."""
    import httpx
    try:
        nombres = [m["name"] for m in
                   httpx.get("http://localhost:11434/api/tags",
                             timeout=5).json().get("models", [])]
        for n in nombres:
            httpx.post("http://localhost:11434/api/generate",
                       json={"model": n, "keep_alive": 0}, timeout=10)
        log.info("🧹 Ollama descargado de RAM (%d modelos liberados)",
                 len(nombres))
    except Exception as e:  # noqa: BLE001
        log.warning("no se pudo descargar Ollama (¿apagado?): %s", e)


def generar_ia(prompt: str, salida: Path, tam: int = 512) -> Path | None:
    """Genera con sd-turbo (2 pasos, guidance 0.0 → sin classifier-free, el
    truco que lo hace viable en CPU). fp32 + offload: prioriza RAM sobre
    velocidad. Solo se llama con la luz verde de RAM del CLI."""
    try:
        import torch                      # noqa: F401
        from diffusers import StableDiffusionTurboPipeline
    except ImportError:
        log.error(
            "Faltan librerías para el modo IA. Instalar con:\n"
            "  ../.venv/bin/pip install --no-cache-dir torch "
            "--index-url https://download.pytorch.org/whl/cpu\n"
            "  ../.venv/bin/pip install --no-cache-dir diffusers transformers "
            "accelerate\n(y ~3 GB de descarga del modelo sd-turbo la primera "
            "vez)")
        return None

    libre = libre_ram_gb()
    if libre < RAM_MIN_LIBRE_GB_IA:
        log.error("RAM libre %.1f GB < %.1f GB necesarios para SD-turbo. "
                  "Cierra cosas o usa --modo cartel.",
                  libre, RAM_MIN_LIBRE_GB_IA)
        return None

    log.info("🧠 Modo IA: liberando RAM (Ollama fuera)…")
    _descargar_ollama()

    t0 = time.time()
    log.info("Cargando sd-turbo (primera vez descarga ~3 GB)…")
    pipe = StableDiffusionTurboPipeline.from_pretrained(
        "stabilityai/sd-turbo", torch_dtype=torch.float32,
        use_safetensors=True)
    pipe.enable_sequential_cpu_offload(device="cpu")  # trocea el pipeline:
    # pica RAM a ~2.5 GB a cambio de algo más de tiempo. Vital en 8 GB.
    log.info("🎨 Generando (%dx%d, 2 pasos)… puede tardar 1-3 min", tam, tam)
    img = pipe(prompt=prompt, num_inference_steps=2,
               guidance_scale=0.0, height=tam, width=tam).images[0]
    salida.parent.mkdir(parents=True, exist_ok=True)
    img.save(salida)
    log.info("✅ Imagen IA en %.0fs: %s", time.time() - t0, salida)
    log.info("ℹ️  Ri recargará su modelo sola en el próximo chat.")
    return salida if salida.exists() else None


# ══ CLI ══════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Imagen local para redes: cartel ffmpeg (instantáneo) "
                    "o IA sd-turbo (lenta pero generativa).")
    ap.add_argument("tema", help="describe la imagen (el cartel lo usa como "
                                 "título; el modo IA como prompt)")
    ap.add_argument("--titulo", default="",
                    help="texto grande del cartel (por defecto = tema)")
    ap.add_argument("--modo", choices=("cartel", "ia"), default="cartel")
    ap.add_argument("--tam", default="",
                    help="cartel: ANCHOxALTO (def. 1080x1920) · ia: lado px "
                         "(def. 512, máx. recomendado 640)")
    ap.add_argument("--sin-avatar", action="store_true",
                    help="no poner a Ri en el cartel")
    ap.add_argument("--salida", default="", metavar="RUTA",
                    help="ruta de destino del png")
    args = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        print("necesita ffmpeg (sudo apt install ffmpeg)")
        return 2

    ts = time.strftime("%Y%m%d_%H%M%S")
    if args.salida:
        salida = Path(args.salida).expanduser()
    else:
        salida = IMAGES_DIR / f"{slug(args.tema)}_{ts}.png"

    if args.modo == "cartel":
        tam = args.tam or "1080x1920"
        if not re.fullmatch(r"\d{3,4}x\d{3,4}", tam):
            print("tamaño inválido (usa p.ej. 1080x1920 o 1080x1080)")
            return 2
        res = generar_cartel(args.titulo or args.tema, salida, tam,
                             con_avatar=not args.sin_avatar)
    else:
        lado = int(args.tam or 512)
        res = generar_ia(args.tema, salida, min(lado, 640))

    if res is None:
        return 1
    print(f"🖼️  Lista: {res}  ({Path(res).stat().st_size // 1024} KB)")
    print("   (sírvela como --plantilla de make_reel o súbela directo a IG)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
