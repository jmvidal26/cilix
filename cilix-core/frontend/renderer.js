/**
 * Cilix v1.2 - Renderer 100% Local
 * Sin dependencias externas - 100% Local
 */

class CilixRenderer {
    constructor() {
        this.ws = null;
        this.isConnected = false;
        this.isVoiceActive = false;
        
        this.elements = {
            statusDot: document.getElementById('status-dot'),
            statusLabel: document.getElementById('status-label'),
            stateBadge: document.getElementById('state-badge'),
            chatHistory: document.getElementById('chat-history'),
            userInput: document.getElementById('user-input'),
            micBtn: document.getElementById('mic-btn'),
            sendBtn: document.getElementById('send-btn'),
            backendLabel: document.getElementById('backend-label'),
            memLabel: document.getElementById('mem-label')
        };
        
        this.setupEventListeners();
        this.connectWebSocket();
        this.updateSystemMetrics();
        setInterval(() => this.updateSystemMetrics(), 5000);
    }
    
    setupEventListeners() {
        this.elements.userInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendMessage();
        });
        
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
                this.addMessageToChat('Cilix', `Error: ${data.message}`, 'error');
                break;
        }
    }
    
    handleChatResponse(data) {
        const message = data.message || data.text || '';
        this.addMessageToChat('Cilix', message);
        this.updateStatus('idle');
    }
    
    handleStatus(data) {
        if (data.backend) {
            this.backend = data.backend;
            this.elements.backendLabel.textContent = data.backend;
        }
        
        if (data.ram_usage !== undefined) {
            this.elements.memLabel.textContent = `${data.ram_usage}%`;
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
    
    toggleMic() {
        this.isVoiceActive = !this.isVoiceActive;
        this.elements.micBtn.classList.toggle('recording', this.isVoiceActive);
        
        if (this.isVoiceActive) {
            this.updateStatus('listening');
            if (this.ws && this.isConnected) {
                this.ws.send(JSON.stringify({ type: 'start_listening' }));
            }
        } else {
            this.updateStatus('idle');
            if (this.ws && this.isConnected) {
                this.ws.send(JSON.stringify({ type: 'stop_listening' }));
            }
        }
    }
    
    updateStatus(state) {
        const statusLabel = this.elements.statusLabel;
        const statusDot = this.elements.statusDot;
        const stateBadge = this.elements.stateBadge;
        
        statusLabel.textContent = state.toUpperCase();
        statusDot.setAttribute('data-state', state);
        
        // Actualizar badge
        const colors = {
            idle: { color: 'var(--success)', text: '● IDLE' },
            listening: { color: 'var(--cyan)', text: '● ESCUCHANDO' },
            thinking: { color: 'var(--purple)', text: '● PENSANDO' },
            executing: { color: 'var(--warning)', text: '● EJECUTANDO' },
            talking: { color: 'var(--magenta)', text: '● HABLANDO' },
            error: { color: 'var(--error)', text: '● ERROR' }
        };
        
        if (colors[state]) {
            stateBadge.style.color = colors[state].color;
            stateBadge.style.borderColor = colors[state].color.replace(')', ', 0.4)').replace('rgb', 'rgba');
            stateBadge.textContent = colors[state].text;
        }
    }
    
    updateConnectionStatus(status) {
        if (status === 'connected') {
            this.updateStatus('idle');
        }
    }
    
    updateBackendStatus() {
        const isOnline = navigator.onLine;
        const backend = isOnline ? 'Ollama (local)' : 'Offline';
        this.elements.backendLabel.textContent = backend;
    }
    
    updateSystemMetrics() {
        if (navigator.storage && navigator.storage.estimate) {
            navigator.storage.estimate().then(estimate => {
                console.log(`Uso de almacenamiento: ${estimate.usage ? (estimate.usage / 1024 / 1024).toFixed(2) + 'MB' : 'N/A'}`);
            });
        }
        
        if (this.ws && this.isConnected) {
            this.ws.send(JSON.stringify({ type: 'get_status' }));
        }
    }
    
    addMessageToChat(sender, text, type = 'normal') {
        const chatHistory = this.elements.chatHistory;
        if (!chatHistory) return;
        
        const bubble = document.createElement('div');
        bubble.className = `chat-bubble ${sender === 'Tú' ? 'user' : 'assistant'}`;
        
        bubble.innerHTML = `
            <div style="font-size:0.6rem; font-family:var(--font-mono); color:var(--cyan); margin-bottom:3px;">
                ${sender}
            </div>
            ${this.escapeHtml(text)}
        `;
        
        chatHistory.appendChild(bubble);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Cilix Renderer inicializando...');
    window.cilix = new CilixRenderer();
});

// Exportar
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CilixRenderer;
}