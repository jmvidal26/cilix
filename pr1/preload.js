const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld(
  'electronAPI',
  {
    // System commands
    executeCommand: (command, options) => 
      ipcRenderer.invoke('execute-command', { command, ...options }),
    
    // File operations
    readFile: (path) => 
      ipcRenderer.invoke('read-file', path),
    
    writeFile: (path, content) => 
      ipcRenderer.invoke('write-file', { path, content }),
    
    // Python backend control
    restartPython: () => 
      ipcRenderer.invoke('restart-python'),
    
    getPythonStatus: () => 
      ipcRenderer.invoke('get-python-status'),
    
    // System monitoring
    getSystemInfo: () => 
      ipcRenderer.invoke('get-system-info'),
    
    // Settings
    saveSettings: (settings) => 
      ipcRenderer.invoke('save-settings', settings),
    
    loadSettings: () => 
      ipcRenderer.invoke('load-settings'),
    
    // Dialogs
    openDialog: (options) => 
      new Promise((resolve, reject) => {
        ipcRenderer.once('dialog-result', (event, result) => resolve(result));
        ipcRenderer.once('dialog-error', (event, error) => reject(error));
        ipcRenderer.send('open-dialog', options);
      }),
    
    // Notifications
    showNotification: (title, body) => 
      ipcRenderer.send('show-notification', { title, body }),
    
    // Event listeners
    onPythonLog: (callback) => 
      ipcRenderer.on('python-log', (event, message) => callback(message)),
    
    onPythonError: (callback) => 
      ipcRenderer.on('python-error', (event, message) => callback(message)),
    
    onPythonStopped: (callback) => 
      ipcRenderer.on('python-stopped', (event, data) => callback(data)),
    
    onCommandResult: (callback) => 
      ipcRenderer.on('command-result', (event, data) => callback(data)),
    
    onCommandError: (callback) => 
      ipcRenderer.on('command-error', (event, data) => callback(data)),
    
    onFileContent: (callback) => 
      ipcRenderer.on('file-content', (event, data) => callback(data)),
    
    onFileError: (callback) => 
      ipcRenderer.on('file-error', (event, data) => callback(data)),
    
    onSystemInfo: (callback) => 
      ipcRenderer.on('system-info', (event, data) => callback(data)),
    
    onSettingsLoaded: (callback) => 
      ipcRenderer.on('settings-loaded', (event, settings) => callback(settings)),
    
    // Remove listeners
    removeAllListeners: (channel) => 
      ipcRenderer.removeAllListeners(channel),
    
    // App controls
    openMonitor: () => 
      ipcRenderer.send('open-monitor'),
    
    openTerminal: () => 
      ipcRenderer.send('open-terminal'),
    
    openSettings: () => 
      ipcRenderer.send('open-settings')
  }
);