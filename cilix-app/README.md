# Cilix · Registro de mejoras (v2.1)

Este documento resume **las mejoras realizadas** sobre Cilix, el asistente de
escritorio tipo VTuber 100 % local/offline (FastAPI + WebSocket + Electron +
Live2D). Todo se ejecuta en máquina con un **límite estricto de 8 GB de RAM**
y sin enviar nada a la nube. Los comentarios de código están en español.

---

## 0. Revisión v2.1 · seguridad, bugs y tests 🛡️

**Seguridad (lo más importante):**
- **WebSocket con validación de `Origin`**: antes cualquier página web abierta
  en el navegador podía conectar a `ws://127.0.0.1:8765` y enviar `command`.
  Ahora solo se aceptan orígenes de `localhost`/`127.0.0.1`/`::1` (o clientes
  sin `Origin`, como scripts locales). Ver `backend/security.py`.
- **CORS restringido** a la propia interfaz local (antes `allow_origins=["*"]`
  con credenciales).
- **Fin de la inyección de shell**: la lista blanca solo miraba el primer
  token, así que `ls; touch /tmp/x` pasaba como "seguro". Ahora se rechazan
  `;`, `&&`, `||`, `&`, saltos de línea, backticks, `$(…)` y redirecciones
  fuera de comillas; las tuberías solo se permiten entre comandos SAFE
  (`lspci | grep VGA` sigue funcionando).
- **Abrir carpeta social sin shell**: la ruta del cliente se confina a
  `~/Documents/cilix-social` y se abre con `xdg-open` vía `exec` (no shell).
- **Rutas permitidas por frontera real** (`commonpath`): antes
  `/home/usuario2` colaba como si estuviera dentro de `/home/usuario`.

- **Sudo auditado de verdad**: al reescribir `sudo` como `sudo -n`, la
  auditoría confundía `-n` con el comando; `sudo rm /etc/passwd` pasaba.
  Ahora se saltan los flags de sudo y se audita el comando real.
- **WebSocket/API con validación de `Origin`** y middleware que rechaza
  escrituras HTTP con origen externo (CORS no basta: no bloquea el envío).

**Bugs corregidos:**
- El pulido de voz **destruía el código** (quitaba backticks y `**negritas**`
  de los bloques ```…```). Ahora los bloques se preservan literalmente y el
  límite de frases/caracteres se amplía en respuestas técnicas.
- `rm` dentro de `~/…` **nunca llegaba a la papelera**: `/home` estaba
  protegido como prefijo. Ahora solo protege exactamente `/home` (y `~`), y
  `~/proyecto/viejo` se desvía a `gio trash`.
- El detector de emociones marcaba **triste** con palabras como «normal»
  (porque `mal` casaba dentro de `normal`). Ahora usa frontera de palabra.
- «Un solo emoji» no funcionaba con ráfagas (`😄😄😄` contaba como uno).
- La tarea de precarga de voz no se cancelaba al apagar el servidor.

**Calidad / DX:**
- **31 tests** con `unittest` (sin dependencias nuevas): comandos peligrosos,
  sudo, orígenes, rutas, voz/código, emociones y memoria SQLite.
- `run.sh` ya **no reinstala pip en cada arranque** (solo si cambia
  `requirements.txt`), detecta una instancia viva y mata bien el backend en
  modo `--dev` (`exec` + trap).
- Documentado el **modo ONLINE opcional** (OpenCode local) en `.env.example`.

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
- `kokoro_speed` subido de `1.0` → **`1.25`** (habla ~15 % más ágil).
- **Warm-up en segundo plano** (`voice_warmup`, activo por defecto): precarga
  Kokoro ~2 s después de arrancar para que la *primera* frase no tenga retardo.
- **Guardia de RAM** en el warm-up: si la máquina está muy cargada
  (≥ `ram_critical_percent`), se omite la precarga y se carga bajo demanda para
  no superar los 8 GB.

**Config:** `CILIX_KOKORO_SPEED=1.25`, `CILIX_VOICE_WARMUP=true`.

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

## Integración con OpenCode / MCP (opcional) 🔌

Cilix puede usarse como **cuerpo** de un agente (OpenCode, Claude Desktop…):
el agente llama herramientas por MCP y Cilix habla, gesticula o recuerda.

```bash
# 1) Arranca Cilix (backend en 8765)
./run.sh --backend

# 2) Registra el servidor MCP en OpenCode (una vez)
opencode mcp add cilix --global -- \
  "$PWD/.venv/bin/python" "$PWD/backend/mcp_server.py"
```

