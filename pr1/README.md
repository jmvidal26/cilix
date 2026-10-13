# Sylix OS Core Assistant

**VTuber Agent with Linux Desktop Automation & System Control**

![Sylix OS Core](assets/icon.png)

## 🚀 Transformación: De Web App a Aplicación Nativa de Escritorio

Sylix OS Core ha evolucionado de una aplicación web a una aplicación nativa de escritorio con capacidades avanzadas de Linux, proporcionando control total del sistema y automatización del escritorio.

## ✨ Nuevas Características (Versión Nativa)

### 🖥️ **Interfaz Nativa**
- Aplicación Electron independiente (sin navegador)
- Tray icon y notificaciones del sistema
- Menú de aplicaciones nativo
- Acceso directo desde dock/menú inicio

### 🔧 **Funcionalidades Avanzadas de Linux**
- **Terminal Integrado**: Terminal completa con autocompletado y comandos Sylix
- **Monitor del Sistema**: Gráficos en tiempo real de CPU, RAM, disco, red
- **Gestor de Procesos**: Visualización y control de procesos en ejecución
- **Control de Servicios**: Gestión de servicios systemd (start/stop/restart)
- **Explorador de Archivos**: Navegación con permisos completos
- **Script Manager**: Crear, guardar y ejecutar scripts bash/python
- **Logs del Sistema**: Acceso directo a syslog, auth.log, journalctl

### 🎭 **VTuber Agent Mejorado**
- Avatar Live2D con animaciones fluidas
- Síntesis de voz con múltiples backends (Edge-TTS, Piper, pyttsx3)
- IA multimodal (Gemini, Claude, Ollama offline)
- Automatización de escritorio con xdotool/wmctrl
- Control por voz y texto

## 📦 Instalación Rápida

### Requisitos Previos
```bash
# Sistema
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip nodejs npm

# Dependencias del sistema
sudo apt-get install -y xdotool wmctrl nmap ffmpeg scrot alsa-utils
```

### Instalación Automática
```bash
# Dar permisos de ejecución
chmod +x install-electron.sh

# Ejecutar instalador
./install-electron.sh
```

El instalador automáticamente:
1. Verifica dependencias
2. Configura entorno Python virtual
3. Instala dependencias Node.js
4. Crea scripts de inicio
5. Agrega acceso directo al menú

### Configuración Manual
```bash
# 1. Configurar entorno Python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Instalar dependencias Node.js
npm install

# 3. Instalar electron-builder globalmente
sudo npm install -g electron-builder

# 4. Configurar API keys (opcional)
# Edita el archivo .env y agrega tus claves de API
nano .env
```

## 🎮 Uso

### Modos de Ejecución
```bash
# 🚀 Inicio completo (recomendado para nuevos usuarios)
./run.sh

# ⚡ Desarrollo rápido con características avanzadas
./start_sylix.sh

# 🔧 Solo backend Python (API REST + WebSocket)
python main.py

# 🖥️ Aplicación Electron nativa (requiere Node.js)
npm start

# 🧪 Modo prueba y verificación
python tests/test_advanced_integration.py
```

### Características Avanzadas (Nueva)
Sylix OS Core ahora incluye tres sistemas avanzados:

1. **🧠 Memoria Persistente** (SIEMPRE ACTIVA)
   - Almacena todas las conversaciones y acciones
   - Base de datos SQLite en `~/.config/sylix/memory.db`
   - Aprende preferencias y patrones del usuario

2. **👁️ Monitor de Actividad** (OPCIONAL)
   - Registra actividad del sistema y aplicaciones
   - Detecta patrones de uso y hábitos
   - Base de datos en `~/.config/sylix/activity.db`

3. **💡 Pensamiento Proactivo** (OPCIONAL)
   - Analiza datos y genera sugerencias automáticas
   - Sugiere optimizaciones y recordatorios
   - Base de datos en `~/.config/sylix/proactive.db`

**Accede al panel de control:** `http://localhost:8000/advanced`

