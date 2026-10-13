/**
 * Terminal integrado para Sylix OS Core Assistant
 * Usa xterm.js para una terminal completa en la aplicación
 */

const { Terminal } = require('xterm');
const { FitAddon } = require('xterm-addon-fit');
const { WebLinksAddon } = require('xterm-addon-web-links');
const { ipcRenderer } = require('electron');
const pty = require('node-pty');

class SylixTerminal {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.options = {
            theme: {
                background: '#050a14',
                foreground: '#00f5ff',
                cursor: '#ff2d78',
                selection: 'rgba(0, 245, 255, 0.3)',
                black: '#000000',
                red: '#ff2d78',
                green: '#22d3a0',
                yellow: '#f59e0b',
                blue: '#4f46e5',
                magenta: '#8b5cf6',
                cyan: '#00f5ff',
                white: '#e2f0ff'
            },
            fontSize: 14,
            fontFamily: 'JetBrains Mono, monospace',
            cursorBlink: true,
            cursorStyle: 'bar',
            lineHeight: 1.2,
            letterSpacing: 0,
            ...options
        };

        this.terminal = null;
        this.fitAddon = null;
        this.ptyProcess = null;
        this.isActive = false;
        this.commandHistory = [];
        this.historyIndex = -1;
        this.currentCommand = '';
        
