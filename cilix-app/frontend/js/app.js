/* ══════════════════════════════════════════════════════════════════════════
   Cilix · Lógica de la interfaz (renderer)
   · Conecta por WebSocket con el backend FastAPI (cerebro dual local).
   · Chat minimalista con burbujas y estado (pensando/hablando).
   · Grabación de voz (STT) con codificación WAV en el navegador.
   · Reproducción de voz (TTS) sincronizada con el lip-sync del avatar.
   · Control de modo Ri/Re, voz on/off y botones de la ventana flotante.
   Todo funciona offline; sin dependencias externas más allá de las libs locales.
   ══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // Modo navegador (sin puente de Electron): marca <html> para lucir fondo propio.
  if (!window.cilix) document.documentElement.classList.add('browser');

  // ── Referencias de DOM ────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const els = {
    messages: $('messages'), input: $('input'), send: $('btn-send'), mic: $('btn-mic'),
    thinking: $('thinking'), dot: $('status-dot'), modeBadge: $('mode-badge'),
    modeSwitch: $('mode-switch'), voiceToggle: $('voice-toggle'),
    ram: $('ram-val'), cpu: $('cpu-val'), ri: $('ri-val'), re: $('re-val'),
    pin: $('btn-pin'), min: $('btn-min'), close: $('btn-close'),
  };

  const state = {
    ws: null,
    reconnectMs: 2500,
    mode: 'Ri',
    voiceEnabled: true,
    currentAudio: null,
    recording: false,
    mediaStop: null,
  };

  // ══ WebSocket ═══════════════════════════════════════════════════════════
  function wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    // El backend sirve la página, reutilizamos host (incluye el puerto 8765).
    return `${proto}://${location.host}/ws`;
  }

  function connect() {
    try {
      state.ws = new WebSocket(wsUrl());
    } catch (err) {
      console.error('[WS] no se pudo crear:', err);
      return scheduleReconnect();
    }

    state.ws.onopen = () => {
      setOnline(true);
      console.info('[WS] conectado');
    };
    state.ws.onclose = () => { setOnline(false); scheduleReconnect(); };
    state.ws.onerror = () => { /* onclose gestiona la reconexión */ };
    state.ws.onmessage = (ev) => handleMessage(JSON.parse(ev.data));
  }

  function scheduleReconnect() {
    setTimeout(() => {
      if (!state.ws || state.ws.readyState === WebSocket.CLOSED) connect();
    }, state.reconnectMs);
  }

  function send(payload) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(payload));
    } else {
      addMessage('sys', 'Sin conexión con el backend… reintentando.');
      connect();
    }
  }

  // ══ Despacho de mensajes del backend ═════════════════════════════════════
  function handleMessage(msg) {
    switch (msg.type) {
      case 'connected':
        if (msg.config) applyConfig(msg.config);
        if (msg.status) updateStatus(msg.status);
        addMessage('sys', msg.message || 'Conectada 💕');
        break;

      case 'state':
        setState(msg.state);
        break;

      case 'response':
        setState('idle');
        addMessage('ai', msg.text, msg.mode);
        if (window.CilixAvatar) window.CilixAvatar.setEmotion(msg.emotion || 'neutral');
        break;

      case 'speak':
        playSpeech(msg);
        break;

      case 'stt_result':
        if (msg.text) addMessage('user', msg.text);
        break;

      case 'mode_switched':
        setMode(msg.mode);
        addMessage('sys', `Modo ${msg.mode} activo.`);
        break;

      case 'command_result':
        addMessage('sys', formatCommandResult(msg));
        break;

      case 'settings_updated':
        state.voiceEnabled = !!msg.voice_enabled;
        updateVoiceToggle();
        break;

      case 'status':
        updateStatus(msg);
        break;

      case 'error':
        setState('idle');
        addMessage('sys', '⚠️ ' + (msg.message || 'Error'));
        break;
    }
  }

  // ══ Chat ════════════════════════════════════════════════════════════════
  function submitText() {
    const text = els.input.value.trim();
    if (!text) return;
    addMessage('user', text);
    els.input.value = '';
    setState('thinking');
    send({ type: 'chat', text, mode: state.mode });
  }

  function addMessage(role, text, mode) {
    const div = document.createElement('div');
    div.className = `msg ${role}${role === 'ai' && mode === 'Re' ? ' re' : ''}`;
    if (role === 'ai' && mode) {
      const tag = document.createElement('span');
      tag.className = 'tag';
      tag.textContent = `Cilix-${mode}`;
      div.appendChild(tag);
      div.appendChild(document.createElement('br'));
    }
    div.appendChild(document.createTextNode(text));
    els.messages.appendChild(div);
    els.messages.scrollTop = els.messages.scrollHeight;
    // Límite visual del historial
    while (els.messages.children.length > 120) els.messages.removeChild(els.messages.firstChild);
  }

  function setState(s) {
    document.body.classList.toggle('thinking', s === 'thinking');
    document.body.classList.toggle('speaking', s === 'talking');
    els.thinking.classList.toggle('hidden', s !== 'thinking');
  }

  function setOnline(on) {
    els.dot.classList.toggle('online', on);
    els.dot.classList.toggle('offline', !on);
  }

  function formatCommandResult(m) {
    if (m.success) return `💻 $ ${m.command}\n${m.output || '(sin salida)'}`;
    return `🚫 ${m.command}\n${m.error || 'ejecución bloqueada'}`;
  }

  // ══ Voz: reproducción TTS + lip-sync ══════════════════════════════════════
  function playSpeech(msg) {
    if (!msg.audio) { setState('idle'); return; }
    try {
      const bytes = Uint8Array.from(atob(msg.audio), (c) => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));

      if (state.currentAudio) { try { state.currentAudio.pause(); } catch (_) {} }
      const audio = new Audio(url);
      state.currentAudio = audio;

      audio.onplay = () => {
        setState('talking');
        // Inicia la animación de boca sincronizada con la duración real
        if (window.CilixAvatar) window.CilixAvatar.speak(msg.volume_frames || [], msg.duration || 1);
      };
      audio.onended = () => {
        setState('idle');
        URL.revokeObjectURL(url);
        if (window.CilixAvatar) window.CilixAvatar.setMouth(0);
      };
      audio.onerror = () => setState('idle');
      audio.play().catch(() => setState('idle'));
    } catch (err) {
      console.error('[TTS] error reproduciendo:', err);
      setState('idle');
    }
  }

  // ══ Voz: grabación STT (micrófono → WAV → backend) ═════════════════════════
  async function toggleMic() {
    if (state.recording) return stopRecording();
    return startRecording();
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia) {
      addMessage('sys', 'Micrófono no disponible en este entorno.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const src = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const chunks = [];

      proc.onaudioprocess = (e) => {
        chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };
      src.connect(proc);
      proc.connect(ctx.destination);

      state.recording = true;
      els.mic.classList.add('recording');
      addMessage('sys', '🎙️ Escuchando… pulsa de nuevo para enviar.');

      // Detención al pulsar otra vez: recoge el audio y lo codifica
      state.mediaStop = async () => {
        proc.onaudioprocess = null;
        proc.disconnect(); src.disconnect();
        stream.getTracks().forEach((t) => t.stop());
        const wav = encodeWav(chunks, ctx.sampleRate);
        await ctx.close();
        return wav;
      };
    } catch (err) {
      console.error('[STT] error de micrófono:', err);
      addMessage('sys', 'No se pudo acceder al micrófono.');
    }
  }

  async function stopRecording() {
    if (!state.recording || !state.mediaStop) return;
    state.recording = false;
    els.mic.classList.remove('recording');
    try {
      const wavB64 = await state.mediaStop();
      state.mediaStop = null;
      if (wavB64) {
        setState('thinking');
        send({ type: 'stt', audio: wavB64, mode: state.mode });
      }
    } catch (err) {
      console.error('[STT] error al procesar:', err);
      addMessage('sys', 'Error procesando el audio.');
    }
  }

  /* Codifica los bloques Float32 capturados a WAV PCM16 mono (base64). */
  function encodeWav(floatChunks, sampleRate) {
    const total = floatChunks.reduce((n, c) => n + c.length, 0);
    if (total === 0) return null;
    const pcm = new Int16Array(total);
    let off = 0;
    for (const chunk of floatChunks) {
      for (let i = 0; i < chunk.length; i++) {
        const s = Math.max(-1, Math.min(1, chunk[i]));
        pcm[off++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
    }
    // Cabecera WAV (44 bytes) + datos PCM
    const buf = new ArrayBuffer(44 + pcm.length * 2);
    const view = new DataView(buf);
    const wstr = (o, str) => { for (let i = 0; i < str.length; i++) view.setUint8(o + i, str.charCodeAt(i)); };
    const byteRate = sampleRate * 2;
    wstr(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); wstr(8, 'WAVE');
    wstr(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
    view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    wstr(36, 'data'); view.setUint32(40, pcm.length * 2, true);
    new Int16Array(buf, 44).set(pcm);
    // base64
    const bytes = new Uint8Array(buf);
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }

  // ══ Estado del sistema (chips) ════════════════════════════════════════════
  function updateStatus(s) {
    if (!s) return;
    els.ram.textContent = `${Math.round(s.ram_percent || 0)}%`;
    els.cpu.textContent = `${Math.round(s.cpu_percent || 0)}%`;
    els.ri.textContent = s.ri_loaded ? 'RAM' : 'off';
    els.re.textContent = s.re_loaded ? 'RAM' : 'off';
    els.ram.parentElement.classList.toggle('warn', (s.ram_percent || 0) > 85);
    if (s.mode) setMode(s.mode);
  }

  function applyConfig(cfg) {
    if (typeof cfg.voice_enabled === 'boolean') {
      state.voiceEnabled = cfg.voice_enabled;
      updateVoiceToggle();
    }
    // Cerebro único (dual_brain=false): ocultar el selector Ri/Re y el chip de Re.
    if (cfg.dual_brain === false) {
      if (els.modeSwitch) els.modeSwitch.style.display = 'none';
      const reChip = els.re && els.re.parentElement;
      if (reChip) reChip.style.display = 'none';
      state.mode = 'Ri';
      setMode('Ri');
    }
  }

  // ══ Controles de UI ════════════════════════════════════════════════════════
  function setMode(mode) {
    state.mode = mode;
    els.modeBadge.textContent = mode;
    els.modeBadge.classList.toggle('re', mode === 'Re');
    els.modeSwitch.querySelectorAll('button').forEach((b) =>
      b.classList.toggle('active', b.dataset.mode === mode));
  }

  function updateVoiceToggle() {
    els.voiceToggle.classList.toggle('on', state.voiceEnabled);
    els.voiceToggle.textContent = state.voiceEnabled ? 'ON' : 'OFF';
  }

  function bindEvents() {
    els.send.addEventListener('click', submitText);
    els.input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submitText(); });
    els.mic.addEventListener('click', toggleMic);

    els.modeSwitch.querySelectorAll('button').forEach((b) => {
      b.addEventListener('click', () => send({ type: 'switch_mode', mode: b.dataset.mode }));
    });

    els.voiceToggle.addEventListener('click', () => {
      const next = !state.voiceEnabled;
      send({ type: 'toggle_voice', enabled: next });
      state.voiceEnabled = next;
      updateVoiceToggle();
    });

    // Controles de ventana (solo dentro de Electron)
    const api = window.cilix;
    // Sin puente de Electron (modo navegador): ocultar controles inútiles.
    if (!api) {
      [els.pin, els.min, els.close].forEach((b) => { if (b) b.style.display = 'none'; });
    }
    els.close.addEventListener('click', () => api ? api.hide() : window.close());
    els.min.addEventListener('click', () => api && api.minimize());
    els.pin.addEventListener('click', () => {
      const on = !els.pin.classList.contains('active');
      els.pin.classList.toggle('active', on);
      if (api) api.setAlwaysOnTop(on);
    });
    els.pin.classList.add('active'); // fijada por defecto
  }

  // ══ Arranque ══════════════════════════════════════════════════════════════
  window.addEventListener('DOMContentLoaded', async () => {
    bindEvents();
    connect();
    if (window.CilixAvatar) window.CilixAvatar.init();
  });
})();