### Comandos Sylix en Terminal
```bash
sylix-help        # Muestra todos los comandos Sylix
sylix-system      # Información detallada del sistema
sylix-monitor     # Inicia monitoreo en tiempo real
sylix-services    # Lista y gestiona servicios systemd
sylix-scripts     # Administra scripts personalizados
sylix-logs        # Accede a logs del sistema
sylix-automate    # Herramientas de automatización
```

### Comandos de Automatización
```bash
# Ejemplos desde la interfaz de Sylix:
"mover mouse a 100,100"
"hacer clic en la posición actual"
"tomar captura de pantalla"
"abrir terminal"
"listar procesos"
"reiniciar servicio ssh"
```

## 🏗️ Arquitectura

### Stack Tecnológico
```
┌─────────────────────────────────────────┐
│           Aplicación Electron           │
│  ┌──────────────────────────────────┐  │
│  │        Frontend (HTML/JS/CSS)    │  │
│  │  • Interfaz Live2D VTuber        │  │
│  │  • Terminal integrado (xterm.js) │  │
│  │  • Monitor del sistema           │  │
│  └──────────────────────────────────┘  │
│                 │ IPC                  │
│  ┌──────────────────────────────────┐  │
│  │    Backend Python (FastAPI)     │  │
│  │  • IA Agents (Gemini/Claude)    │  │
│  │  • TTS (Edge-TTS/Piper)         │  │
│  │  • Herramientas del sistema     │  │
│  └──────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Módulos Principales
1. **Electron Main Process** (`main.js`): Gestión de ventanas, tray, IPC
2. **Python Backend** (`main.py`): IA, TTS, herramientas del sistema
3. **Frontend** (`index.html`): Interfaz VTuber, terminal, monitor
4. **Linux Integration** (`electron-python-integration.py`): APIs nativas de Linux
5. **Terminal** (`terminal.js`): Terminal integrado con node-pty

## 🔧 Desarrollo

### Estructura de Archivos (Organizada)
```
sylix-os-core/
├── 📁 Raíz del Proyecto
│   ├── main.py                    # Backend FastAPI principal
│   ├── run.sh                     # Script principal de instalación/inicio
│   ├── start_sylix.sh             # Script simplificado para desarrollo
│   ├── package.json              # Configuración Electron/Node.js
│   ├── requirements.txt          # Dependencias Python
│   ├── README.md                 # Esta documentación
│   └── .env                      # Variables de entorno
│
├── 📁 src/                        # Código fuente Python
│   ├── main.py                   # (enlace simbólico a ../main.py)
│   ├── ai_backends.py           # Backends de IA (Gemini/Claude/Ollama)
│   ├── tools.py                  # Herramientas del sistema
│   ├── memory.py                # Memoria persistente (SIEMPRE ACTIVA)
│   ├── activity_monitor.py      # Monitor de actividad (OPCIONAL)
│   ├── proactive_thinking.py    # Pensamiento proactivo (OPCIONAL)
│   ├── advanced_features.py     # Sistema de integración avanzada
│   └── pop_os_command_runner.py # Ejecutor de comandos Pop!_OS
│
├── 📁 web/                        # Frontend Web/Electron
│   ├── main.js                  # Proceso principal Electron
│   ├── preload.js               # Contexto seguro para IPC
│   ├── terminal.js              # Terminal integrado
│   ├── index.html              # Interfaz principal
│   ├── advanced_panel.html     # Panel de características avanzadas
│   ├── system-monitor.html     # Monitor del sistema
│   └── static/                 # Recursos estáticos (CSS/JS)
│
├── 📁 models/                     # Modelos de IA y Voz
│   ├── design_genius_white/    # Avatar Live2D
│   ├── piper/                  # Modelos Piper TTS (español)
│   ├── kokoro/                 # Modelos Kokoro TTS (anime)
│   └── sylix                   # Configuración del modelo Sylix
│
├── 📁 scripts/                    # Scripts de utilidad
│   ├── install-electron.sh     # Instalador de Electron
│   ├── start-now.sh           # Inicio rápido
│   ├── demo-comandos.sh       # Demo de comandos
│   └── verify_dependencies.py # Verificador de dependencias
│
├── 📁 tests/                      # Pruebas y validación
│   └── test_advanced_integration.py # Pruebas de características avanzadas
│
├── 📁 logs/                       # Logs de la aplicación
├── 📁 assets/                     # Iconos y recursos gráficos
└── 📁 __pycache__/               # Caché Python (generado automáticamente)
```

### Construcción para Distribución
```bash
# Build para Linux (DEB, RPM, AppImage)
npm run build-linux

