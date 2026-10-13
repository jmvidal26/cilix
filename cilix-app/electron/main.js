// ══════════════════════════════════════════════════════════════════════════
//  Cilix · Proceso principal de Electron
//  Ventana flotante transparente (overlay VTuber) + lanzamiento del backend
//  Python (FastAPI) como proceso hijo. Hereda la interfaz flotante de pr1 y
//  la arquitectura de cerebro dual de cilix-core.
// ══════════════════════════════════════════════════════════════════════════
const { app, BrowserWindow, ipcMain, screen, Tray, Menu, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

// ── Configuración ────────────────────────────────────────────────────────────
const IS_DEV = process.argv.includes('--dev') || process.env.NODE_ENV === 'development';
const PORT = parseInt(process.env.CILIX_PORT || '8765', 10);
const BACKEND_URL = `http://127.0.0.1:${PORT}`;

const ROOT_DIR = path.join(__dirname, '..');
const BACKEND_DIR = path.join(ROOT_DIR, 'backend');
// Selecciona el intérprete: venv local si existe, si no python3 del sistema.
const VENV_PY = path.join(ROOT_DIR, '.venv', 'bin', 'python');
const PYTHON = fs.existsSync(VENV_PY) ? VENV_PY : 'python3';

let mainWindow = null;
let tray = null;
let pythonProcess = null;

// ── Backend Python como proceso hijo ──────────────────────────────────────────
function startPythonBackend() {
  if (pythonProcess) return;

  const args = [path.join(BACKEND_DIR, 'main.py')];
  if (IS_DEV) args.push('--dev');

  console.log(`🐍 Arrancando backend: ${PYTHON} ${args.join(' ')}`);
  pythonProcess = spawn(PYTHON, args, {
    cwd: BACKEND_DIR,
    env: { ...process.env, PYTHONUNBUFFERED: '1', CILIX_PORT: String(PORT) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  pythonProcess.stdout.on('data', (d) => {
    const msg = d.toString().trim();
    if (msg) console.log(`[backend] ${msg}`);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('backend-log', msg);
    }
  });

  pythonProcess.stderr.on('data', (d) => {
    const msg = d.toString().trim();
    if (msg) console.error(`[backend!] ${msg}`);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('backend-error', msg);
    }
  });

  pythonProcess.on('close', (code) => {
    console.log(`⚠️ Backend terminado (código ${code})`);
    pythonProcess = null;
    // Reintento automático si el cierre no fue provocado por el usuario
    if (code !== 0 && code !== null && !app.isQuitting) {
      setTimeout(startPythonBackend, 3000);
    }
  });

  pythonProcess.on('error', (err) => {
    console.error('❌ No se pudo iniciar el backend:', err.message);
    pythonProcess = null;
  });
}

function stopPythonBackend() {
  if (pythonProcess) {
    pythonProcess.kill('SIGTERM');
    pythonProcess = null;
  }
}

// Espera a que el backend responda en /health antes de mostrar la ventana.
async function waitForBackend(timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BACKEND_URL}/health`);
      if (res.ok) return true;
    } catch (_) {
      /* aún no está listo */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

// ── Ventana flotante transparente ────────────────────────────────────────────
function createMainWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  mainWindow = new BrowserWindow({
    width: 460,
    height: 680,
    x: width - 480,          // esquina derecha por defecto
    y: 40,
    minWidth: 320,
    minHeight: 480,
    transparent: true,       // fondo transparente (overlay)
    frame: false,            // sin barra de título
    alwaysOnTop: true,       // siempre visible sobre el escritorio
    resizable: true,
    skipTaskbar: false,
    hasShadow: false,
    icon: path.join(ROOT_DIR, 'assets', 'icon.png'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
      backgroundThrottling: false,
    },
  });

  mainWindow.loadURL(BACKEND_URL);

  mainWindow.once('ready-to-show', () => mainWindow.show());

  if (IS_DEV) mainWindow.webContents.openDevTools({ mode: 'detach' });

  // Enlaces externos → navegador del sistema
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http')) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ── Bandeja del sistema ───────────────────────────────────────────────────────
function createTray() {
  const icon = path.join(ROOT_DIR, 'assets', 'tray-icon.png');
  if (!fs.existsSync(icon)) return; // sin icono no hay bandeja
  tray = new Tray(icon);
  tray.setToolTip('Cilix · Asistente de escritorio');
  tray.setContextMenu(Menu.buildFromTemplate([
    {
      label: 'Mostrar / Ocultar',
      click: () => {
        if (!mainWindow) return createMainWindow();
        mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
      },
    },
    { label: 'Reiniciar backend', click: () => { stopPythonBackend(); startPythonBackend(); } },
    { type: 'separator' },
    { label: 'Salir', click: () => app.quit() },
  ]));
}

// ── Handlers IPC (puente seguro con el renderer) ─────────────────────────────
function setupIpc() {
  // Controles de ventana del overlay
  ipcMain.on('window:minimize', () => mainWindow && mainWindow.minimize());
  ipcMain.on('window:close', () => mainWindow && mainWindow.hide());
  ipcMain.on('window:quit', () => app.quit());
  ipcMain.on('window:toggle-top', (_e, onTop) =>
    mainWindow && mainWindow.setAlwaysOnTop(Boolean(onTop)));

  // Reposicionamiento relativo (arrastrar el overlay)
  ipcMain.on('window:move-by', (_e, dx, dy) => {
    if (!mainWindow) return;
    const [x, y] = mainWindow.getPosition();
    mainWindow.setPosition(Math.round(x + dx), Math.round(y + dy));
  });

  // Estado del backend solicitado por la UI
  ipcMain.handle('backend:status', () => ({
    running: Boolean(pythonProcess),
    port: PORT,
    url: BACKEND_URL,
  }));

  ipcMain.handle('app:version', () => app.getVersion());
}

// ── Ciclo de vida de la aplicación ───────────────────────────────────────────
app.whenReady().then(async () => {
  if (app.isPackaged) app.setLoginItemSettings && app.setLoginItemSettings({ openAtLogin: false });

  setupIpc();
  startPythonBackend();

  const ready = await waitForBackend();
  if (!ready) {
    dialog.showErrorBox(
      'Cilix · Backend no disponible',
      'El servidor Python no respondió a tiempo.\n' +
      'Revisa dependencias y Ollama, o ejecuta run.sh desde una terminal para ver los logs.'
    );
  }

  createMainWindow();
  if (process.platform !== 'darwin') createTray();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on('window-all-closed', () => {
  // En Linux mantenemos el proceso en bandeja; salir explícitamente con Quit.
  if (process.platform !== 'linux') app.quit();
});

app.on('before-quit', () => {
  app.isQuitting = true;
  stopPythonBackend();
});

process.on('SIGINT', () => { stopPythonBackend(); app.quit(); });
process.on('SIGTERM', () => { stopPythonBackend(); app.quit(); });
