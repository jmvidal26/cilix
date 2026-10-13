const { app, BrowserWindow, ipcMain, Menu, Tray, Notification, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, exec } = require('child_process');
const log = require('electron-log');
const Store = require('electron-store');
const WebSocket = require('ws');

// Configuración
const isDev = process.env.NODE_ENV === 'development';
const store = new Store();

// Variables globales
let mainWindow = null;
let tray = null;
let pythonProcess = null;
let pythonPort = 8000;
let wsServer = null;

// Logging configuration
log.transports.file.level = isDev ? 'debug' : 'info';
log.transports.console.level = isDev ? 'debug' : 'info';

// IPC Handlers
const ipcHandlers = {
  // System commands
  'execute-command': async (event, { command, timeout = 30, background = false }) => {
    try {
      const result = await executeSystemCommand(command, { timeout, background });
      event.reply('command-result', { id: command, result });
    } catch (error) {
      log.error('Command execution error:', error);
      event.reply('command-error', { id: command, error: error.message });
    }
  },

  // File operations
  'read-file': (event, filePath) => {
    fs.readFile(filePath, 'utf-8', (err, data) => {
      if (err) {
        event.reply('file-error', { path: filePath, error: err.message });
      } else {
        event.reply('file-content', { path: filePath, content: data });
      }
    });
  },

  'write-file': (event, { path, content }) => {
    fs.writeFile(path, content, 'utf-8', (err) => {
      if (err) {
        event.reply('file-error', { path, error: err.message });
      } else {
        event.reply('file-written', { path });
      }
    });
  },

  // Python backend control
  'restart-python': (event) => {
    restartPythonBackend();
    event.reply('python-restarted');
  },

  'get-python-status': (event) => {
    const status = pythonProcess ? 'running' : 'stopped';
    event.reply('python-status', { status, port: pythonPort });
  },

  // System monitoring
  'get-system-info': async (event) => {
    try {
      const si = require('systeminformation');
      const [cpu, mem, osInfo] = await Promise.all([
        si.cpu(),
        si.mem(),
        si.osInfo()
      ]);
      event.reply('system-info', { cpu, memory: mem, os: osInfo });
    } catch (error) {
      log.error('System info error:', error);
      event.reply('system-info-error', { error: error.message });
    }
  },

  // Settings
  'save-settings': (event, settings) => {
    store.set('settings', settings);
    event.reply('settings-saved');
  },

  'load-settings': (event) => {
    const settings = store.get('settings', {
      geminiApiKey: '',
      anthropicApiKey: '',
      ollamaModel: 'qwen2.5:1.5b',
      ttsVoice: 'es-CO-SalomeNeural',
      theme: 'dark',
      autoStartPython: true,
      showTerminal: false
    });
    event.reply('settings-loaded', settings);
  }
};

// Execute system command with timeout
function executeSystemCommand(command, options = {}) {
  return new Promise((resolve, reject) => {
    const { timeout = 30, background = false } = options;
    
    if (background) {
      const proc = spawn(command, { 
        shell: true,
        detached: true,
        stdio: 'ignore'
      });
      proc.unref();
      resolve({ pid: proc.pid, status: 'background', command });
      return;
    }

    const timer = setTimeout(() => {
      reject(new Error(`Command timeout after ${timeout} seconds`));
    }, timeout * 1000);

    exec(command, { maxBuffer: 1024 * 1024 }, (error, stdout, stderr) => {
      clearTimeout(timer);
      
      if (error) {
        reject(new Error(stderr || error.message));
      } else {
        resolve({
          stdout: stdout.trim(),
          stderr: stderr.trim(),
          code: error ? error.code : 0,
          command
        });
      }
    });
  });
}

// Python backend management
function startPythonBackend() {
  if (pythonProcess) {
    log.info('Python backend already running');
    return;
  }

  const pythonPath = isDev ? 'python3' : path.join(process.resourcesPath, 'python', 'bin', 'python3');
  const scriptPath = isDev ? 'main.py' : path.join(process.resourcesPath, 'python', 'main.py');
  
  const env = {
    ...process.env,
    PORT: pythonPort.toString(),
    PYTHONUNBUFFERED: '1',
    GEMINI_API_KEY: store.get('settings.geminiApiKey', ''),
    ANTHROPIC_API_KEY: store.get('settings.anthropicApiKey', '')
  };

  log.info(`Starting Python backend on port ${pythonPort}`);
  
  pythonProcess = spawn(pythonPath, ['-m', 'uvicorn', 'main:app', '--host', '0.0.0.0', '--port', pythonPort.toString(), '--log-level', 'info'], {
    cwd: isDev ? process.cwd() : path.join(process.resourcesPath, 'python'),
    env,
    stdio: ['pipe', 'pipe', 'pipe']
  });

  pythonProcess.stdout.on('data', (data) => {
    const message = data.toString();
    log.info(`Python: ${message}`);
    
    // Send logs to renderer
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('python-log', message);
    }
  });

  pythonProcess.stderr.on('data', (data) => {
    const message = data.toString();
    log.error(`Python Error: ${message}`);
    
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('python-error', message);
    }
  });

  pythonProcess.on('close', (code) => {
    log.info(`Python backend exited with code ${code}`);
    pythonProcess = null;
    
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('python-stopped', { code });
    }
    
    // Auto-restart if unexpected exit
    if (code !== 0 && code !== null) {
      setTimeout(() => startPythonBackend(), 3000);
    }
  });

  pythonProcess.on('error', (err) => {
    log.error('Failed to start Python backend:', err);
    pythonProcess = null;
  });
}