# Solo DEB package
npm run build-deb

# Solo AppImage
npm run build-appimage

# Solo RPM package
npm run build-rpm
```

## 🛡️ Seguridad

### Características de Seguridad
- **Sandboxing**: Procesos aislados (Electron renderer)
- **Validación de Comandos**: Sanitización de entrada del usuario
- **Permisos Granulares**: Control por función específica
- **Logging de Auditoría**: Registro detallado de operaciones
- **Prompt de Confirmación**: Para operaciones privilegiadas

### Comandos Restringidos
La aplicación valida y restringe comandos peligrosos:
- Eliminación recursiva sin confirmación
- Modificación de archivos del sistema sin privilegios explícitos
- Comandos con potencial de daño al sistema

## 🤖 Integración con IA

### Backends Disponibles
1. **Google Gemini** (Online, Primario): `gemini-2.0-flash`
2. **Anthropic Claude** (Online, Secundario): `claude-3-5-sonnet`
3. **Ollama Local** (Offline, Fallback): `qwen2.5:1.5b`

### Configuración de IA
```env
# En archivo .env
GEMINI_API_KEY=tu_clave_aqui
ANTHROPIC_API_KEY=tu_clave_aqui
OLLAMA_MODEL=qwen2.5:1.5b
```

## 🔊 Síntesis de Voz (TTS)

### Backends Disponibles
1. **Edge-TTS** (Microsoft Neural Voices): Calidad premium, requiere internet
2. **Piper TTS** (Neural Offline): Voz femenina natural en español
3. **pyttsx3** (Fallback): Sintetizador offline básico

## 🚀 Roadmap

### Próximas Características
- [ ] Integración con Docker/Podman
- [ ] Gestor de paquetes apt/dnf integrado
- [ ] Monitor de red avanzado
- [ ] Backup y sincronización
- [ ] Plugins y extensiones
- [ ] Modo kiosko/pantalla completa

### Mejoras Planeadas
- [ ] Soporte para múltiples avatares Live2D
- [ ] Reconocimiento de voz mejorado
- [ ] Gestión de perfiles de usuario
- [ ] API REST para integraciones externas
- [ ] CLI companion para administración remota

## 🤝 Contribuir

1. Fork el repositorio
2. Crea una rama: `git checkout -b feature/nueva-funcionalidad`
3. Haz commit de tus cambios: `git commit -am 'Add nueva funcionalidad'`
4. Push a la rama: `git push origin feature/nueva-funcionalidad`
5. Abre un Pull Request

### Guías de Estilo
- **Python**: PEP 8, type hints, docstrings
- **JavaScript**: ES6+, async/await, comentarios JSDoc
- **HTML/CSS**: Semántico, responsive, variables CSS

## 📄 Licencia

MIT License - ver [LICENSE](LICENSE) para detalles.

## 🙏 Agradecimientos

- **Live2D Cubism**: Framework de animación 2D
- **Electron**: Framework para aplicaciones de escritorio
- **FastAPI**: Framework web Python de alto rendimiento
- **Google Gemini & Anthropic Claude**: Modelos de IA
- **Piper TTS**: Síntesis de voz neural offline

---

**✨ Transforma tu escritorio Linux en un asistente VTuber inteligente con Sylix OS Core Assistant!**