# Configuración Cilix v1.2

## 🎯 Objetivos de la Versión 1.2

La versión 1.2 se enfoca en **automatización completa** y **optimización de recursos** para sistemas con 8GB RAM.

## 🚀 Características Nuevas (v1.2)

### 1. Sistema de Lanzamiento Automatizado
- **Script único** `cilix-launcher.sh` para todo el proceso
- **Verificación automática** de requisitos del sistema
- **Instalación guiada** paso a paso
- **Modo interactivo** y **modo comando**

### 2. Gestión Inteligente de Dependencias
- **Entorno virtual Python** aislado
- **Instalación condicional** (solo lo necesario)
- **Cache de dependencias** para reinstalaciones rápidas
- **Verificación de versiones** compatibles

### 3. Configuración Automática de Ollama
- **Detección automática** de Ollama instalado
- **Descarga automática** de modelos Ri/Re
- **Gestión de procesos** (inicio/parada automática)
- **Logs unificados** para diagnóstico

### 4. Setup VTurer Inteligente
- **Detección automática** de modelo `Design_genius_white`
- **Copia inteligente** de assets
- **Validación de archivos** del modelo
- **Configuración automática** de paths

### 5. Optimización de Memoria RAM
- **Monitorización activa** de uso de RAM (<8GB)
- **Descarga automática** del modelo Re cuando no se usa
- **Compresión de texturas** VTuber (si es necesario)
- **Gestión de cache** inteligente

### 6. Sistema de Logging Unificado
- **Logs centralizados** en `/tmp/cilix-*.log`
- **Niveles de logging** configurables
- **Rotación automática** de logs
- **Formato estructurado** para análisis

### 7. Integración con Sistema
- **Entrada de escritorio** `.desktop`
- **Icono personalizado**
- **Integración con systemd** (opcional)
- **Scripts de servicio** para inicio automático

## 📁 Estructura de Archivos v1.2

```
cilix-core/
├── 🚀 cilix-launcher.sh           # Lanzador principal (NUEVO)
├── 📁 backend/
│   ├── 🐍 main.py                # Servidor FastAPI
│   ├── 🧠 core_ia.py             # Cerebro dual Ri/Re
│   ├── 🎤 audio_engine.py        # STT + TTS
│   ├── 👁️ vista_engine.py       # Visión
│   ├── 💻 os_controller.py       # Control sistema
│   ├── 🎭 vtuber_engine.py       # Motor VTuber
│   └── 🔧 config_manager.py      # Gestor configuración (NUEVO)
├── 📁 frontend/
│   ├── 🌐 index.html             # Interfaz web
│   ├── ⚡ renderer.js            # Lógica frontend
│   ├── 🎨 style.css              # Estilos
│   └── 📁 live2d/                # WebGL Live2D
├── 📁 electron/
│   ├── ⚛️ main.js               # Electron main
│   └── 🔗 preload.js             # Preload script
├── 📁 assets/                    # Recursos VTuber
│   ├── 📁 models/               # Modelos Live2D
│   ├── 📁 textures/             # Texturas
│   ├── 📁 expressions/          # Expresiones
│   ├── 📁 motions/              # Animaciones
│   └── ⚙️ model-config.json     # Config modelo
├── 📁 scripts/                   # Scripts auxiliares (NUEVO)
│   ├── 🛠️ install-deps.sh      # Instalación dependencias
│   ├── 🧪 run-tests.sh          # Ejecución pruebas
│   ├── 🧹 cleanup.sh            # Limpieza
│   └── 📊 monitor-ram.sh        # Monitor RAM
├── 📁 config/                    # Configuración (NUEVO)
│   ├── ⚙️ cilix-config.json     # Configuración principal
│   ├── 🎛️ ai-models.json       # Modelos AI configurados
│   ├── 🗣️ voice-profiles.json  # Perfiles de voz
│   └── 🎭 vtuber-settings.json  # Config VTuber
├── 📄 requirements.txt           # Dependencias Python
├── 📄 package.json              # Dependencias Node.js
├── 📖 README.md                 # Documentación
├── 🧪 test_cilix.py             # Suite de pruebas
├── 🧪 test_simple.py            # Pruebas simples
└── 🏷️ VERSION                   # Archivo de versión (NUEVO)
```

## ⚙️ Configuración de Optimización RAM

### Límites por Defecto (8GB Sistema)
```json
{
  "memory_limits": {
    "max_total_ram_mb": 6144,      // 6GB usables de 8GB
    "ri_model_limit_mb": 1536,     // 1.5GB para Ri
    "re_model_limit_mb": 3072,     // 3GB para Re (bajo demanda)
    "system_overhead_mb": 1024,    // 1GB para sistema
    "emergency_threshold_mb": 512  // 512MB margen de seguridad
  },
  "optimization": {
    "auto_unload_re": true,        // Descargar Re automáticamente
    "texture_compression": "medium", // Compresión texturas
    "cache_size_mb": 256,          // Tamaño máximo cache
    "monitor_interval_sec": 5      // Intervalo monitoreo RAM
  }
}
```