function restartPythonBackend() {
  if (pythonProcess) {
    pythonProcess.kill('SIGTERM');
    pythonProcess = null;
  }
  setTimeout(() => startPythonBackend(), 1000);
}

// Create main window
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 768,
    title: 'Sylix OS Core Assistant',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    frame: true,
    backgroundColor: '#050a14',
    show: false
  });

  // Load the Python backend's web interface
  const url = isDev 
    ? `http://localhost:${pythonPort}`
    : `file://${path.join(__dirname, 'index.html')}`;

  mainWindow.loadURL(url);

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (isDev) {
      mainWindow.webContents.openDevTools();
    }
  });

  // Handle external links
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http')) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });

  // Update window title with status
  mainWindow.webContents.on('did-finish-load', () => {
    mainWindow.setTitle(`Sylix OS Core Assistant - Port ${pythonPort}`);
  });

  return mainWindow;
}

// Create system tray
function createTray() {
  const iconPath = path.join(__dirname, 'assets', 'tray-icon.png');
  tray = new Tray(iconPath || path.join(__dirname, 'assets', 'icon.png'));
  
  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show/Hide',
      click: () => {
        if (mainWindow.isVisible()) {
          mainWindow.hide();
        } else {
          mainWindow.show();
        }
      }
    },
    {
      label: 'Restart Python Backend',
      click: () => restartPythonBackend()
    },
    { type: 'separator' },
    {
      label: 'System Monitor',
      click: () => {
        mainWindow.webContents.send('open-monitor');
      }
    },
    {
      label: 'Terminal',
      click: () => {
        mainWindow.webContents.send('open-terminal');
      }
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => app.quit()
    }
  ]);

  tray.setToolTip('Sylix OS Core Assistant');
  tray.setContextMenu(contextMenu);
  
  tray.on('click', () => {
    mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
  });
}

// Setup IPC handlers
function setupIpcHandlers() {
  Object.entries(ipcHandlers).forEach(([channel, handler]) => {
    ipcMain.handle(channel, handler);
  });

  // Additional IPC channels
  ipcMain.on('open-dialog', (event, options) => {
    dialog.showOpenDialog(mainWindow, options).then((result) => {
      event.reply('dialog-result', result);
    }).catch((err) => {
      event.reply('dialog-error', err.message);
    });
  });

  ipcMain.on('show-notification', (event, { title, body }) => {
    new Notification({ title, body }).show();
  });
}

// App lifecycle
app.whenReady().then(() => {
  log.info('App starting...');
  
  // Create main window
  createMainWindow();
  
  // Setup IPC
  setupIpcHandlers();
  
  // Create system tray
  if (process.platform !== 'darwin') {
    createTray();
  }
  
  // Start Python backend
  const settings = store.get('settings', {});
  if (settings.autoStartPython !== false) {
    setTimeout(() => startPythonBackend(), 1000);
  }
  
  // Create application menu
  const menuTemplate = [
    {
      label: 'File',
      submenu: [
        {
          label: 'Settings',
          accelerator: 'CmdOrCtrl+,',
          click: () => mainWindow.webContents.send('open-settings')
        },
        { type: 'separator' },
        {
          label: 'Quit',
          accelerator: 'CmdOrCtrl+Q',
          role: 'quit'
        }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Tools',
      submenu: [
        {
          label: 'System Monitor',
          accelerator: 'Ctrl+Shift+M',
          click: () => mainWindow.webContents.send('open-monitor')
        },
        {
          label: 'Terminal',
          accelerator: 'Ctrl+Shift+T',
          click: () => mainWindow.webContents.send('open-terminal')
        },
        { type: 'separator' },
        {
          label: 'Restart Backend',
          click: () => restartPythonBackend()
        }
      ]
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Documentation',
          click: () => shell.openExternal('https://github.com/sylix-team/sylix-os-core')
        },
        { type: 'separator' },
        {
          label: 'About',
          click: () => dialog.showMessageBox(mainWindow, {
            type: 'info',
            title: 'About Sylix OS Core Assistant',
            message: 'Sylix OS Core Assistant v1.0.0',
            detail: 'VTuber Agent with Linux Desktop Automation\n\nCreated with ❤️ for Pop!_OS and Linux systems.'
          })
        }
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(menuTemplate);
  Menu.setApplicationMenu(menu);
});

// App event handlers
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  }
});

app.on('before-quit', () => {
  if (pythonProcess) {
    pythonProcess.kill('SIGTERM');
  }
});

// Clean exit
process.on('SIGTERM', () => {
  if (pythonProcess) {
    pythonProcess.kill('SIGTERM');
  }
  app.quit();
});