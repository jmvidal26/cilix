/**
 * Cilix v1.2 - Unified Renderer
 * Sin dependencias externas - 100% Local
 */

class CilixUnifiedRenderer {
    constructor() {
        this.ws = null;
        this.isConnected = false;
        this.isVoiceActive = false;
        this.currentMode = 'mascot'; // 'full' o 'mascot'
        this.backend = 'Ollama'; // Gemini/Claude/Ollama
        this.messagesCount = 0;
        
        this.elements = {
            // HUD
            statusDot: document.getElementById('status-dot'),
            statusLabel: document.getElementById('status-label'),
            chatHistory: document.getElementById('chat-history'),
            userInput: document.getElementById('user-input'),
            micBtn: document.getElementById('mic-btn'),
            sendBtn: document.getElementById('send-btn'),
            toggleModeBtn: document.getElementById('toggle-mode-btn'),
            
            // Metrics
            backendLabel: document.getElementById('backend-label'),
            memLabel: document.getElementById('mem-label'),
            voiceLabel: document.getElementById('voice-label'),
            
            // Mascot
            mascotBubble: document.getElementById('mascot-speech-bubble'),
            mascotBubbleText: document.getElementById('bubble-text'),
            mascotBubbleDot: document.getElementById('bubble-status-dot'),
            mascotInput: document.getElementById('mascot-input'),
            mascotMicBtn: document.getElementById('mascot-mic-btn'),
            mascotSendBtn: document.getElementById('mascot-send-btn'),
            
            // Live2D
            canvas: document.getElementById('live2d-canvas'),
            context: null
        };
        
        this.setupEventListeners();
        this.connectWebSocket();
        this.updateSystemMetrics();
        setInterval(() => this.updateSystemMetrics(), 5000);
        
        // Inicializar Live2D canvas
        this.elements.canvas.style.display = 'block';
    }
    
