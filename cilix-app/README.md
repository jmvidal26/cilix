# Cilix · Registro de mejoras (v2.0)

Este documento resume **las mejoras realizadas** sobre Cilix, el asistente de
escritorio tipo VTuber 100 % local/offline (FastAPI + WebSocket + Electron +
Live2D). Todo se ejecuta en máquina con un **límite estricto de 8 GB de RAM**
y sin enviar nada a la nube. Los comentarios de código están en español.

---

## 1. Voz femenina natural (Kokoro) 🎙️

**Problema:** la voz de Piper (`es_ES-davefx`) sonaba masculina y las voces
femeninas de Piper en español prácticamente no existen.

**Mejora:**
- Se adoptó **Kokoro TTS** como motor principal con la voz femenina en español
  **`ef_dora`** (24 kHz, mucho más natural).
- Descarga del par compatible público `fastrtc/kokoro-onnx`
  (`kokoro-v1.0.onnx` ≈325 MB + `voices-v1.0.bin` ≈28 MB) en `models/kokoro/`.
- **Carga diferida (lazy)** para no consumir RAM hasta que se habla.
- Compatibilidad con `numpy>=2` mediante un *monkeypatch* de `allow_pickle`.
- Piper queda como **respaldo** automático si Kokoro no está disponible.

**Config:** `CILIX_TTS_BACKEND=kokoro`, `CILIX_KOKORO_VOICE=ef_dora`.

---

## 2. Arquitectura de baja RAM (cerebro único) 🧠

**Problema:** el modo "Cerebro Dual" (Ri + Re) mantenía dos modelos de Ollama
en memoria (~2 GB). El cuello de RAM **no era Python** (~60–100 MB), sino los
modelos de Ollama, Electron y Kokoro. Se descartó reescribir Python a C/Rust.

**Mejora:**
- Flag **`dual_brain`** (por defecto `false`): con un solo cerebro, **Re nunca
  se carga** → ahorra ~1 GB.
- `ri_keep_alive` bajado de `5m` → `2m` (libera RAM antes).
- `main.py` (`_handle_switch_mode`): sin modo dual, siempre devuelve **Ri**.
- **Lanzador prioriza el navegador**: `./run.sh` arranca el backend en segundo
  plano y abre `http://127.0.0.1:8765` (sin Electron). Electron queda opt-in
  con `./run.sh --app`.
- El modo dual sigue disponible activando `CILIX_DUAL_BRAIN=true`.

---

## 3. Voz más rápida ⚡

**Mejora:**
- `kokoro_speed` subido de `1.0` → **`1.15`** (habla ~15 % más ágil).
- **Warm-up en segundo plano** (`voice_warmup`, activo por defecto): precarga
  Kokoro ~2 s después de arrancar para que la *primera* frase no tenga retardo.
- **Guardia de RAM** en el warm-up: si la máquina está muy cargada
  (≥ `ram_critical_percent`), se omite la precarga y se carga bajo demanda para
  no superar los 8 GB.

**Config:** `CILIX_KOKORO_SPEED=1.15`, `CILIX_VOICE_WARMUP=true`.

---

## 4. Lip-sync mejorado 👄

**Mejora en el envelope de volumen (`audio_engine.py`):**
- Curva **gamma `0.75`** + **ganancia `5.0`** + **suavizado 25/50/25**
  (media móvil). La boca abre más en voces suaves y con transiciones naturales.

**Mejora en el pilotado de boca (`live2d.js`):**
- **Ataque rápido (0.5) / cierre lento (0.3)** y curva `pow(boca, 0.8)`
  → sensación más viva, menos robótica.

---

## 5. Avatar menos "plano" (más animación) 🕺

**Problema:** el modelo `design_genius_white` solo tenía una animación idle que
movía los parámetros de lágrimas → el avatar se veía **congelado**.

**Mejora — nuevo bucle idle en `live2d.js`:**
- **Parpadeo** aleatorio cada 2.6–6.8 s (usa `ParamEyeLOpen`/`ParamEyeROpen`,
  verificados en el modelo).
- **Respiración** (subida/bajada sutil) + **balanceo de cabeza**.
- **Seguimiento de mirada/cabeza al cursor** (eye-tracking + parallax).
- **Bob al hablar**: el avatar se mueve mientras pronuncia.
- **Micro-flutter de cejas** para que nunca esté del todo quieto.
- El **arrastre** respeta `_homeX`/`_homeY`, así el idle nunca "pelea" con la
  posición fijada por el usuario.

---

## 6. Personalidad del prompt de Ri 💬

**Mejora en `core_ia.py`:**
- Prompt de Ri reescrito: compañera VTuber **cálida, curiosa y juguetona**, con
  emojis moderados, frases cortas y vivas, opiniones y matices emocionales, y
  humor al admitir que no sabe algo. Evita listas largas.
- **Fallback de emoción:** si la respuesta sale `neutral`, hereda la emoción
  detectada en el mensaje del usuario → el avatar reacciona con más expresión.

> El modelo de Ri se mantiene en `qwen2.5:1.5b` (mejor equilibrio RAM/calidad).
> Opción para ahorrar ~600 MB más: `CILIX_RI_MODEL=llama3.2:1b`.

---

## 7. UI de la página (modo navegador) 🎨

**Mejora en `styles.css` + `app.js`:**
- En **modo navegador** (sin `window.cilix`) se añade la clase `browser` al
  `<html>` con:
  - Fondo oscuro con **aurora animada** + **viñeta**.
  - Paneles más anchos, chat/composer con **glow al enfocar**.
  - Texto de marca con **degradado**.
- En **Electron** se conserva el overlay **transparente** intacto.
- En modo navegador se ocultan los controles de ventana (pin/min/close) que
  solo tienen sentido en Electron.

---

## Cómo arrancar

```bash
cd /home/jesvid/Downloads/cilix/cilix-app

# Antes de arrancar, limpia backends huérfanos en el puerto 8765:
pkill -f backend/main.py

./run.sh            # modo navegador (bajo en RAM, sin Electron)  [recomendado]
./run.sh --app      # Electron (overlay transparente siempre arriba)
./run.sh --backend  # solo el servidor Python
```

La primera frase puede tardar algo más si la RAM ambiental es alta (IDE,
navegador...), porque el warm-up se salta por la guardia de RAM y Kokoro se
carga bajo demanda. Con menos programas abiertos, la voz responde más rápido.

---

## Verificación

- `node --check live2d.js` / `app.js` → OK
- `py_compile` de los módulos backend → OK
- Defaults confirmados: `kokoro_speed=1.15`, `voice_warmup=True`
- Smoke test WebSocket: `mode: Ri | emotion: feliz` (fallback OK),
  `speak dur:2.11s frames:53 max:0.716` (lip-sync poblando correctamente)

---

## Configuración relevante (`.env`)

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `CILIX_DUAL_BRAIN` | `false` | Un solo cerebro (Re no se carga, ahorra ~1 GB) |
| `CILIX_RI_MODEL` | `qwen2.5:1.5b` | Cerebro residente |
| `CILIX_RI_KEEP_ALIVE` | `2m` | Tiempo que Ri permanece en RAM |
| `CILIX_TTS_BACKEND` | `kokoro` | Motor de voz (Kokoro femenino) |
| `CILIX_KOKORO_VOICE` | `ef_dora` | Voz femenina en español |
| `CILIX_KOKORO_SPEED` | `1.15` | >1 = habla más rápido |
| `CILIX_VOICE_WARMUP` | `true` | Precarga de voz (con guardia de RAM) |
| `CILIX_RAM_CRITICAL` | `88` | % de RAM que desactiva el warm-up |
