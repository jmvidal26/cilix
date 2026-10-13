// ══════════════════════════════════════════════════════════════════════════
//  Cilix · Preload (puente seguro main ↔ renderer)
//  Expone una API mínima sobre `window.cilix` sin revelar Electron completo.
//  La comunicación de datos en tiempo real va por WebSocket (frontend), aquí
//  solo se exponen controles de ventana y estado del backend.
// ══════════════════════════════════════════════════════════════════════════
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('cilix', {
  // ¿Corre dentro de Electron? El frontend lo usa para habilitar overlay.
  isElectron: true,

  // ── Controles de la ventana flotante ──────────────────────────────────
  minimize: () => ipcRenderer.send('window:minimize'),
  hide: () => ipcRenderer.send('window:close'),
  quit: () => ipcRenderer.send('window:quit'),
  setAlwaysOnTop: (onTop) => ipcRenderer.send('window:toggle-top', onTop),
  moveBy: (dx, dy) => ipcRenderer.send('window:move-by', dx, dy),

  // ── Estado del backend Python ─────────────────────────────────────────
  backendStatus: () => ipcRenderer.invoke('backend:status'),
  version: () => ipcRenderer.invoke('app:version'),

  // ── Suscripción a logs del backend ────────────────────────────────────
  onBackendLog: (cb) => ipcRenderer.on('backend-log', (_e, msg) => cb(msg)),
  onBackendError: (cb) => ipcRenderer.on('backend-error', (_e, msg) => cb(msg)),

  // Limpieza de listeners al desmontar
  removeListeners: (channel) => ipcRenderer.removeAllListeners(channel),
});
