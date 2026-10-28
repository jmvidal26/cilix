#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  Cilix v2.0 · Lanzador integral (Pop!_OS / Linux)
#  Prepara el entorno local, verifica recursos y arranca la aplicación.
#  Uso:
#     ./run.sh            → modo navegador (BAJO en RAM: backend + tu navegador)
#     ./run.sh --browser  → igual que el predeterminado
#     ./run.sh --app      → Electron (overlay transparente siempre arriba)
#     ./run.sh --backend  → solo el servidor Python (sin abrir navegador)
#     ./run.sh --dev      → modo desarrollo Electron (recarga + DevTools)
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv"
PY="$VENV/bin/python"
MODE="${1:-browser}"
PORT="${CILIX_PORT:-8765}"
URL="http://127.0.0.1:${PORT}"

echo "🎀 ── Cilix · Asistente de escritorio local ──"

# ── 1) Entorno virtual Python ──────────────────────────────────────────────
if [[ ! -x "$PY" ]]; then
  echo "🐍 Creando entorno virtual (.venv)…"
  python3 -m venv "$VENV"
fi

echo "📦 Comprobando dependencias Python…"
# Instala solo si `requirements.txt` cambió (antes hacía pip install en CADA
# arranque: varios segundos y tráfico de red innecesario).
REQ_HASH="$(sha256sum requirements.txt | awk '{print $1}')"
REQ_STAMP="$VENV/.requirements.sha256"
if [[ ! -f "$REQ_STAMP" || "$(cat "$REQ_STAMP")" != "$REQ_HASH" ]]; then
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -r requirements.txt
  printf '%s' "$REQ_HASH" > "$REQ_STAMP"
else
  echo "   ✔ Dependencias al día"
fi

# ── 2) Variables de entorno ────────────────────────────────────────────────
[[ -f .env ]] || { cp .env.example .env && echo "📝 Creado .env desde el ejemplo"; }

# ── 3) Comprobaciones del sistema ──────────────────────────────────────────
echo "🔎 Verificando requisitos locales…"

# 3a) Ollama en 11434
if command -v ollama >/dev/null 2>&1; then
  if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "🡮   Ollama instalado pero no en ejecución → arrancando 'ollama serve'…"
    # KV cache en q8 + flash attention: cuantiza la memoria de atención si hay
    # GPU; en CPU solo no aplica (no rompe nada) y num_ctx=1024 del backend ya
    # mantiene la KV pequeña de todos modos.
    OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 \
    nohup ollama serve >/tmp/cilix_ollama.log 2>&1 &
    sleep 3
  fi
  echo "🧠   Ollama OK"
else
  echo "⚠️   Ollama NO está instalado. Instala y descarga los modelos:"
  echo "       curl -fsSL https://ollama.com/install.sh | sh"
  echo "       ollama pull qwen2.5:1.5b        # Ri"
  echo "       ollama pull deepseek-coder:1.3b  # Re"
fi

# 3b) Utilidades de percepción de ventana (Linux)
for tool in xdotool wmctrl; do
  command -v "$tool" >/dev/null 2>&1 || echo "ℹ️   Falta '$tool' (opcional para ventana activa): sudo apt install xdotool wmctrl"
done

# 3c) RAM disponible (aviso del límite de 8 GB)
AVAIL_KB=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
echo "💾   RAM disponible: $((AVAIL_KB/1024)) MB"

# ── 4) Arranque ────────────────────────────────────────────────────────────
start_backend_bg() {
  # Lanza el backend Python en segundo plano y devuelve su PID.
  # `exec` garantiza que el PID sea el de Python (no el de una subshell), así
  # el trap de salida lo mata de verdad.
  (cd "$SCRIPT_DIR/backend" && exec "$PY" main.py "$@") &
  BACKEND_PID=$!
}

# Si ya hay una instancia viva, no se arranca otra (chocarían por el puerto).
ALREADY_RUNNING=0
if curl -s "$URL/health" >/dev/null 2>&1; then
  ALREADY_RUNNING=1
fi

case "$MODE" in
  --backend|backend)
    echo "🚀 Backend en ${URL} (Ctrl+C para detener)"
    (cd backend && exec "$PY" main.py "${@:2}")
    ;;
  --browser|browser|"")
    if [[ "$ALREADY_RUNNING" == "1" ]]; then
      echo "ℹ️   Cilix ya está corriendo en $URL"
      xdg-open "$URL" >/dev/null 2>&1 || true
      exit 0
    fi
    echo "🌐 Modo navegador (bajo en RAM, sin Electron)…"
    start_backend_bg
    trap 'kill ${BACKEND_PID:-0} 2>/dev/null || true' EXIT INT TERM
    # Espera a que el backend responda (hasta ~30 s).
    for _ in $(seq 1 60); do
      curl -s "$URL/health" >/dev/null 2>&1 && break
      sleep 0.5
    done
    echo "   Cilix disponible en $URL"
    xdg-open "$URL" >/dev/null 2>&1 || echo "   Ábrelo a mano en tu navegador: $URL"
    wait "${BACKEND_PID:-}"
    ;;
  --dev|dev)
    echo "🛠️  Modo desarrollo…"
    start_backend_bg --dev
    trap 'kill ${BACKEND_PID:-0} 2>/dev/null || true' EXIT INT TERM
    npx --yes electron . --dev
    ;;
  --app|app|--electron|electron)
    # Asegura dependencias de Node/Electron
    if [[ ! -d node_modules/electron ]]; then
      echo "🧩 Instalando Electron (npm install)…"
      npm install
    fi
    echo "🚀 Lanzando Cilix (Electron + backend)…"
    # Electron arranca su propio backend; si ya había uno, se reutiliza.
    if [[ "$ALREADY_RUNNING" == "1" ]]; then
      echo "ℹ️   Reutilizando el backend que ya corre en $URL"
      CILIX_NO_BACKEND=1 npm start
    else
      npm start
    fi
    ;;
esac
