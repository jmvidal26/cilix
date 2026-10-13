const { app, BrowserWindow, ipcMain, screen } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

let mainWindow;
let pythonProcess = null;
let isDev = process.argv.includes('--dev');

// Configuración del servidor Python
const PYTHON_SERVER_PATH = path.join(__dirname, '..', 'backend', 'main.py');
const PYTHON_EXECUTABLE = 'python3';

/**
 * Inicia el servidor Python de Cilix como proceso hijo
 */
function startPythonServer() {
    console.log('🚀 Iniciando servidor Python de Cilix...');
    
    if (!fs.existsSync(PYTHON_SERVER_PATH)) {
        console.error('❌ Archivo del servidor Python no encontrado:', PYTHON_SERVER_PATH);
        return null;
    }

    const args = [PYTHON_SERVER_PATH];
    if (isDev) {
        args.push('--dev');
    }

    const pythonProcess = spawn(PYTHON_EXECUTABLE, args, {
        cwd: path.join(__dirname, '..', 'backend'),
        stdio: ['pipe', 'pipe', 'pipe']
    });

    pythonProcess.stdout.on('data', (data) => {
        const output = data.toString().trim();
        if (output) {
            console.log(`[Python Server] ${output}`);
            if (mainWindow && mainWindow.webContents) {
                mainWindow.webContents.send('python-log', output);
            }
        }
    });

    pythonProcess.stderr.on('data', (data) => {
        const error = data.toString().trim();
        if (error) {
            console.error(`[Python Error] ${error}`);
            if (mainWindow && mainWindow.webContents) {
                mainWindow.webContents.send('python-error', error);
            }
        }
    });

    pythonProcess.on('close', (code) => {
        console.log(`⚠️  Servidor Python cerrado con código: ${code}`);
    });

    pythonProcess.on('error', (err) => {
        console.error('❌ Error al iniciar servidor Python:', err.message);
    });

    return pythonProcess;
}

/**
 * Crea la ventana principal transparente de Cilix
 */
function createWindow() {
    const { width, height } = screen.getPrimaryDisplay().workAreaSize;
    
    mainWindow = new BrowserWindow({
        width: 500,
        height: 600,
        x: width - 540,
        y: 50,
        transparent: true,
        frame: false,
        alwaysOnTop: true,
        resizable: true,
        skipTaskbar: false,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js')
        }
    });

    // Cargar la interfaz web unificada (basada en pr1)
    const indexPath = path.join(__dirname, '..', 'frontend', 'unified_ui.html');
    mainWindow.loadFile(indexPath);

    // Abrir herramientas de desarrollo en modo desarrollo
    if (isDev) {
        mainWindow.webContents.openDevTools({ mode: 'detach' });
    }

    // Manejar cierre de ventana
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

/**
 * Configurar comunicación IPC entre procesos
 */
function setupIpcHandlers() {
    // Toggle visibilidad de ventana
    ipcMain.on('toggle-window-visibility', () => {
        if (mainWindow) {
            if (mainWindow.isVisible()) {
                mainWindow.hide();
            } else {
                mainWindow.show();
            }
        }
    });

    // Cerrar aplicación completamente
    ipcMain.on('quit-app', () => {
        if (pythonProcess) {
            pythonProcess.kill('SIGTERM');
        }
        app.quit();
    });
}

// Eventos de la aplicación Electron
app.whenReady().then(() => {
    console.log('🎮 Cilix Assistant v1.2 iniciando...');
    
    // Iniciar servidor Python primero
    pythonProcess = startPythonServer();
    
    // Esperar 2 segundos para que el servidor Python inicie
    setTimeout(() => {
        createWindow();
        setupIpcHandlers();
        
        console.log('✅ Cilix Assistant v1.2 lista para usar');
        console.log('📡 WebSocket disponible en: ws://localhost:8765');
    }, 2000);
});

app.on('window-all-closed', () => {
    if (process.platform !== 'linux') {
        app.quit();
    }
});

app.on('before-quit', () => {
    console.log('🛑 Cerrando Cilix Assistant...');
    
    if (pythonProcess) {
        console.log('⏳ Deteniendo servidor Python...');
        pythonProcess.kill('SIGTERM');
        
        setTimeout(() => {
            if (pythonProcess && !pythonProcess.killed) {
                pythonProcess.kill('SIGKILL');
            }
        }, 3000);
    }
});

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
    }
});

// Manejo de errores no capturados
process.on('uncaughtException', (error) => {
    console.error('💥 Error no capturado:', error);
});

process.on('unhandledRejection', (reason, promise) => {
    console.error('💥 Promesa rechazada no manejada:', reason);
});