const { contextBridge, ipcRenderer } = require('electron');

// Exponer APIs seguras al renderer
contextBridge.exposeInMainWorld('electronAPI', {
    // Comunicación con el proceso principal
    toggleWindowVisibility: () => ipcRenderer.send('toggle-window-visibility'),
    quitApp: () => ipcRenderer.send('quit-app'),
    restartPythonServer: () => ipcRenderer.send('restart-python-server'),
    
    // Obtener estado del servidor
    getServerStatus: () => ipcRenderer.invoke('get-server-status'),
    
    // Para arrastrar ventana
    startDrag: () => {
        ipcRenderer.send('start-drag-window');
    },
    
    // Escuchar eventos del proceso principal
    onPythonLog: (callback) => {
        ipcRenderer.on('python-log', (event, log) => callback(log));
    },
    
    onPythonError: (callback) => {
        ipcRenderer.on('python-error', (event, error) => callback(error));
    },
    
    onWindowFocusChange: (callback) => {
        ipcRenderer.on('window-focus-change', (event, isFocused) => callback(isFocused));
    },
    
    // Limpiar listeners
    removeAllListeners: (channel) => {
        ipcRenderer.removeAllListeners(channel);
    }
});

// Exponer versión de Node para debugging
contextBridge.exposeInMainWorld('nodeEnv', {
    version: process.versions.node,
    electron: process.versions.electron,
    platform: process.platform,
    isDev: process.argv.includes('--dev')
});