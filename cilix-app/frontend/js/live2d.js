/* ══════════════════════════════════════════════════════════════════════════
   Cilix · Controlador del avatar Live2D (VTuber)
   Renderiza el modelo Cubism 4 con Pixi.js + pixi-live2d-display y expone una
   API sencilla para: cambiar de emoción (expresión) y sincronizar los labios
   con la voz (lip-sync) a partir de la envolvente de volumen del TTS.
   Si el modelo o las librerías no están disponibles, degrada al orbe de
   respaldo sin romper la interfaz.
   ══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const MODEL_URL = '/models/design_genius_white/Design_genius(1).model3.json';

  // Mapa emoción → parámetros REALES del modelo design_genius_white
  // (verificados en su .cdi3.json: ParamMouthForm=sonrisa, ParamBrow*=cejas,
  //  ParamCheek=rubor, Param33=enojo, Param38=llanto). NO se usa ParamEyeLOpen
  //  para no pisar el parpadeo automático del modelo.
  const EMOTION_PARAMS = {
    neutral:      {},
    feliz:        { ParamMouthForm: 1, ParamEyeLSmile: 1, ParamEyeRSmile: 1, ParamCheek: 0.5 },
    triste:       { ParamMouthForm: -0.6, ParamBrowLAngle: -1, ParamBrowRAngle: -1,
                    ParamBrowLY: -0.4, ParamBrowRY: -0.4, Param38: 1 },
    enfadado:     { ParamMouthForm: -0.5, ParamBrowLForm: -1, ParamBrowRForm: -1, Param33: 1 },
    sorprendido:  { ParamBrowLY: 1, ParamBrowRY: 1, ParamMouthForm: -0.2 },
    concentrado:  { ParamBrowLForm: 0.4, ParamBrowRForm: 0.4 },
  };
  // Parámetros que siempre se interpolan (vuelven a 0 = neutro al cambiar).
  const DRIVEN_PARAMS = [
    'ParamMouthForm', 'ParamEyeLSmile', 'ParamEyeRSmile',
    'ParamBrowLForm', 'ParamBrowRForm', 'ParamBrowLY', 'ParamBrowRY',
    'ParamBrowLAngle', 'ParamBrowRAngle', 'ParamCheek', 'Param33', 'Param38',
  ];

  const CilixAvatar = {
    app: null,          // PIXI.Application
    model: null,        // Live2DModel
    ready: false,
    mouthTarget: 0,     // apertura objetivo (0..1)
    mouthCurrent: 0,    // apertura suavizada
    _emotionTarget: {}, // valores objetivo por parámetro de emoción
    _emotionCur: {},    // valores actuales interpolados
    _raf: null,
    _lipTimer: null,
    _talking: false,
    // Movimiento/idle del avatar
    _homeX: 0, _homeY: 0,     // posición ancla (respeta el arrastre)
    _t0: 0,
    _blinkStart: -1, _nextBlinkAt: 1.2,
    _pointer: { x: 0, y: 0, active: false },

    /* ── Inicialización ─────────────────────────────────────────────────── */
    async init() {
      const canvas = document.getElementById('live2d-canvas');
      const libsOk = typeof PIXI !== 'undefined' && PIXI.live2d &&
                     typeof Live2DCubismCore !== 'undefined';

      if (!libsOk) {
        console.warn('[Live2D] librerías no disponibles → orbe de respaldo');
        return this._showFallback();
      }

      try {
        this.app = new PIXI.Application({
          view: canvas,
          resizeTo: window,
          backgroundAlpha: 0,      // transparente para overlay
          // ── AHORRO DE RAM/VRAM ──────────────────────────────
          resolution: 1,           // evita el escalado x2/x3 en pantallas HiDPI
          autoDensity: false,
          antialias: false,        // el suavizado consume memoria de más
          powerPreference: 'low-power',
          autoStart: true,
        });

        this.model = await PIXI.live2d.Live2DModel.from(MODEL_URL, {
          autoInteract: false,     // la UI no debe capturar el canvas
        });

        this._layoutModel();
        this.app.stage.addChild(this.model);
        window.addEventListener('resize', () => this._layoutModel());
        this._enableDrag();
        this._enableEyeTracking();

        this.ready = true;
        document.getElementById('avatar-fallback')?.classList.add('hidden');
        this._startIdleLoop();
        console.info('[Live2D] modelo cargado ✔');
      } catch (err) {
        console.warn('[Live2D] error cargando modelo:', err);
        this._showFallback();
      }
    },

    /* Permite arrastrar el avatar con el ratón/dedo sobre el canvas.
       El arrastre fija _homeX/_homeY; el bucle idle añade encima el
       balanceo/respiración, así que nunca 'pelean' con la posición. */
    _enableDrag() {
      const canvas = this.app.view;
      let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;

      canvas.addEventListener('pointerdown', (e) => {
        if (!this.model) return;
        dragging = true;
        sx = e.clientX; sy = e.clientY;
        ox = this._homeX; oy = this._homeY;
        canvas.classList.add('dragging');
        try { canvas.setPointerCapture(e.pointerId); } catch (_) {}
      });
      canvas.addEventListener('pointermove', (e) => {
        if (!dragging || !this.model) return;
        this._homeX = ox + (e.clientX - sx);
        this._homeY = oy + (e.clientY - sy);
      });
      const stop = (e) => {
        dragging = false;
        canvas.classList.remove('dragging');
        try { canvas.releasePointerCapture(e.pointerId); } catch (_) {}
      };
      canvas.addEventListener('pointerup', stop);
      canvas.addEventListener('pointercancel', stop);
    },

    /* Registra el cursor para que la mirada/cabeza sigan al usuario. */
    _enableEyeTracking() {
      window.addEventListener('pointermove', (e) => {
        const w = window.innerWidth || 1, h = window.innerHeight || 1;
        this._pointer.x = (e.clientX / w) * 2 - 1;   // -1..1
        this._pointer.y = (e.clientY / h) * 2 - 1;
        this._pointer.active = true;
      }, { passive: true });
    },

    /* Encuentra y centra/escala el modelo según la ventana. */
    _layoutModel() {
      if (!this.model || !this.app) return;
      const w = this.app.renderer.width / this.app.renderer.resolution;
      const h = this.app.renderer.height / this.app.renderer.resolution;
      const scale = Math.min(w / this.model.width, (h * 0.9) / this.model.height);
      this.model.scale.set(scale);
      this._homeX = (w - this.model.width) / 2;
      this._homeY = h - this.model.height;   // apoyado en la parte inferior
      this.model.x = this._homeX;
      this.model.y = this._homeY;
    },

    _showFallback() {
      const fb = document.getElementById('avatar-fallback');
      if (fb) fb.classList.remove('hidden');
      const canvas = document.getElementById('live2d-canvas');
      if (canvas) canvas.style.display = 'none';
      // El fallback también reacciona a la voz (pulso del orbe)
      this._startFallbackPulse();
    },

    /* ── Emoción ────────────────────────────────────────────────────────── */
    setEmotion(emotion) {
      if (!this.ready || !this.model) return;
      const target = EMOTION_PARAMS[emotion] || EMOTION_PARAMS.neutral;
      // Mapa completo: todos los controlados → 0 salvo los de la emoción activa,
      // así al cambiar de emoción la cara 'suelta' la anterior.
      const map = {};
      for (const p of DRIVEN_PARAMS) map[p] = (target[p] != null) ? target[p] : 0;
      this._emotionTarget = map;
    },

    /* Escribe un parámetro en el Cubism4 de forma tolerante a la API. */
    _setParam(id, value) {
      const core = this.model && this.model.internalModel && this.model.internalModel.coreModel;
      if (!core) return;
      try {
        if (typeof core.setParameterValueById === 'function') {
          core.setParameterValueById(id, value);   // API Cubism 4
        } else if (typeof core.setParameterFloatById === 'function') {
          core.setParameterFloatById(id, value);    // fallback Cubism 2
        }
      } catch (_) { /* parámetro inexistente en este modelo */ }
    },

    /* ── Lip-sync ───────────────────────────────────────────────────────── */
    /**
     * Reproduce una secuencia de fotogramas de volumen sincronizados con el
     * audio que ya está sonando en el frontend.
     * @param {number[]} frames  envolvente 0..1 (≈25 fps)
     * @param {number}   duration segundos de audio
     */
    speak(frames, duration) {
      if (!Array.isArray(frames) || frames.length === 0) return;
      this._talking = true;
      clearInterval(this._lipTimer);

      const fps = frames.length / (duration || 1);
      const stepMs = 1000 / Math.max(1, fps);
      let i = 0;

      this._lipTimer = setInterval(() => {
        if (i >= frames.length) {
          clearInterval(this._lipTimer);
          this._lipTimer = null;
          this._talking = false;
          this.mouthTarget = 0;
          return;
        }
        this.mouthTarget = frames[i++];
      }, stepMs);
    },

    /* Fija la apertura de boca (0..1) manualmente. */
    setMouth(value) {
      this.mouthTarget = Math.max(0, Math.min(1, value));
    },

    /* ── Bucle de animación (suavizado) ─────────────────────────────────── */
    _startIdleLoop() {
      this._t0 = performance.now() / 1000;
      const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
      const apply = () => {
        if (this.ready && this.model) {
          const t = performance.now() / 1000 - this._t0;
          const mw = this.model.width || 300;
          const mh = this.model.height || 300;

          // Emociones: interpolación suave + micro-flutter en cejas (no congelada)
          for (const p of DRIVEN_PARAMS) {
            const tgt = this._emotionTarget[p] || 0;
            const cur = this._emotionCur[p] || 0;
            const v = cur + (tgt - cur) * 0.15;
            this._emotionCur[p] = v;
            let out = v;
            if (p === 'ParamBrowLY' || p === 'ParamBrowRY') {
              out += Math.sin(t * 0.7 + (p === 'ParamBrowRY' ? 1.3 : 0)) * 0.03;
            }
            this._setParam(p, clamp(out, -1, 1));
          }

          // Lip-sync: abre rápido, cierra suave + curva gamma (boca expresiva)
          const rate = this.mouthTarget > this.mouthCurrent ? 0.5 : 0.3;
          this.mouthCurrent += (this.mouthTarget - this.mouthCurrent) * rate;
          this._setParam('ParamMouthOpenY', clamp(Math.pow(this.mouthCurrent, 0.8), 0, 1));

          // Parpadeo natural (ParamEyeLOpen/ROpen sí existen en este modelo)
          if (t >= this._nextBlinkAt) {
            this._blinkStart = t;
            this._nextBlinkAt = t + 2.6 + Math.random() * 4.2;
          }
          let eyeOpen = 1;
          const bd = t - this._blinkStart;
          if (this._blinkStart >= 0 && bd >= 0 && bd < 0.14) {
            const u = bd / 0.14;
            eyeOpen = Math.max(0.05, u < 0.5 ? 1 - u / 0.5 : (u - 0.5) / 0.5);
          }
          this._setParam('ParamEyeLOpen', eyeOpen);
          this._setParam('ParamEyeROpen', eyeOpen);

          // Movimiento: respiración + balanceo + parallax al cursor + cabeceo
          const breathe = Math.sin(t * 1.1) * mh * 0.006;
          const swayX = Math.sin(t * 0.45) * mw * 0.006;
          let parX = 0, parY = 0;
          if (this._pointer.active) {
            parX = this._pointer.x * mw * 0.02;
            parY = this._pointer.y * mh * 0.015;
            // mirada/cabeza siguen al cursor (no-op si el modelo no los tiene)
            this._setParam('ParamEyeBallX', clamp(this._pointer.x, -1, 1));
            this._setParam('ParamEyeBallY', clamp(-this._pointer.y, -1, 1));
            this._setParam('ParamAngleX', this._pointer.x * 12);
            this._setParam('ParamAngleY', this._pointer.y * 8);
            this._setParam('ParamAngleZ', -this._pointer.x * 6);
          } else {
            this._setParam('ParamAngleX', Math.sin(t * 0.3) * 4);
            this._setParam('ParamAngleZ', Math.sin(t * 0.2) * 3);
          }
          const talkBob = this._talking ? Math.sin(t * 6) * mh * 0.004 : 0;
          this.model.x = this._homeX + swayX + parX;
          this.model.y = this._homeY + breathe + talkBob + parY;
        }
        this._raf = requestAnimationFrame(apply);
      };
      apply();
    },

    /* Respiración/idle del orbe de respaldo. */
    _startFallbackPulse() {
      const orb = document.querySelector('.orb');
      if (!orb) return;
      const tick = () => {
        const scale = this._talking ? 1 + this.mouthTarget * 0.25 : 1;
        orb.style.transform = `scale(${scale.toFixed(3)})`;
        requestAnimationFrame(tick);
      };
      tick();
    },
  };

  window.CilixAvatar = CilixAvatar;
})();