Herramientas expuestas: `cilix_say`, `cilix_emotion`, `cilix_ask`,
`cilix_state`, `cilix_remember`, `cilix_history`, `cilix_curiosity`,
`cilix_code`, `cilix_coder_status` y `edith`.
Por dentro usan la API REST local (`/api/say`, `/api/emotion`, `/api/ask`,
`/api/state`, `/api/remember`), que rechaza peticiones con `Origin` externo.

---

## Programar con Antigravity / Qoder 🧑‍💻

Cilix puede delegar una tarea de código a un agente externo **sin cargarlo en
su proceso**: lanza `agy -p` (Antigravity CLI) o `qoder -p` (Qoder CLI) como
subproceso, en el directorio del proyecto, y te cuenta el resultado. En reposo
no ocupa RAM.

```bash
# Antigravity CLI (recomendado: ya está instalado y autenticado)
agy --version

# Alternativa: Qoder CLI
qoder --version
```

Desde el chat:

- «programa un script que ordene los archivos de ~/partes/pruebas»
- «pásalo a Antigravity: arregla el bug de la API»
- «arregla este bug en el repo ~/partes/Le-fil»
- «haz un test para la función suma» (en el proyecto por defecto)

También por API/MCP:

```bash
curl -s http://127.0.0.1:8765/api/coder \
  -H 'Content-Type: application/json' \
  -d '{"task":"crea un hola.py que imprima hola","workspace":"/home/jesvid/partes/pruebas"}'
```

Herramientas MCP nuevas: `cilix_code` y `cilix_coder_status`.

**Permisos (importante).** En modo headless el CLI no puede preguntar, así que:

- Los archivos dentro del proyecto se editan sin preguntar (`accept-edits`).
- Los comandos de terminal se **deniegan** por defecto. Para permitir algunos,
  añade reglas en `~/.gemini/antigravity-cli/settings.json`:

  ```json
  {"permissions": {"allow": ["command(python3)", "command(pytest)",
                             "command(git status)", "command(git diff)"]}}
  ```

- Si quieres que el agente ejecute lo que necesite sin preguntar, pon
  `CILIX_CODER_AUTO=true`: se usa `--dangerously-skip-permissions` **junto con
  `--sandbox`**, que aísla los comandos y bloquea archivos sensibles (`~/.ssh`,
  `.env`). Aun así, revisa el primer uso. También puedes pedirlo solo para una
  tarea: «programa en modo autónomo un script que…».
- `CILIX_CODER_ROOTS` limita en qué carpetas puede trabajar Cilix.
- Antigravity envía el código a Google para razonar. Si el proyecto es privado,
  usa `CILIX_CODER_MODE=plan` o no lo delegues.

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

```bash
# Tests de seguridad, voz, emociones y memoria (sin dependencias extra)
.venv/bin/python -m unittest discover -s tests -v

# Comprobación de sintaxis
.venv/bin/python -m py_compile backend/*.py
node --check frontend/js/live2d.js && node --check frontend/js/app.js
```

- Defaults confirmados: `kokoro_speed=1.25`, `voice_warmup=True`
- Smoke test WebSocket: `mode: Ri | emotion: feliz` (fallback OK),
  `speak dur:2.11s frames:53 max:0.716` (lip-sync poblando correctamente)
- `Origin` externo → el WebSocket se cierra con código `1008`.

---

## Configuración relevante (`.env`)

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `CILIX_DUAL_BRAIN` | `false` | Un solo cerebro (Re no se carga, ahorra ~1 GB) |
| `CILIX_RI_MODEL` | `qwen2.5:1.5b` | Cerebro residente |
| `CILIX_RI_KEEP_ALIVE` | `2m` | Tiempo que Ri permanece en RAM |
| `CILIX_TTS_BACKEND` | `kokoro` | Motor de voz (Kokoro femenino) |
| `CILIX_KOKORO_VOICE` | `ef_dora` | Voz femenina en español |
| `CILIX_KOKORO_SPEED` | `1.25` | >1 = habla más rápido |
| `CILIX_VOICE_WARMUP` | `true` | Precarga de voz (con guardia de RAM) |
| `CILIX_RAM_CRITICAL` | `88` | % de RAM que desactiva el warm-up |
| `CILIX_ONLINE` | `false` | Cerebro en OpenCode local (con fallback a Ollama) |
| `CILIX_ONLINE_FALLBACK` | `true` | Si OpenCode falla, responde Ollama |
| `CILIX_OPENCODE_SESSION` | `Cilix · voz` | Sesión dedicada dentro de OpenCode |
