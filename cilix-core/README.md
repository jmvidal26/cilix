# Cilix Assistant v1.2 - 100% Local

<p align="center">
  <img src="https://img.shields.io/badge/Version-1.2--local-blue" alt="Version">
  <img src="https://img.shields.io/badge/Python-3.8%2B-green" alt="Python">
  <img src="https://img.shields.io/badge/Electron-31.0%2B-purple" alt="Electron">
  <img src="https://img.shields.io/badge/UI--Based--on--pr1-orange" alt="pr1">
  <img src="https://img.shields.io/badge/100%25--Local-red" alt="Local">
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="License">
</p>

**Cilix v1.2** es una asistente de escritorio local con avatar VTuber **Design_genius_white** (Live2D), **100% offline y sin APIs externas**, optimizada para sistemas con 8GB de RAM total (~6GB usables en Pop!_OS).

## 🎯 Características Principales v1.2

### � **Cerebro Dual (Ri & Re) - Ollama Local**
- **Ri** (Hermana menor): Modelo ultraligero (~1.5GB RAM) residente para conversación natural, cálida y proactiva
- **Re** (Hermana mayor): Modelo especialista bajo demanda (~3GB RAM) para programación y análisis técnico
- **Optimización de memoria**: Re se carga/descarga dinámicamente para no sobrecargar los 8GB RAM
- **100% Local**: Sin dependencia de APIs externas (Google, Anthropic, etc.)
- **Solo Ollama**: Todo el poder de IA en tu máquina local

### 🎭 **UI Basada en pr1 (Sylix OS Core)**
- **Fuentes Outfit + JetBrains Mono** - Diseño futurista
- **Modo mascot** - Solo personaje flotante
- **HUD completo** - Panel con métricas y chat
- **Transición suave** entre modos
- **Live2D** integrado para avatar

### 🎤 Sistema de Voz Local
- **STT**: faster-whisper (CPU-only, modelos tiny/base)
- **TTS**: Piper TTS con voces femeninas locales
- **Lip-sync**: Sincronización de labios con modelo Live2D
- **100% Offline**: No requiere conexión a internet

### 👁️ Sistema de Percepción
- **Cámara**: Detección de presencia con OpenCV (baja resolución)
- **Ventana activa**: Contexto de aplicación en uso
- **Bajo consumo**: <15% CPU, <200MB RAM para visión

### 💻 Interfaz Moderna con Todo-in-One
- **Electron**: Ventana transparente, siempre visible, sin bordes, tray icon
- **VTuber en canvas**: Renderizado WebGL del modelo Live2D
- **Terminal integrado**: Con autocompletado y comandos Sylix
- **Monitor del sistema**: Dashboard visualización de recursos
- **WebSocket**: Comunicación en tiempo real con backend Python
- **Diseño flotante**: Minimalista, con controles táctiles y VTuber integrado

### 🔧 Optimización y Automatización
- **Launcher Automatizado**: Un solo comando para todo
- **Instalación unificada**: Dependencias Python + Node.js
- **Gestión automática de Ollama**: Configuración y modelos
- **Optimización RAM**: Monitorización y ajuste dinámico
- **Entrada de escritorio**: Integrate con el sistema
- **Scripts de mantenimiento**: Monitor RAM, limpieza, diagnóstico