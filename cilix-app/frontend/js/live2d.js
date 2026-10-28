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
  // (verificados en su .cdi3.json). Nombres chinos de los switches: Param32=
  // 爱心(cariño) Param33=生气(enojo) Param35=圈圈(mareo) Param36=脸红(rubor)
  // Param37=嘟嘴(pucherito) Param38=流泪开关(llanto) Param39=左泪水(lágrima).
  // NO se tocan ParamEyeLOpen/ROpen ni ParamAngle*/Ball* (los gobierna el bucle
  // idle: parpadeo + seguimiento de cursor), para no pelear con ellos.
  const EMOTION_PARAMS = {
    neutral:      {},
    feliz:        { ParamMouthForm: 1, ParamEyeLSmile: 1, ParamEyeRSmile: 1,
                    ParamCheek: 0.6, Param36: 0.8, Param32: 0.35,
                    ParamBrowLY: 0.2, ParamBrowRY: 0.2,
                    ParamBrowLAngle: 0.3, ParamBrowRAngle: 0.3 },
    triste:       { ParamMouthForm: -0.8, ParamBrowLAngle: -1, ParamBrowRAngle: -1,
                    ParamBrowLY: -0.35, ParamBrowRY: -0.35,
                    ParamBrowLForm: -0.3, ParamBrowRForm: -0.3,
                    Param38: 1, Param39: 1 },
    enfadado:     { ParamMouthForm: -0.6, ParamBrowLForm: -1, ParamBrowRForm: -1,
                    ParamBrowLX: -0.4, ParamBrowRX: 0.4,
                    ParamBrowLAngle: 0.8, ParamBrowRAngle: 0.8,
                    ParamBrowLY: -0.4, ParamBrowRY: -0.4,
                    Param33: 1, Param36: 0.35 },
    sorprendido:  { ParamBrowLY: 1, ParamBrowRY: 1, ParamBrowLForm: 0.5, ParamBrowRForm: 0.5,
                    ParamBrowLAngle: 0.5, ParamBrowRAngle: 0.5,
                    ParamMouthForm: -0.3, Param35: 0.5, Param36: 0.3 },
    concentrado:  { ParamBrowLForm: 0.35, ParamBrowRForm: 0.35,
                    ParamBrowLX: 0.3, ParamBrowRX: -0.3,
                    ParamBrowLY: -0.15, ParamBrowRY: -0.15, ParamMouthForm: 0.15 },
  };
  // Parámetros que siempre se interpolan (vuelven a 0 = neutro al cambiar).
  const DRIVEN_PARAMS = [
    'ParamMouthForm', 'ParamEyeLSmile', 'ParamEyeRSmile',
    'ParamBrowLForm', 'ParamBrowRForm', 'ParamBrowLY', 'ParamBrowRY',
    'ParamBrowLX', 'ParamBrowRX', 'ParamBrowLAngle', 'ParamBrowRAngle',
    'ParamCheek', 'Param32', 'Param33', 'Param35', 'Param36', 'Param37',
    'Param38', 'Param39',
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
    // Paseo: desplaza el avatar a izquierda/derecha sin tocar _homeX, así el
    // arrastre manual sigue funcionando y al terminar vuelve solo a su sitio.
    _walking: false,
    _baseScale: 0,

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

        this.app.stage.addChild(this.model);
        this._layoutModel();
        // Los bounds del modelo no son fiables hasta el primer render: se
        // recalcula en el siguiente frame para evitar una escala enorme.
        requestAnimationFrame(() => this._layoutModel());
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
      // Se usan las dimensiones de la ventana (el canvas la cubre entera).
      // El renderer puede seguir en 1×1 durante el primer frame con `resizeTo`.
      const w = window.innerWidth || this.app.renderer.width || 1;
      const h = window.innerHeight || this.app.renderer.height || 1;
      // `model.width/height` incluyen la escala actual, así que se miden una
      // sola vez en escala 1. Si no, cada resize volvía a escalar en cascada.
      if (!this._baseW || !this._baseH) {
        const prev = this.model.scale.x;
        this.model.scale.set(1);
        this._baseW = this.model.width;
        this._baseH = this.model.height;
        this.model.scale.set(prev, prev);
      }
      const bw = this._baseW || 0;
      const bh = this._baseH || 0;
      if (!bw || !bh) return;
      const scale = Math.min(w / bw, (h * 0.9) / bh);
      if (!isFinite(scale) || scale <= 0) return;
      this._baseScale = scale;
      this.model.scale.set(scale);
      this._homeX = (w - bw * scale) / 2;
      this._homeY = h - bh * scale;   // apoyado en la parte inferior
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

    /* ── Paseo (actividad de aburrimiento) ──────────────────────────────── */
    /* Activa un vaivén horizontal suave. No modifica _homeX: es un offset
       que se suma en el bucle idle, así arrastrar el avatar no lo rompe. */
    setWalking(on) {
      const next = !!on;
      if (this._walking === next) return;
      this._walking = next;
      if (!next && this.model && this._baseScale) {
        this.model.scale.x = this._baseScale;   // recupera la orientación
      }
    },

    isWalking() {
      return !!this._walking;
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

          // Emociones: interpolación suave + micro-vida (no cara congelada)
          for (const p of DRIVEN_PARAMS) {
            const tgt = this._emotionTarget[p] || 0;
            const cur = this._emotionCur[p] || 0;
            const v = cur + (tgt - cur) * 0.18;   // ataque un pelín más ágil
            this._emotionCur[p] = v;
            let out = v;
            if (p === 'ParamBrowLY' || p === 'ParamBrowRY') {
              out += Math.sin(t * 0.7 + (p === 'ParamBrowRY' ? 1.3 : 0)) * 0.035;
            } else if (Math.abs(tgt) > 0.05 &&
                       (p === 'ParamCheek' || p === 'Param36' ||
                        p === 'ParamEyeLSmile' || p === 'ParamEyeRSmile')) {
              // rubor/sonrisa 'respiran' suave: la emoción se siente viva
              out += Math.sin(t * 1.3 + 0.6) * 0.04;
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

          // Paseo: vaivén amplio + pasitos (bob) y giro según la dirección.
          let walkX = 0, walkBob = 0;
          if (this._walking) {
            const vw = window.innerWidth || 800;
            const mw = Math.abs(this.model.width) || 0;
            // No salirse de la pantalla: margen disponible a cada lado.
            const space = Math.max(0, Math.min(this._homeX, vw - this._homeX - mw));
            const range = Math.min(vw * 0.24, 260, space);
            walkX = Math.sin(t * 0.85) * range;
            walkBob = Math.abs(Math.sin(t * 7)) * mh * 0.012;
            if (this._baseScale) {
              this.model.scale.x = this._baseScale *
                (Math.cos(t * 0.85) >= 0 ? 1 : -1);
            }
          }

          this.model.x = this._homeX + swayX + parX + walkX;
          this.model.y = this._homeY + breathe + talkBob + parY + walkBob;
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