    setupEventListeners() {
        // Input enter para enviar
        this.elements.userInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendMessage();
        });
        this.elements.mascotInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendMascotMessage();
        });
        
        // Live2D arrastre
        let isDragging = false;
        let startX, startY;
        
        this.elements.canvas.addEventListener('mousedown', (e) => {
            isDragging = true;
            startX = e.clientX - this.elements.canvas.offsetLeft;
            startY = e.clientY - this.elements.canvas.offsetTop;
            this.elements.canvas.classList.add('dragging');
        });
        
        window.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            const x = e.clientX - startX;
            const y = e.clientY - startY;
            this.elements.canvas.style.transform = `translate(${x}px, ${y}px)`;
        });
        
        window.addEventListener('mouseup', () => {
            isDragging = false;
            this.elements.canvas.classList.remove('dragging');
        });
        
        // Botón toggle modo
        this.elements.toggleModeBtn.addEventListener('click', () => this.toggleMascotMode());
        
        // WebSocket
        window.addEventListener('online', () => this.updateBackendStatus());
        window.addEventListener('offline', () => this.updateBackendStatus());
    }
    
    connectWebSocket() {
        const wsUrl = 'ws://localhost:8765/ws';
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('✅ WebSocket conectado');
                this.isConnected = true;
                this.updateConnectionStatus('connected');
                this.updateBackendStatus();
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleServerMessage(data);
                } catch (e) {
                    console.error('❌ Error al procesar mensaje:', e);
                }
            };
            
            this.ws.onclose = () => {
                console.log('🔌 WebSocket desconectado');
                this.isConnected = false;
                this.updateConnectionStatus('disconnected');
            };
            
            this.ws.onerror = (error) => {
                console.error('❌ Error WebSocket:', error);
                this.updateConnectionStatus('error');
            };
            
        } catch (error) {
            console.error('❌ Error al crear WebSocket:', error);
        }
    }
    
    handleServerMessage(data) {
        console.log('📨 Mensaje del servidor:', data.type);
        
        switch (data.type) {
            case 'chat_response':
                this.handleChatResponse(data);
                break;
                
            case 'status':
                this.handleStatus(data);
                break;
                
            case 'error':
                this.showBubbleMessage(`Error: ${data.message}`, 'error');
                break;
        }
    }
    
    handleChatResponse(data) {
        const message = data.message || data.text || '';
        this.showBubbleMessage(message);
        this.addMessageToChat('Cilix', message);
        this.updateStatus('idle');
    }
    
    handleStatus(data) {
        if (data.backend) {
            this.backend = data.backend;
            this.elements.backendLabel.textContent = data.backend;
        }
        
        if (data.memory_usage !== undefined) {
            this.elements.memLabel.textContent = `${data.memory_usage}%`;
            this.elements.memLabel.style.color = 
                data.memory_usage > 80 ? 'var(--error)' : 
                data.memory_usage > 60 ? 'var(--warning)' : 'var(--cyan)';
        }
    }
    
    sendMessage() {
        const message = this.elements.userInput.value.trim();
        if (!message) return;
        
        this.addMessageToChat('Tú', message);
        this.elements.userInput.value = '';
        this.updateStatus('thinking');
        
        if (this.ws && this.isConnected) {
            this.ws.send(JSON.stringify({
                type: 'chat',
                message: message
            }));
        }
    }
    
    sendMascotMessage() {
        const message = this.elements.mascotInput.value.trim();
        if (!message) return;
        
        this.addMessageToChat('Tú', message);
        this.elements.mascotInput.value = '';
        this.updateStatus('thinking');
        
        if (this.ws && this.isConnected) {
            this.ws.send(JSON.stringify({
                type: 'chat',
                message: message
            }));
        }
    }
    
    toggleMic() {
        this.isVoiceActive = !this.isVoiceActive;
        this.elements.micBtn.classList.toggle('recording', this.isVoiceActive);
        
        if (this.isVoiceActive) {
            this.updateStatus('listening');
            if (this.ws && this.isConnected) {
                this.ws.send(JSON.stringify({
                    type: 'start_listening'
                }));
            }
        } else {
            this.updateStatus('idle');
            if (this.ws && this.isConnected) {
                this.ws.send(JSON.stringify({
                    type: 'stop_listening'
                }));
            }
        }
    }
    
    toggleMascotMode() {
        this.currentMode = this.currentMode === 'mascot' ? 'full' : 'mascot';
        document.body.classList.toggle('mascot-mode', this.currentMode === 'mascot');
    }
    
    resetModelPosition() {
        this.elements.canvas.style.transform = 'translate(50%, 50%)';
    }
    
    updateStatus(state) {
        const statusLabel = this.elements.statusLabel;
        const statusDot = this.elements.statusDot;
        
        statusLabel.textContent = state.toUpperCase();
        statusDot.setAttribute('data-state', state);
        
        // Actualizar bubble
        if (this.elements.mascotBubbleDot) {
            this.elements.mascotBubbleDot.setAttribute('data-state', state);
        }
        
        // Actualizar botón de micrófono
        if (state === 'listening') {
            this.elements.micBtn.classList.add('recording');
            this.elements.mascotMicBtn.classList.add('recording');
        } else {
            this.elements.micBtn.classList.remove('recording');
            this.elements.mascotMicBtn.classList.remove('recording');
        }
    }
    
    updateConnectionStatus(status) {
        if (status === 'connected') {
            this.updateStatus('idle');
        }
    }
    
    updateBackendStatus() {
        const isOnline = navigator.onLine;
        const backend = isOnline ? this.backend : 'Offline';
        this.elements.backendLabel.textContent = backend;
    }
    
    updateSystemMetrics() {
        if (navigator.storage && navigator.storage.estimate) {
            navigator.storage.estimate().then(estimate => {
                const usage = (estimate.usage / 1024 / 1024).toFixed(2);
                // Solo mostrar si no es undefined
                if (usage !== 'NaN') {
                    // console.log(`Uso de almacenamiento: ${usage}MB`);
                }
            });
        }
        
        // Solicitar estado al servidor
        if (this.ws && this.isConnected) {
            this.ws.send(JSON.stringify({
                type: 'get_status'
            }));
        }
    }
    
    addMessageToChat(sender, text) {
        const chatHistory = this.elements.chatHistory;
        if (!chatHistory) return;
        
        const bubble = document.createElement('div');
        bubble.className = `chat-bubble ${sender === 'Tú' ? 'user' : 'assistant'}`;
        
        bubble.innerHTML = `
            <div style="font-size:0.6rem; font-family:var(--font-mono); color:var(--cyan); margin-bottom:3px;">
                ${sender}
            </div>
            ${text}
        `;
        
        chatHistory.appendChild(bubble);
        chatHistory.scrollTop = chatHistory.scrollHeight;
        
        this.messagesCount++;
        this.updateStatus('idle');
    }
    
    showBubbleMessage(text, type = 'normal') {
        const bubble = this.elements.mascotBubble;
        const textEl = this.elements.mascotBubbleText;
        
        if (!bubble || !textEl) return;
        
        textEl.textContent = text;
        bubble.classList.add('visible');
        
        if (type === 'error') {
            bubble.style.borderColor = 'var(--error)';
        } else {
            bubble.style.borderColor = 'var(--border-hot)';
        }
        
        // Ocultar después de 5 segundos
        setTimeout(() => {
            bubble.classList.remove('visible');
        }, 5000);
    }
    
    // Funciones de utilidad
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Cilix Unified Renderer inicializando...');
    window.cilix = new CilixUnifiedRenderer();
});

// Exportar
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CilixUnifiedRenderer;
}