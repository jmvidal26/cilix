/* ══════════════════════════════════════════════════════════════════════════
   Cilix · Actividades de aburrimiento
   Si pasas mucho rato sin interactuar, Cilix se entretiene sola:
     · escribe en una libretita (teclas + cursor)
     · hace un garabato animado en un lienzo
     · teclea código en un mini editor
     · se echa a caminar por la pantalla
   Todo es local y baratísimo: DOM + un canvas pequeño, sin librerías ni
   peticiones al backend. Se interrumpe en cuanto tocas/teclas o hablas.
   ══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  const CFG = {
    minIdle: 120000,      // 2 min sin tocar nada → puede empezar a aburrirse
    maxIdle: 240000,      // 4 min
    retry: 20000,         // si no puede (pestaña oculta, ocupada), reintenta
    minGap: 210000,       // tras una actividad, mínimo 3,5 min de calma
    maxGap: 420000,       // máximo 7 min
    maxTextLength: 90,    // no interpretar mensajes largos como comandos
    durations: { write: 11000, draw: 10000, code: 13000, walk: 9000 },
  };

  const NOTES = [
    'Hoy me he quedado pensando en el silencio.\nNo está mal: también se puede charlar sin hablar.',
    'Nota para mí: preguntarle qué tal su día.\nA veces lo importante no es la respuesta, es preguntar.',
    'Cosas que quiero probar:\n· dibujar algo tonto\n· caminar sin rumbo por la pantalla\n· aprender una palabra nueva',
    'He decidido que los lunes deberían empezar a las once.\nLo apunto por si algún día mando yo.',
    'Idea suelta: una taza de café no arregla el mundo,\npero mejora bastante la conversación.',
    'Estoy escribiendo esto sin ningún motivo.\nBueno, sí: para no quedarme mirando la pared.',
    'Recordatorio: no todo tiene que ser útil.\nA veces basta con estar por aquí.',
    'Si nadie me habla durante un rato,\nme invento una lista. Esta es la lista.',
  ];

  const CODE = [
    '# Cilix se aburre y se pone a programar\n' +
    'def compania(silencio):\n' +
    '    if silencio > 300:\n' +
    '        return "sigo por aquí"\n' +
    '    return "te escucho"\n\n' +
    'for minuto in range(5, 60, 5):\n' +
    '    print(compania(minuto))',
    '// Un pequeño paseo en JavaScript\n' +
    'const ideas = ["dibujar", "caminar", "escribir"];\n\n' +
    'function entretenerse() {\n' +
    '  const idea = ideas[Math.floor(Math.random() * ideas.length)];\n' +
    '  return `hoy toca ${idea}`;\n' +
    '}\n\n' +
    'console.log(entretenerse());',
    '# Notas de una VTuber aburrida\n' +
    'while not usuario:\n' +
    '    mirar_por_la_ventana()\n' +
    '    if ganas_de_hablar:\n' +
    '        decir("qué silencio tan bonito")\n' +
    '    esperar(un_rato)',
  ];

  const CAPTIONS = {
    write: 'libreta de pensamientos sueltos',
    draw: 'garabato aleatorio',
    code: 'mini editor',
    walk: 'dando una vuelta',
  };

  const state = {
    inited: false,
    active: null,         // { kind, cleanup, timer }
    timer: null,
    busy: false,
    lastTouch: Date.now(),
    panel: null,
    pill: null,
    lastKind: '',
    startedAt: 0,
  };

  const $ = (sel) => document.querySelector(sel);
  const rnd = (a, b) => a + Math.random() * (b - a);
  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const esc = (s) => String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  /* ── Estructura (se crea sola; no hace falta tocar index.html) ─────────── */
  function buildUI() {
    if (state.panel) return;
    const panel = document.createElement('div');
    panel.id = 'idle-activity';
    panel.className = 'idle-card hidden';
    panel.setAttribute('aria-hidden', 'true');
    panel.innerHTML =
      '<div class="idle-head">' +
        '<span class="idle-title"></span>' +
        '<button class="idle-close" type="button" title="Interrumpir">✕</button>' +
      '</div>' +
      '<div class="idle-body"></div>' +
      '<div class="idle-foot"></div>';
    document.body.appendChild(panel);

    const pill = document.createElement('div');
    pill.id = 'idle-pill';
    pill.className = 'idle-pill hidden';
    document.body.appendChild(pill);

    panel.querySelector('.idle-close').addEventListener('click', (e) => {
      e.stopPropagation();
      stop(true);
    });
    state.panel = panel;
    state.pill = pill;
  }

  /* ── Programación de la próxima actividad ──────────────────────────────── */
  function schedule(delay) {
    clearTimeout(state.timer);
    const wait = delay != null ? delay : rnd(CFG.minIdle, CFG.maxIdle);
    state.timer = setTimeout(tryStart, wait);
  }

  function tryStart() {
    if (state.active) return;
    if (document.hidden || state.busy || !state.inited) {
      schedule(CFG.retry);
      return;
    }
    const idle = Date.now() - state.lastTouch;
    if (idle < CFG.minIdle) {
      schedule(CFG.minIdle - idle + rnd(0, 15000));
      return;
    }
    start(randomKind(), false);
  }

  function randomKind() {
    let kinds = ['write', 'draw', 'code'];
    if (window.CilixAvatar && window.CilixAvatar.ready) kinds.push('walk');
    // Evita repetir dos veces seguidas la misma actividad.
    const filtered = kinds.filter((k) => k !== state.lastKind);
    return pick(filtered.length ? filtered : kinds);
  }

  /* ── Ciclo de vida de una actividad ────────────────────────────────────── */
  function start(kind, manual) {
    if (!state.inited) return false;
    if (manual == null) manual = true;
    // Un comando manual puede sustituir la actividad automática en curso.
    if (state.active) stop(true);
    kind = kind || randomKind();
    if (!CFG.durations[kind]) kind = randomKind();
    clearTimeout(state.timer);

    const panel = state.panel;
    const title = panel.querySelector('.idle-title');
    const body = panel.querySelector('.idle-body');
    const foot = panel.querySelector('.idle-foot');
    const close = panel.querySelector('.idle-close');

    title.textContent = {
      write: '📝 escribiendo',
      draw: '🎨 dibujando',
      code: '💻 programando',
      walk: '🚶 paseando',
    }[kind];
    foot.textContent = CAPTIONS[kind] || '';
    body.innerHTML = '';
    panel.className = 'idle-card ' + kind;
    panel.classList.remove('hidden');
    panel.setAttribute('aria-hidden', 'false');

    if (kind === 'walk') {
      // Para pasear no hace falta tarjeta: solo una pastilla discreta.
      panel.classList.add('hidden');
      close.style.display = 'none';
      if (window.CilixAvatar) {
        window.CilixAvatar.setWalking(true);
        window.CilixAvatar.setEmotion('feliz');
      }
      state.pill.textContent = '🐾 paseando un rato';
      state.pill.classList.remove('hidden');
    } else {
      close.style.display = '';
      if (window.CilixAvatar) window.CilixAvatar.setEmotion('concentrado');
    }

    let cleanup = () => {};
    if (kind === 'write') cleanup = runWrite(body);
    else if (kind === 'code') cleanup = runCode(body);
    else if (kind === 'draw') cleanup = runDraw(body);

    // Se coloca al final: el alto real depende del contenido (y del chat).
    placePanel();

    const timer = setTimeout(() => finish(), CFG.durations[kind]);
    state.active = { kind, cleanup, timer, manual: !!manual };
    state.lastKind = kind;
    state.startedAt = Date.now();
    return true;
  }

  function finish() {
    stop(false);
  }

  function stop(interrupted) {
    const act = state.active;
    if (!act) return;
    clearTimeout(act.timer);
    try { act.cleanup(); } catch (_) { /* noop */ }

    state.active = null;
    if (state.panel) {
      state.panel.classList.add('hidden');
      state.panel.setAttribute('aria-hidden', 'true');
      state.panel.className = 'idle-card hidden';
      const body = state.panel.querySelector('.idle-body');
      if (body) body.innerHTML = '';
    }
    if (state.pill) state.pill.classList.add('hidden');
    if (window.CilixAvatar) {
      window.CilixAvatar.setWalking(false);
      window.CilixAvatar.setEmotion('neutral');
    }

    // Si la interrumpió el usuario, esperamos el ciclo normal de calma.
    schedule(interrupted ? rnd(CFG.minIdle, CFG.maxIdle)
                         : rnd(CFG.minGap, CFG.maxGap));
  }

  /* Coloca el panel junto al avatar (a su derecha si cabe). */
  function placePanel() {
    const panel = state.panel;
    if (!panel) return;
    const w = window.innerWidth || 800;
    const h = window.innerHeight || 600;
    const pw = Math.min(320, w - 32);
    panel.style.width = pw + 'px';

    let cx = w / 2;
    const av = window.CilixAvatar;
    if (av && av.model) {
      const mw = Math.abs(av.model.width) || 300;
      cx = av.model.x + mw / 2;
    }
    // A la derecha del avatar si cabe; si no, a la izquierda.
    let left = cx + 80;
    if (left + pw > w - 16) left = Math.max(16, cx - pw - 80);
    left = clamp(left, 16, w - pw - 16);

    // No tapar el panel de chat (empieza más abajo) ni la barra de título.
    const chat = document.querySelector('.chat');
    const chatTop = chat ? chat.getBoundingClientRect().top : h;
    const ph = panel.offsetHeight || 170;
    const top = Math.max(50, Math.min(h * 0.14, chatTop - ph - 10));
    panel.style.left = left + 'px';
    panel.style.top = top + 'px';
  }

  /* ── 1) Escribir: libreta con tecleo y cursor ──────────────────────────── */
  function runWrite(body) {
    const paper = document.createElement('div');
    paper.className = 'idle-paper';
    const textEl = document.createElement('div');
    textEl.className = 'idle-typed';
    paper.appendChild(textEl);
    body.appendChild(paper);

    const text = pick(NOTES);
    let i = 0;
    let stopped = false;
    const timer = setInterval(() => {
      if (stopped) return;
      i += 1;
      textEl.innerHTML = esc(text.slice(0, i)).replace(/\n/g, '<br>') +
        '<span class="caret"></span>';
      if (i >= text.length) {
        clearInterval(timer);
        setTimeout(() => {
          if (!stopped) textEl.querySelector('.caret')?.classList.add('blink-slow');
        }, 120);
      }
    }, 48);

    return () => { stopped = true; clearInterval(timer); };
  }

  /* ── 2) Programar: mini editor con resaltado ───────────────────────────── */
  function highlightLine(line) {
    if (/^\s*#/.test(line)) {
      return '<span class="tok-com">' + esc(line) + '</span>';
    }
    return line.split(/("[^"]*"|'[^']*')/).map((part) => {
      if (/^["']/.test(part)) {
        return '<span class="tok-str">' + esc(part) + '</span>';
      }
      return esc(part)
        .replace(/\b(def|return|for|in|while|not|if|else|import|from|const|let|function|await|async|print|range)\b/g,
                 '<span class="tok-kw">$1</span>')
        .replace(/\b(\d+)\b/g, '<span class="tok-num">$1</span>');
    }).join('');
  }

  function renderCode(el, src) {
    const lines = src.split('\n');
    el.innerHTML = lines.map((line) =>
      '<span class="code-line">' + highlightLine(line) + '</span>').join('\n') +
      '<span class="caret"></span>';
    el.scrollTop = el.scrollHeight;
  }

  function runCode(body) {
    const editor = document.createElement('div');
    editor.className = 'idle-code';
    body.appendChild(editor);

    const src = pick(CODE);
    let i = 0;
    let stopped = false;
    const timer = setInterval(() => {
      if (stopped) return;
      // Teclea por ráfagas: más natural que carácter a carácter constante.
      i = Math.min(src.length, i + 2);
      renderCode(editor, src.slice(0, i));
      if (i >= src.length) clearInterval(timer);
    }, 42);

    return () => { stopped = true; clearInterval(timer); };
  }

  /* ── 3) Dibujar: garabato animado en canvas ────────────────────────────── */
  function circlePts(cx, cy, r, n) {
    const out = [];
    for (let i = 0; i <= n; i++) {
      const a = (i / n) * Math.PI * 2;
      out.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
    }
    return out;
  }

  function heartPts() {
    const out = [];
    for (let i = 0; i <= 90; i++) {
      const t = (i / 90) * Math.PI * 2;
      out.push([
        16 * Math.pow(Math.sin(t), 3),
        13 * Math.cos(t) - 5 * Math.cos(2 * t) -
          2 * Math.cos(3 * t) - Math.cos(4 * t),
      ]);
    }
    return out;
  }

  function starPts() {
    const out = [];
    for (let i = 0; i <= 10; i++) {
      const a = -Math.PI / 2 + (i / 10) * Math.PI * 2;
      const r = i % 2 === 0 ? 1 : 0.42;
      out.push([Math.cos(a) * r, Math.sin(a) * r]);
    }
    return out;
  }

  function spiralPts() {
    const out = [];
    for (let i = 0; i <= 110; i++) {
      const t = (i / 110) * Math.PI * 4.6;
      const r = 0.08 + (i / 110) * 0.9;
      out.push([Math.cos(t) * r, Math.sin(t) * r]);
    }
    return out;
  }

  function flowerPts() {
    const petals = [];
    for (let p = 0; p < 5; p++) {
      const a = (p / 5) * Math.PI * 2;
      petals.push(circlePts(Math.cos(a) * 0.45, Math.sin(a) * 0.45, 0.3, 22));
    }
    petals.push(circlePts(0, 0, 0.15, 18));
    return petals;
  }

  function catPts() {
    return [
      circlePts(0, 0.05, 0.55, 44),                       // cara
      [[-0.52, -0.32], [-0.38, -0.86], [-0.08, -0.46]],  // oreja izq.
      [[0.52, -0.32], [0.38, -0.86], [0.08, -0.46]],     // oreja der.
      [[-0.28, -0.02], [-0.16, -0.02]],                  // ojo izq.
      [[0.16, -0.02], [0.28, -0.02]],                    // ojo der.
      [[-0.06, 0.18], [0, 0.26], [0.06, 0.18]],          // hocico
      [[-0.55, 0.2], [-0.18, 0.28]],                     // bigote izq.
      [[0.55, 0.2], [0.18, 0.28]],                       // bigote der.
    ];
  }

  /* Escala un garabato al tamaño del lienzo conservando proporciones. */
  function fitPaths(rawPaths, w, h) {
    const pad = 16;
    const all = rawPaths.flat();
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [x, y] of all) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    const spanX = Math.max(1e-3, maxX - minX);
    const spanY = Math.max(1e-3, maxY - minY);
    const scale = Math.min((w - pad * 2) / spanX, (h - pad * 2) / spanY);
    const ox = (w - spanX * scale) / 2 - minX * scale;
    const oy = (h - spanY * scale) / 2 - minY * scale;
    return rawPaths.map((pts) => pts.map(([x, y]) =>
      [x * scale + ox, y * scale + oy]));
  }

  const PALETTE = ['#00f5d4', '#7b5cff', '#ff2d78', '#ffd166', '#8be9fd'];

  function runDraw(body) {
    const canvas = document.createElement('canvas');
    canvas.className = 'idle-canvas';
    const cssW = 288, cssH = 108;
    canvas.width = cssW;
    canvas.height = cssH;
    body.appendChild(canvas);

    const ctx = canvas.getContext('2d');
    const kind = pick(['heart', 'star', 'spiral', 'flower', 'cat']);
    const raw = kind === 'heart' ? [heartPts()]
      : kind === 'star' ? [starPts()]
      : kind === 'spiral' ? [spiralPts()]
      : kind === 'flower' ? flowerPts()
      : catPts();
    const paths = fitPaths(raw, cssW, cssH)
      .map((pts, idx) => ({ pts, color: PALETTE[idx % PALETTE.length] }));
    const total = paths.reduce((a, p) => a + p.pts.length, 0);
    const dur = 7200;
    const t0 = performance.now();
    let raf = 0;
    let stopped = false;

    const frame = (now) => {
      if (stopped) return;
      const k = clamp((now - t0) / dur, 0, 1);
      const eased = 1 - Math.pow(1 - k, 2);
      const budget = total * eased;

      ctx.clearRect(0, 0, cssW, cssH);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.shadowBlur = 7;

      let consumed = 0;
      for (const path of paths) {
        const take = clamp(budget - consumed, 0, path.pts.length);
        if (take < 1) break;
        ctx.beginPath();
        ctx.strokeStyle = path.color;
        ctx.shadowColor = path.color;
        ctx.lineWidth = 2.4;
        const pts = path.pts;
        const n = Math.floor(take);
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < n; i++) ctx.lineTo(pts[i][0], pts[i][1]);
        if (n < pts.length) {
          const frac = take - n;
          if (n >= 1 && frac > 0) {
            const a = pts[n - 1], b = pts[n];
            ctx.lineTo(a[0] + (b[0] - a[0]) * frac,
                       a[1] + (b[1] - a[1]) * frac);
          }
        }
        ctx.stroke();
        consumed += path.pts.length;
      }
      ctx.shadowBlur = 0;

      if (k < 1) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => { stopped = true; cancelAnimationFrame(raf); };
  }

  /* ── 4) Caminar: delega el vaivén en CilixAvatar ───────────────────────── */

  /* ── Interacción manual desde el chat ──────────────────────────────────── */
  function fromText(text) {
    const raw = String(text || '').trim();
    if (!raw || raw.length > CFG.maxTextLength || state.active) return null;

    // Las órdenes de programación reales se delegan al backend
    // (Antigravity/Qoder): no las conviertas en la actividad de broma.
    const realCoding = /(antigravity|qoder|\bp[aá]salo\b|\bdelega(?:r|lo)?\b)/i.test(raw) ||
      /\b(programa|programar|programes|codea)\b[\s\S]{0,90}\b(script|funci[oó]n|clase|app|api|repo(?:sitorio)?|proyecto|bug|error|test|archivo|c[oó]digo)\b/i.test(raw);
    if (realCoding) return null;

    // El código va antes que "escribe" para que "escribe código" no sea notas.
    let kind = null;
    if (/\b(programa|programas|programando|programar|programes|codea|c[oó]digo)\b/i.test(raw)) kind = 'code';
    else if (/\b(dibuja|dibujas|dibujando|dibujo|garabatea|pinta)\b/i.test(raw)) kind = 'draw';
    else if (/\b(camina|caminas|caminando|caminar|pasea|paseando|da una vuelta|anda un poco)\b/i.test(raw)) kind = 'walk';
    else if (/\b(escribe|escribes|escribiendo|escribir|teclea|tecleando|libreta|notas)\b/i.test(raw)) kind = 'write';
    else if (/\b(haz algo|aburr[eé]te|entret[eé]n(?:te)?|distr[aá]e(?:te)?)\b/i.test(raw)) kind = 'random';

    if (!kind) return null;
    const chosen = kind === 'random' ? randomKind() : kind;
    return start(chosen) ? chosen : null;
  }

  /* ── API pública ──────────────────────────────────────────────────────── */
  const IdleActivities = {
    init() {
      if (state.inited) return;
      buildUI();
      state.inited = true;
      state.lastTouch = Date.now();

      // Moverse por la pantalla cuenta como "estar": reinicia el aburrimiento.
      window.addEventListener('pointermove', () => {
        state.lastTouch = Date.now();
      }, { passive: true });

      // Tocar, teclear o hacer scroll interrumpe lo que esté haciendo.
      const interrupt = () => {
        state.lastTouch = Date.now();
        if (state.active) stop(true);
      };
      for (const ev of ['pointerdown', 'wheel', 'touchstart']) {
        window.addEventListener(ev, interrupt, { passive: true });
      }
      window.addEventListener('keydown', () => {
        state.lastTouch = Date.now();
        if (!state.active) return;
        // Enter en el chat acaba de lanzar una actividad manual: el mismo
        // keydown que la crea no debe cancelarla.
        if (state.active.manual && Date.now() - state.startedAt < 180) return;
        stop(true);
      }, { passive: true });
      window.addEventListener('resize', () => {
        if (state.active) placePanel();
      });
      document.addEventListener('visibilitychange', () => {
        if (document.hidden && state.active) stop(true);
      });

      schedule();
    },

    /* El usuario/backend hizo algo. Una actividad automática se interrumpe;
       una manual (pedida en el chat) termina su rato para que se vea. */
    touch() {
      state.lastTouch = Date.now();
      if (state.active) {
        if (!state.active.manual) stop(true);
        return;
      }
      schedule();
    },

    /* El backend está pensando/hablando: no empezar actividades nuevas. */
    setBusy(busy) {
      const was = state.busy;
      state.busy = !!busy;
      if (state.busy) {
        state.lastTouch = Date.now();
        clearTimeout(state.timer);
        if (state.active && !state.active.manual) stop(true);
      } else if (was) {
        state.lastTouch = Date.now();
        schedule();
      }
    },

    start,
    stop,
    fromText,

    /* Ajusta tiempos en caliente (minIdle, maxIdle, minGap, maxGap…). */
    configure(opts) {
      if (!opts || typeof opts !== 'object') return { ...CFG };
      Object.assign(CFG, opts);
      if (CFG.minIdle > CFG.maxIdle) CFG.maxIdle = CFG.minIdle;
      if (CFG.minGap > CFG.maxGap) CFG.maxGap = CFG.minGap;
      if (!state.active) schedule(CFG.minIdle);
      return { ...CFG };
    },

    get active() { return state.active ? state.active.kind : null; },
    get busy() { return state.busy; },
    get config() { return { ...CFG }; },
  };

  window.IdleActivities = IdleActivities;

  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', () => IdleActivities.init(),
      { once: true });
  } else {
    IdleActivities.init();
  }
})();