        this.init();
    }

    init() {
        // Crear terminal
        this.terminal = new Terminal(this.options);
        this.fitAddon = new FitAddon();
        this.terminal.loadAddon(this.fitAddon);
        this.terminal.loadAddon(new WebLinksAddon());
        
        // Configurar eventos del terminal
        this.setupTerminalEvents();
        
        // Crear proceso PTY
        this.createPtyProcess();
        
        // Abrir terminal en el contenedor
        const container = document.getElementById(this.containerId);
        if (container) {
            this.terminal.open(container);
            this.fitAddon.fit();
            
            // Mostrar bienvenida
            this.showWelcomeMessage();
        }
    }

    setupTerminalEvents() {
        // Evento de entrada de datos
        this.terminal.onData(data => {
            if (this.ptyProcess && this.isActive) {
                this.ptyProcess.write(data);
            }
        });

        // Evento de cambio de tamaño
        window.addEventListener('resize', () => {
            if (this.fitAddon) {
                this.fitAddon.fit();
                if (this.ptyProcess) {
                    this.ptyProcess.resize(this.terminal.cols, this.terminal.rows);
                }
            }
        });

        // Manejo de teclas especiales
        this.terminal.attachCustomKeyEventHandler((event) => {
            if (event.type === 'keydown') {
                // Ctrl + L para limpiar
                if (event.ctrlKey && event.key === 'l') {
                    this.terminal.clear();
                    return false;
                }
                
                // Ctrl + C para enviar SIGINT
                if (event.ctrlKey && event.key === 'c') {
                    if (this.ptyProcess) {
                        this.ptyProcess.kill('SIGINT');
                    }
                    return false;
                }
                
                // Ctrl + D para EOF
                if (event.ctrlKey && event.key === 'd') {
                    if (this.ptyProcess) {
                        this.ptyProcess.write('\x04');
                    }
                    return false;
                }
                
                // Flechas para navegar en el historial
                if (event.key === 'ArrowUp') {
                    this.navigateHistory(-1);
                    return false;
                }
                if (event.key === 'ArrowDown') {
                    this.navigateHistory(1);
                    return false;
                }
                
                // Tab para autocompletar
                if (event.key === 'Tab') {
                    this.handleTabCompletion();
                    return false;
                }
            }
            return true;
        });
    }

    createPtyProcess() {
        // Configuración del shell según sistema operativo
        const shell = process.platform === 'win32' ? 'powershell.exe' : process.env.SHELL || 'bash';
        
        // Opciones del proceso PTY
        const env = { ...process.env };
        env.TERM = 'xterm-256color';
        env.COLORTERM = 'truecolor';
        env.PS1 = '\\[\\e[1;36m\\]\\u@\\h\\[\\e[0m\\]:\\[\\e[1;35m\\]\\w\\[\\e[0m\\]\\$ ';
        
        // Crear proceso PTY
        this.ptyProcess = pty.spawn(shell, [], {
            name: 'xterm-256color',
            cols: this.terminal.cols,
            rows: this.terminal.rows,
            cwd: process.env.HOME || process.cwd(),
            env: env,
            encoding: 'utf8'
        });

        // Configurar salida del proceso
        this.ptyProcess.onData(data => {
            this.terminal.write(data);
        });

        // Manejar cierre del proceso
        this.ptyProcess.onExit(({ exitCode, signal }) => {
            this.isActive = false;
            this.terminal.write(`\r\nProcess exited with code ${exitCode}${signal ? ` (signal: ${signal})` : ''}\r\n`);
            
            // Reiniciar shell después de 1 segundo
            setTimeout(() => {
                this.createPtyProcess();
            }, 1000);
        });

        this.isActive = true;
    }

    showWelcomeMessage() {
        const welcomeMessage = `
\x1b[1;36m╔══════════════════════════════════════════════════════════╗\x1b[0m
\x1b[1;36m║           SYLIX OS CORE ASSISTANT - TERMINAL             ║\x1b[0m
\x1b[1;36m╚══════════════════════════════════════════════════════════╝\x1b[0m

\x1b[1;35mWelcome to Sylix OS Core Terminal\x1b[0m
\x1b[1;33mVersion:\x1b[0m 1.0.0 | \x1b[1;33mShell:\x1b[0m ${process.env.SHELL || 'bash'}
\x1b[1;33mShortcuts:\x1b[0m Ctrl+L (clear) | Ctrl+C (interrupt) | Ctrl+D (EOF)
\x1b[1;33mHistory:\x1b[0m Arrow Up/Down | \x1b[1;33mAuto-complete:\x1b[0m Tab

\x1b[1;32mConnected to system monitoring and automation APIs\x1b[0m
\x1b[1;32mType 'sylix-help' for Sylix-specific commands\x1b[0m

\x1b[1;34m────────────────────────────────────────────────────────────\x1b[0m
\r\n`;
        
        this.terminal.write(welcomeMessage);
        
        // Añadir comando de ayuda personalizado al historial
        this.commandHistory.push('sylix-help');
    }

    navigateHistory(direction) {
        if (this.commandHistory.length === 0) return;
        
        // Actualizar índice del historial
        this.historyIndex += direction;
        
        // Limitar índices
        if (this.historyIndex < 0) {
            this.historyIndex = -1;
            this.currentCommand = '';
        } else if (this.historyIndex >= this.commandHistory.length) {
            this.historyIndex = this.commandHistory.length - 1;
        }
        
        // Obtener comando del historial
        if (this.historyIndex >= 0) {
            const command = this.commandHistory[this.historyIndex];
            this.currentCommand = command;
            
            // Limpiar línea actual y escribir comando
            this.terminal.write('\x1b[2K\r'); // Limpiar línea
            this.terminal.write(`\x1b[1;36m${process.env.USER || 'user'}@sylix:\x1b[1;35m${process.cwd()}\x1b[0m$ ${command}`);
        } else {
            this.terminal.write('\x1b[2K\r'); // Limpiar línea
            this.terminal.write(`\x1b[1;36m${process.env.USER || 'user'}@sylix:\x1b[1;35m${process.cwd()}\x1b[0m$ `);
        }
    }

    handleTabCompletion() {
        // Implementación básica de autocompletado
        const line = this.terminal.buffer.active.getLine(this.terminal.buffer.active.cursorY);
        const text = line ? line.translateToString(false) : '';
        
        // Dividir línea actual para obtener palabra actual
        const words = text.trim().split(/\s+/);
        const currentWord = words[words.length - 1] || '';
        
        if (currentWord) {
            // Comandos comunes para autocompletar
            const commonCommands = [
                'ls', 'cd', 'pwd', 'cp', 'mv', 'rm', 'mkdir', 'touch',
                'cat', 'grep', 'find', 'ps', 'top', 'htop', 'df', 'free',
                'sudo', 'apt', 'systemctl', 'journalctl', 'nmap', 'ping',
                'git', 'python', 'node', 'npm', 'docker', 'podman'
            ];
            
            const sylixCommands = [
                'sylix-help', 'sylix-system', 'sylix-monitor', 'sylix-services',
                'sylix-scripts', 'sylix-logs', 'sylix-automate'
            ];
            
            const allCommands = [...commonCommands, ...sylixCommands];
            
            // Buscar coincidencias
            const matches = allCommands.filter(cmd => 
                cmd.startsWith(currentWord.toLowerCase())
            );
            
            if (matches.length === 1) {
                // Autocompletar
                const completion = matches[0].slice(currentWord.length);
                this.ptyProcess.write(completion);
            } else if (matches.length > 1) {
                // Mostrar opciones
                this.terminal.write('\r\n');
                matches.forEach(cmd => {
                    this.terminal.write(`\x1b[1;36m${cmd}\x1b[0m  `);
                });
                this.terminal.write('\r\n');
                
                // Restaurar prompt
                this.terminal.write(`\x1b[1;36m${process.env.USER || 'user'}@sylix:\x1b[1;35m${process.cwd()}\x1b[0m$ ${text}`);
            }
        }
    }

    executeSylixCommand(command) {
        const cmd = command.trim().toLowerCase();
        
        switch (cmd) {
            case 'sylix-help':
                this.showSylixHelp();
                break;
                
            case 'sylix-system':
                this.showSystemInfo();
                break;
                
            case 'sylix-monitor':
                this.startSystemMonitor();
                break;
                
            case 'sylix-services':
                this.listServices();
                break;
                
            case 'sylix-scripts':
                this.listScripts();
                break;
                
            case 'sylix-logs':
                this.showLogsMenu();
                break;
                
            case 'sylix-automate':
                this.showAutomationMenu();
                break;
                
            default:
                this.terminal.write(`\x1b[1;31mUnknown Sylix command: ${command}\x1b[0m\r\n`);
                this.terminal.write(`Type 'sylix-help' for available commands\r\n`);
        }
    }

    showSylixHelp() {
        const helpText = `
\x1b[1;36mSYLIX OS CORE COMMANDS\x1b[0m
────────────────────────────────────────────────────────────

\x1b[1;35mSystem Information:\x1b[0m
  sylix-system      Show detailed system information
  sylix-monitor     Start real-time system monitoring

\x1b[1;35mService Management:\x1b[0m
  sylix-services    List and manage systemd services

\x1b[1;35mScript Management:\x1b[0m
  sylix-scripts     List and manage Sylix scripts

\x1b[1;35mLogs:\x1b[0m
  sylix-logs        View system logs (syslog, auth, etc.)

\x1b[1;35mAutomation:\x1b[0m
  sylix-automate    Desktop automation tools

\x1b[1;35mIntegration:\x1b[0m
  All standard Linux commands work normally
  Press Tab for auto-completion
  Use Arrow Up/Down for command history

\x1b[1;34m────────────────────────────────────────────────────────────\x1b[0m
\r\n`;
        
        this.terminal.write(helpText);
    }

    async showSystemInfo() {
        try {
            this.terminal.write('\x1b[1;33mFetching system information...\x1b[0m\r\n');
            
            // Usar la API de Electron para obtener información del sistema
            const info = await window.electronAPI.getSystemInfo();
            
            if (info && !info.error) {
                const { cpu, memory, os } = info;
                
                const infoText = `
\x1b[1;36mSYSTEM INFORMATION\x1b[0m
────────────────────────────────────────────────────────────
\x1b[1;35mOS:\x1b[0m ${os.distro} ${os.release} (${os.arch})
\x1b[1;35mKernel:\x1b[0m ${os.kernel}
\x1b[1;35mUptime:\x1b[0m ${os.uptime}

\x1b[1;35mCPU:\x1b[0m ${cpu.manufacturer} ${cpu.brand}
\x1b[1;35mCores:\x1b[0m ${cpu.cores} (${cpu.physicalCores} physical)
\x1b[1;35mSpeed:\x1b[0m ${cpu.speed} GHz
\x1b[1;35mUsage:\x1b[0m ${cpu.usage}%

\x1b[1;35mMemory:\x1b[0m
  Total: ${(memory.total / 1024 / 1024 / 1024).toFixed(2)} GB
  Used:  ${(memory.used / 1024 / 1024 / 1024).toFixed(2)} GB (${memory.usage}%)
  Free:  ${(memory.free / 1024 / 1024 / 1024).toFixed(2)} GB

\x1b[1;35mLoad Average:\x1b[0m ${os.loadavg.join(', ')}
────────────────────────────────────────────────────────────
\r\n`;
                
                this.terminal.write(infoText);
            } else {
                this.terminal.write(`\x1b[1;31mError getting system info: ${info.error}\x1b[0m\r\n`);
            }
        } catch (error) {
            this.terminal.write(`\x1b[1;31mError: ${error.message}\x1b[0m\r\n`);
        }
    }

    startSystemMonitor() {
        this.terminal.write('\x1b[1;33mStarting system monitor...\x1b[0m\r\n');
        this.terminal.write('\x1b[1;32mPress Ctrl+C to stop monitoring\x1b[0m\r\n\r\n');
        
        // Ejemplo de monitoreo básico (en una aplicación real esto sería más complejo)
        const monitorInterval = setInterval(() => {
            if (this.ptyProcess && this.isActive) {
                // En una implementación real, aquí se obtendrían métricas en tiempo real
                const timestamp = new Date().toLocaleTimeString();
                this.terminal.write(`\x1b[1;36m[${timestamp}]\x1b[0m Monitoring active...\r\n`);
            } else {
                clearInterval(monitorInterval);
            }
        }, 2000);
        
        // Detectar Ctrl+C para detener
        const originalKill = this.ptyProcess.kill;
        this.ptyProcess.kill = function(signal) {
            if (signal === 'SIGINT') {
                clearInterval(monitorInterval);
                this.terminal.write('\x1b[1;33mSystem monitor stopped\x1b[0m\r\n');
            }
            return originalKill.apply(this, arguments);
        }.bind(this);
    }

    listServices() {
        this.terminal.write('\x1b[1;33mFetching services...\x1b[0m\r\n');
        
        // Comando para listar servicios
        this.ptyProcess.write('systemctl list-units --type=service --no-pager | head -20\r\n');
    }

    listScripts() {
        this.terminal.write('\x1b[1;33mListing Sylix scripts...\x1b[0m\r\n');
        
        // Comando para listar scripts
        this.ptyProcess.write('ls -la ~/.sylix/scripts/ 2>/dev/null || echo "No scripts found"\r\n');
    }

    showLogsMenu() {
        const menu = `
\x1b[1;36mSYSTEM LOGS MENU\x1b[0m
────────────────────────────────────────────────────────────
\x1b[1;35mAvailable logs:\x1b[0m
  1. System logs (syslog)
  2. Authentication logs (auth.log)
  3. Kernel logs (kern.log)
  4. Package manager logs (dpkg.log)
  5. System journal (journalctl)

\x1b[1;35mUsage:\x1b[0m
  tail -f /var/log/syslog    # Follow system logs
  journalctl -f              # Follow system journal
  sudo dmesg                 # Kernel messages

\x1b[1;35mQuick commands:\x1b[0m
  sylix-logs-tail            # Tail system logs
  sylix-logs-journal         # Show journal

\x1b[1;34m────────────────────────────────────────────────────────────\x1b[0m
\r\n`;
        
        this.terminal.write(menu);
    }

    showAutomationMenu() {
        const menu = `
\x1b[1;36mDESKTOP AUTOMATION MENU\x1b[0m
────────────────────────────────────────────────────────────
\x1b[1;35mAvailable automation commands:\x1b[0m

\x1b[1;33mWindow Management:\x1b[0m
  wmctrl -l                  # List windows
  wmctrl -a <WIN>           # Focus window
  wmctrl -r <WIN> -e ...    # Move/resize window

\x1b[1;33mDesktop Control:\x1b[0m
  xdotool getmouselocation   # Get mouse position
  xdotool mousemove X Y      # Move mouse
  xdotool click 1            # Left click

\x1b[1;33mScreenshots:\x1b[0m
  scrot screenshot.png       # Take screenshot
  gnome-screenshot -a        # Area screenshot

\x1b[1;33mSystem Information:\x1b[0m
  inxi -Fxz                  # Full system info
  neofetch                   # System info with logo
  screenfetch                # Alternative to neofetch

\x1b[1;34m────────────────────────────────────────────────────────────\x1b[0m
\r\n`;
        
        this.terminal.write(menu);
    }

    resize(cols, rows) {
        if (this.ptyProcess) {
            this.ptyProcess.resize(cols, rows);
        }
        if (this.fitAddon) {
            this.fitAddon.fit();
        }
    }

    clear() {
        if (this.terminal) {
            this.terminal.clear();
        }
    }

    focus() {
        if (this.terminal) {
            this.terminal.focus();
        }
    }

    destroy() {
        if (this.ptyProcess) {
            this.ptyProcess.kill();
            this.ptyProcess = null;
        }
        if (this.terminal) {
            this.terminal.dispose();
            this.terminal = null;
        }
        this.isActive = false;
    }
}

// Exportar para uso global
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SylixTerminal;
} else {
    window.SylixTerminal = SylixTerminal;
}