### Estrategias de Optimización
1. **Modelo Re bajo demanda**: Solo cargado cuando se necesita programación
2. **Compresión de texturas**: Texturas VTuber optimizadas para RAM
3. **Cache LRU**: Eliminación de cache menos usado recientemente
4. **Pool de conexiones**: Reutilización de conexiones WebSocket/HTTP
5. **Lazy loading**: Carga diferida de módulos no esenciales

## 🔧 Scripts de Automatización

### `cilix-launcher.sh` - Lanzador Principal
```bash
# Modos de operación
./cilix-launcher.sh              # Modo interactivo
./cilix-launcher.sh --setup      # Instalar + ejecutar
./cilix-launcher.sh --install    # Solo instalación
./cilix-launcher.sh --run        # Solo ejecución
./cilix-launcher.sh --test       # Ejecutar pruebas
./cilix-launcher.sh --clean      # Limpiar instalación
./cilix-launcher.sh --status     # Ver estado
```

### `scripts/monitor-ram.sh` - Monitor RAM
```bash
# Monitoreo continuo de RAM
./scripts/monitor-ram.sh

# Con alertas
./scripts/monitor-ram.sh --alert 6000  # Alerta a 6GB

# Con registro
./scripts/monitor-ram.sh --log /tmp/ram.log
```

### `scripts/install-deps.sh` - Instalación Dependencias
```bash
# Instalación completa
./scripts/install-deps.sh --all

# Solo Python
./scripts/install-deps.sh --python

# Solo Node.js
./scripts/install-deps.sh --node

# Verificar sin instalar
./scripts/install-deps.sh --check
```

## 🧪 Suite de Pruebas v1.2

### Pruebas Automatizadas
```bash
# Pruebas completas
python test_cilix.py

# Pruebas específicas
python test_cilix.py --module core_ia
python test_cilix.py --module vtuber_engine

# Pruebas de rendimiento
python test_cilix.py --performance

# Pruebas de memoria
python test_cilix.py --memory
```

### Verificación de Salud
```bash
# Verificar estado del sistema
./cilix-launcher.sh --status

# Verificar servicios
curl http://localhost:8765/health
curl http://localhost:11434/api/tags

# Verificar RAM
free -h
```

## 📊 Métricas y Monitoreo

### Métricas Clave
- **RAM usada**: Objetivo <6GB de 8GB total
- **Tiempo respuesta IA**: <2s para Ri, <5s para Re
- **FPS VTurer**: >30 FPS estable
- **Latencia audio**: <100ms para lip-sync
- **Uso CPU**: <30% en idle, <70% bajo carga

### Archivos de Log
```
/tmp/cilix-python.log      # Logs servidor Python
/tmp/cilix-electron.log    # Logs Electron
/tmp/ollama-cilix.log      # Logs Ollama
/tmp/cilix-ram.log         # Logs uso RAM
/tmp/cilix-perf.log        # Logs rendimiento
```

## 🚀 Plan de Implementación v1.2

### Fase 1: Automatización (Semana 1)
- [ ] Crear `cilix-launcher.sh` completo
- [ ] Implementar verificación de requisitos
- [ ] Crear sistema de entorno virtual
- [ ] Automatizar instalación dependencias

### Fase 2: Optimización RAM (Semana 2)
- [ ] Implementar monitor de RAM
- [ ] Crear sistema de descarga automática de Re
- [ ] Optimizar texturas VTurer
- [ ] Implementar cache LRU

### Fase 3: Sistema de Logging (Semana 3)
- [ ] Centralizar logs en `/tmp/cilix-*.log`
- [ ] Implementar rotación de logs
- [ ] Crear sistema de alertas RAM
- [ ] Añadir métricas de rendimiento

### Fase 4: Integración Sistema (Semana 4)
- [ ] Crear entrada `.desktop`
- [ ] Implementar scripts de servicio
- [ ] Añadir icono personalizado
- [ ] Documentación completa

## 🔮 Características Futuras (Post v1.2)

### v1.3 - Plugins y Extensiones
- Sistema de plugins para funcionalidades adicionales
- API para desarrolladores de terceros
- Store de plugins integrado

### v1.4 - Aprendizaje y Personalización
- Aprendizaje de preferencias del usuario
- Personalización de personalidad Ri/Re
- Sistema de comandos personalizados

### v1.5 - Integraciones Avanzadas
- Integración con Obsidian, Joplin, etc.
- Control por voz avanzado
- Reconocimiento gestual

## 📞 Soporte y Diagnóstico

### Comandos de Diagnóstico
```bash
# Verificar estado completo
./cilix-launcher.sh --diagnose

# Generar reporte de problemas
./cilix-launcher.sh --report

# Reiniciar servicios
./cilix-launcher.sh --restart

# Ver logs en tiempo real
tail -f /tmp/cilix-*.log
```

### Códigos de Error Comunes
```
ERR001: Python no encontrado
ERR002: Node.js no encontrado  
ERR003: Ollama no disponible
ERR004: RAM insuficiente
ERR005: Modelo VTuber faltante
ERR006: Dependencias incompletas
ERR007: Puerto en uso
ERR008: Permisos insuficientes
```

---

**Cilix v1.2** representa un paso significativo hacia un sistema **completamente automatizado, optimizado y fácil de usar** que mantiene su compromiso con la **privacidad 100% local** y la **optimización para 8GB RAM**.