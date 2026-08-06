/**
 * GraphFace — a living, depth-aware dotted face rendered on a canvas.
 *
 * Modes:
 *  - GEOMETRIC (default): a procedurally-built 3D dot-cloud face.
 *  - PORTRAIT (set via setFace): converts a supplied face image into a coloured
 *    stipple portrait, preserving the likeness while keeping the same breathing,
 *    listening, speaking and state-driven animations. Dots are sampled
 *    organically — density follows luminance (darker = denser), positions are
 *    jittered off a grid, and the silhouette dissolves into a soft rim.
 *
 * Public API (unchanged):
 *   constructor(canvas, options), setState(state), setAudioLevel(level),
 *   start(), stop(), resize(w, h), setFace(src)
 */

const STATE_COLORS = {
  idle:       { hex: '#34d399' }, // green
  listening:  { hex: '#22d3ee' }, // cyan
  processing: { hex: '#f59e0b' }, // amber
  speaking:   { hex: '#8b7dff' }, // violet
  error:      { hex: '#ff6a75' }, // red
};

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

// Per-state motion presets (eased at runtime so transitions stay fluid).
const PRESETS = {
  idle:       { amp: 1.4, speed: 0.5, swirl: 0.0, ripple: 0.0, mouth: 0.0, pulse: 0.0, twinkle: 0.7, jitter: 0.0, turn: 0.12 },
  listening:  { amp: 1.7, speed: 0.8, swirl: 0.0, ripple: 1.0, mouth: 0.0, pulse: 0.0, twinkle: 0.3, jitter: 0.0, turn: 0.16 },
  processing: { amp: 2.4, speed: 1.7, swirl: 0.9, ripple: 0.0, mouth: 0.0, pulse: 0.0, twinkle: 0.4, jitter: 0.0, turn: 0.32 },
  speaking:   { amp: 2.0, speed: 1.1, swirl: 0.1, ripple: 0.2, mouth: 1.0, pulse: 1.0, twinkle: 0.6, jitter: 0.0, turn: 0.14 },
  error:      { amp: 2.8, speed: 2.2, swirl: 0.3, ripple: 0.0, mouth: 0.0, pulse: 0.0, twinkle: 1.0, jitter: 0.6, turn: 0.10 },
};

// Geometric face surface (normalized).
const RX = 0.62, RY = 0.80, RZ = 0.62;          // head ellipsoid
const EYE = { x: 0.30, y: -0.14, rx: 0.19, ry: 0.11 };
const LIGHT = (() => {                          // direction TO the light (upper-left-front)
  const v = [-0.35, -0.55, 0.78];
  const m = Math.hypot(v[0], v[1], v[2]);
  return [v[0] / m, v[1] / m, v[2] / m];
})();

function rotate(x, y, z, yaw, pitch) {
  const cy = Math.cos(yaw), sy = Math.sin(yaw);
  let x1 = x * cy + z * sy;
  let z1 = -x * sy + z * cy;
  const cp = Math.cos(pitch), sp = Math.sin(pitch);
  let y2 = y * cp - z1 * sp;
  let z2 = y * sp + z1 * cp;
  return [x1, y2, z2];
}

// ─── portrait helpers ───────────────────────────────────────────────────────

function colorDist(c1, c2) {
  return Math.hypot(c1[0]-c2[0], c1[1]-c2[1], c1[2]-c2[2]);
}

function samplePatch(data, W, H, cx, cy, r) {
  let sum = [0,0,0,0], n = 0;
  for (let y = Math.max(0, cy-r); y <= Math.min(H-1, cy+r); y++) {
    for (let x = Math.max(0, cx-r); x <= Math.min(W-1, cx+r); x++) {
      const i = (y*W+x)*4;
      sum[0] += data[i]; sum[1] += data[i+1]; sum[2] += data[i+2]; sum[3] += data[i+3];
      n++;
    }
  }
  return n ? [sum[0]/n, sum[1]/n, sum[2]/n, sum[3]/n] : [0,0,0,0];
}

class GraphFace {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.options = options;
    this.density = options.density || 1;

    this.state = 'idle';
    this.audioLevel = 0;
    this.smoothedLevel = 0;
    this.frame = 0;
    this.size = 0;
    this.dots = [];
    this.cur = { ...PRESETS.idle };
    this.yaw = 0; this.pitch = 0;
    this.blink = 0;
    this._blinkClock = 0;
    this._manualBlink = 0;   // >0 => force a blink for that many frames
    this.animId = null;

    // Portrait mode state
    this.portrait = null;   // null = geometric mode
    this.faceImage = null;  // current <img>
    this._pendingFace = null;

    this._resize();

    if (typeof ResizeObserver !== 'undefined') {
      this._ro = new ResizeObserver(() => this._resize());
      this._ro.observe(canvas);
    } else {
      window.addEventListener('resize', () => this._resize());
    }

    this.start();
  }

  /**
   * Switch to portrait mode using the supplied face image URL.
   * Falls back to the geometric face if the image fails to load.
   */
  setFace(src) {
    if (!src) { this._clearPortrait(); return; }
    this._pendingFace = src;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      if (this._pendingFace !== src) return; // a newer request arrived
      this.faceImage = img;
      this._buildPortraitDots(img);
    };
    img.onerror = () => {
      console.warn('[GraphFace] face image failed:', src);
      this._clearPortrait();
    };
    img.src = src;
  }

  _clearPortrait() {
    this.portrait = null;
    this.faceImage = null;
    this._pendingFace = null;
    this._buildDots();
  }

  _resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = this.canvas.getBoundingClientRect();
    const cssSize = Math.max(1, Math.round(rect.width || this.canvas.width || 280));
    this.size = cssSize;
    this.canvas.width = Math.round(cssSize * dpr);
    this.canvas.height = Math.round(cssSize * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (this.faceImage) {
      this._buildPortraitDots(this.faceImage);
    } else {
      this._buildDots();
    }
  }

  // Build a 3D point cloud: a front-facing cap of the head ellipsoid, tagged by
  // which facial feature each point belongs to.
  _buildDots() {
    const S = this.size;
    const step = Math.max(6, Math.round(8 / this.density));
    const dots = [];
    for (let gy = -S / 2; gy <= S / 2; gy += step) {
      const ny = gy / (S / 2);
      const ax = RX * (1 - 0.16 * Math.max(0, -ny));   // taper the jaw
      for (let gx = -S / 2; gx <= S / 2; gx += step) {
        const nx = gx / (S / 2);
        const rh = (nx * nx) / (ax * ax) + (ny * ny) / (RY * RY);
        if (rh > 1) continue;
        const z = RZ * Math.sqrt(Math.max(0, 1 - rh));  // onto the front surface
        const region = this._region(nx, ny);
        if (!region) continue;
        // Jitter each dot off the lattice so the fallback reads as a loose 3D
        // cloud instead of a visible grid; re-project onto the head surface.
        const jn = (step / S) * 0.5;
        const jx = nx + (Math.random() - 0.5) * 2 * jn;
        const jy = ny + (Math.random() - 0.5) * 2 * jn;
        const jrh = (jx * jx) / (ax * ax) + (jy * jy) / (RY * RY);
        if (jrh > 1) continue;
        // rim = 1 in the middle of the face, fading to 0 exactly at the silhouette.
        // The outer ~40% dissolves so the face reads as a floating dot-cloud with
        // no crisp outline / face boundary.
        const rim = clamp((1 - jrh) / 0.40, 0, 1);
        dots.push({
          bx: gx, by: gy, nx: jx, ny: jy,
          x: jx * RX, y: jy * RY, z: RZ * Math.sqrt(Math.max(0, 1 - jrh)),
          region,
          rim,
          phase: Math.random() * Math.PI * 2,
          tw: 0.6 + Math.random() * 0.8,
        });
      }
    }
    this.dots = dots;
  }

  // Feature tag for normalized face coords (nx right, ny down, [-1,1]).
  _region(nx, ny) {
    // Eyes (large almond) + bright pupil.
    for (const sx of [-1, 1]) {
      const dx = nx - sx * EYE.x, dy = ny - EYE.y;
      if ((dx * dx) / (EYE.rx * EYE.rx) + (dy * dy) / (EYE.ry * EYE.ry) <= 1) {
        return (dx * dx + dy * dy) < 0.0022 ? 'pupil' : 'eye';
      }
    }
    // Brows — a gentle arc above each eye.
    for (const sx of [-1, 1]) {
      const dx = nx - sx * EYE.x;
      if (Math.abs(dx) < EYE.rx + 0.02) {
        const by = EYE.y - 0.20 - dx * dx * 0.9 + 0.02;
        if (Math.abs(ny - by) < 0.035) return 'brow';
      }
    }
    // Nose — slim bridge with a tip and nostrils.
    if (Math.abs(nx) < 0.045 && ny > -0.04 && ny < 0.20) return 'nose';
    if (Math.abs(nx - (-0.05)) < 0.03 && Math.abs(ny - 0.17) < 0.03) return 'nose';
    if (Math.abs(nx - (0.05)) < 0.03 && Math.abs(ny - 0.17) < 0.03) return 'nose';
    // Lips — upper (cupid bow) + lower, in a mouth slot.
    const my = 0.42, mr = 0.26, mry = 0.075;
    if (((nx * nx) / (mr * mr) + ((ny - my) * (ny - my)) / (mry * mry)) <= 1) return 'mouth';

    // Face interior — keep only a sparse haze (~12%) so features pop.
    if (Math.random() < 0.12) return 'face';
    return null;
  }

  // Sample a supplied face image into a stipple/dot field.
  _buildPortraitDots(img) {
    // Finer sampling grid than before so thin features (irises, brow lines,
    // lip lines) survive the stipple instead of blurring away.
    const W = Math.max(64, Math.round(104 * (this.density || 1)));
    const H = Math.max(64, Math.round(W * img.naturalHeight / img.naturalWidth));
    const canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    const pctx = canvas.getContext('2d');
    pctx.drawImage(img, 0, 0, W, H);
    const data = pctx.getImageData(0, 0, W, H).data;

    // Background: median of the four corner patches. The head can touch the top
    // and bottom of the frame (hair / shoulders), so border-ring samples are
    // contaminated; the corners are reliably the plain background.
    const corners = [
      samplePatch(data, W, H, 0, 0, 4),
      samplePatch(data, W, H, W-1, 0, 4),
      samplePatch(data, W, H, 0, H-1, 4),
      samplePatch(data, W, H, W-1, H-1, 4),
    ];
    const median = arr => { arr.sort((a, b) => a - b); return arr[(arr.length / 2) | 0]; };
    const bg = [median(corners.map(p => p[0])), median(corners.map(p => p[1])), median(corners.map(p => p[2]))];
    const bgThresh = 45;  // max RGB distance to be treated as background

    const size = W * H;
    const lums = new Float32Array(size);
    const colors = new Uint8ClampedArray(size * 3);
    const isBg = new Uint8Array(size);

    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = (y * W + x) * 4;
        const idx = y * W + x;
        const r = data[i], g = data[i+1], b = data[i+2];
        colors[idx*3] = r; colors[idx*3+1] = g; colors[idx*3+2] = b;
        lums[idx] = 0.299*r + 0.587*g + 0.114*b;
        isBg[idx] = colorDist([r,g,b], bg) < bgThresh ? 1 : 0;
      }
    }

    // Tiny cleanup: remove isolated 1px foreground islands (salt-and-pepper from the generator).
    for (let y = 1; y < H - 1; y++) {
      for (let x = 1; x < W - 1; x++) {
        const idx = y * W + x;
        if (!isBg[idx]) {
          let bgNei = 0;
          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              if (isBg[(y+dy)*W + (x+dx)]) bgNei++;
            }
          }
          if (bgNei >= 7) isBg[idx] = 1;
        }
      }
    }

    // Face bounds from the silhouette. Feature bands are relative to this box so
    // eye/mouth detection adapts to the crop, and restricted to the central
    // column so stray hair on the sides or broad shoulders below don't confuse it.
    let fTop = H, fBot = 0, fLeft = W, fRight = 0;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        if (!isBg[y * W + x]) {
          if (y < fTop) fTop = y;
          if (y > fBot) fBot = y;
          if (x < fLeft) fLeft = x;
          if (x > fRight) fRight = x;
        }
      }
    }
    const fH = Math.max(1, fBot - fTop);
    const fW = Math.max(1, fRight - fLeft);
    const xL = Math.min(fLeft + Math.round(fW * 0.12), fRight);
    const xR = Math.max(fRight - Math.round(fW * 0.12), fLeft);

    // Adaptive darkness thresholds: the darkest ~12% of each feature band.
    const bandThresh = (y0, y1) => {
      const a = [];
      for (let y = y0; y < y1; y++) {
        for (let x = xL; x <= xR; x++) {
          const i = y * W + x;
          if (!isBg[i]) a.push(lums[i]);
        }
      }
      if (!a.length) return 128;
      a.sort((p, q) => p - q);
      return a[(a.length * 0.18) | 0];
    };
    const eyeThresh = Math.min(bandThresh(fTop + fH * 0.25, fTop + fH * 0.62), 155);
    const mouthThresh = Math.min(bandThresh(fTop + fH * 0.55, fTop + fH * 0.92), 165);

    // Chamfer distance transform over the background mask. Every foreground
    // pixel gets its distance (in px) to the nearest background pixel; the rim
    // of the silhouette is 0 and grows inwards, so the edge can be softened
    // instead of ending in a crisp outline.
    const d2 = new Float32Array(size).fill(W + H);
    for (let i = 0; i < size; i++) if (isBg[i]) d2[i] = 0;
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = y * W + x;
        if (isBg[i]) continue;
        let d = d2[i];
        if (x > 0)                       d = Math.min(d, d2[i - 1] + 1);
        if (y > 0)                       d = Math.min(d, d2[i - W] + 1);
        if (x > 0 && y > 0)              d = Math.min(d, d2[i - W - 1] + 1.4142);
        if (x < W - 1 && y > 0)          d = Math.min(d, d2[i - W + 1] + 1.4142);
        d2[i] = d;
      }
    }
    for (let y = H - 1; y >= 0; y--) {
      for (let x = W - 1; x >= 0; x--) {
        const i = y * W + x;
        if (isBg[i]) continue;
        let d = d2[i];
        if (x < W - 1)                   d = Math.min(d, d2[i + 1] + 1);
        if (y < H - 1)                   d = Math.min(d, d2[i + W] + 1);
        if (x < W - 1 && y < H - 1)      d = Math.min(d, d2[i + W + 1] + 1.4142);
        if (x > 0 && y < H - 1)          d = Math.min(d, d2[i + W - 1] + 1.4142);
        d2[i] = d;
      }
    }

    const lum = (x, y) => (x >= 0 && x < W && y >= 0 && y < H) ? lums[y*W+x] : 255;
    const dots = [];
    let mouthYSum = 0, mouthN = 0;

    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const idx = y * W + x;
        if (isBg[idx]) continue;

        const r = colors[idx*3], g = colors[idx*3+1], b = colors[idx*3+2];
        const L = lums[idx];

        // Gradient magnitude (edges define the face structure).
        const gx = (lum(x+1, y) - lum(x-1, y)) / 255;
        const gy = (lum(x, y+1) - lum(x, y-1)) / 255;
        const edge = Math.min(1, Math.hypot(gx, gy));

        // Darkness 0..1. Squaring amplifies the contrast between dark features
        // and flat skin so the stipple carves out eyes/lips/hair clearly.
        const dk = (255 - L) / 255;
        // Edge weight is deliberately modest so outlines get a gentle bump, not
        // a dense outline — dark features and flat skin stay in balance.
        const ink = clamp(dk * dk * 1.2 + edge * 0.5, 0, 1);

        // Density rule: flat skin keeps a generous floor (~40%) so the face
        // doesn't look hollow, edges sit around 50-65%, and dark features peak
        // near 80%. This avoids "dense outlines + empty flat areas".
        let pKeep = clamp(0.38 + 0.42 * ink, 0.25, 0.9);

        // Distance to the nearest background pixel; soften the silhouette with
        // fewer, fainter dots on the rim.
        const rim = clamp(d2[idx] / 3, 0, 1);
        pKeep *= 0.5 + 0.5 * rim;
        if (Math.random() > pKeep) continue;

        // Feature region from adaptive bands (used for blink / mouth animation).
        let region = 'face';
        if (x >= xL && x <= xR && y > fTop + fH * 0.24 && y < fTop + fH * 0.64 && L < eyeThresh) region = 'eye';
        else if (x >= xL && x <= xR && y > fTop + fH * 0.54 && y < fTop + fH * 0.94 &&
                 (L < mouthThresh || (edge > 0.5 && L < 175) ||
                  (r - g > 55 && r - b > 55 && r > 140))) region = 'mouth';

        // Lift the palette so pale pastel skin still reads as visible ink: dot
        // colours are deepened toward their hue, strongly for bright skin and
        // hardly at all for dark features.
        const lumDot = L;
        const lift = clamp((lumDot - 150) / 100, 0, 1);
        const liftK = 1 - 0.42 * lift;

        // Features get bigger, more solid dots so the eyes and mouth pop out of
        // the skin haze. Light cartoon lips are deepened to stay readable.
        let cr = r * liftK, cg = g * liftK, cb = b * liftK;
        let feat = 1.2;
        if (region === 'eye') {
          feat = 1.5;
        } else if (region === 'mouth') {
          feat = 1.6;
          if (0.299*cr + 0.587*cg + 0.114*cb > 175) {
            const k = 0.55;
            cr = cr * k; cg = cg * k; cb = Math.max(70, cb * k * 0.75);
          }
        }

        // Grid coords to [-1, 1] with aspect preserved, then jitter each dot off
        // its lattice cell so no rows/columns remain visible.
        const nx = (x / (W / 2)) - 1 + (Math.random() - 0.5) * (2 / W);
        const ny = (y / (H / 2)) - 1 + (Math.random() - 0.5) * (2 / H);

        // Radius / alpha tuned for a "lovely" stipple look: dark features get
        // big solid dots, light skin gets small faint ones. Edge contribution is
        // halved so outlines stay light instead of bulging into dense dark lines.
        const baseR = (0.5 + 2.2 * dk * dk + 0.55 * edge) * (0.7 + 0.3 * rim) * feat;
        const baseAlpha = clamp((0.14 + 1.1 * dk * dk + 0.25 * edge) * (0.5 + 0.5 * rim) * (feat > 1.2 ? 1.2 : 1), 0.26, 0.96);

        if (region === 'mouth') { mouthYSum += ny; mouthN++; }

        dots.push({
          nx, ny,
          color: [cr, cg, cb],
          baseR,
          baseAlpha,
          weight: dk,
          edge,
          region,
          phase: Math.random() * Math.PI * 2,
          tw: 0.6 + Math.random() * 0.8,
        });
      }
    }

    this.portrait = { W, H, aspect: W / H, mouthY: mouthN ? mouthYSum / mouthN : 0.36 };
    this.dots = dots;
  }

  setState(state) {
    if (PRESETS[state]) this.state = state;
  }

  /** Force the face to blink once (used when the agent starts "thinking"). */
  triggerBlink() {
    this._manualBlink = 20;
  }

  setAudioLevel(level) {
    this.audioLevel = Math.max(0, Math.min(1, level));
  }

  start() {
    const loop = () => {
      this.frame++;

      if (this._manualBlink > 0) {
        // Manual blink override: a smooth close/open across ~20 frames.
        this.blink = Math.sin(((20 - this._manualBlink) / 20) * Math.PI);
        this._manualBlink--;
      } else {
        this._blinkClock = (this._blinkClock + 1) % 240;
        this.blink = this._blinkClock > 220
          ? Math.sin(((this._blinkClock - 220) / 20) * Math.PI)
          : 0;
      }

      const target = this.audioLevel;
      const coef = target > this.smoothedLevel ? 0.4 : 0.15;
      this.smoothedLevel += (target - this.smoothedLevel) * coef;

      this._draw();
      this.animId = requestAnimationFrame(loop);
    };
    this.animId = requestAnimationFrame(loop);
  }

  stop() {
    if (this.animId) {
      cancelAnimationFrame(this.animId);
      this.animId = null;
    }
  }

  // Smooth layered-sine flow field -> a small 2D displacement (screen-space shimmer).
  _flow(nx, ny, t) {
    const a = Math.sin(nx * 3.1 + t * 0.7)
            + Math.sin(ny * 2.4 - t * 0.9)
            + Math.sin((nx + ny) * 2.7 + t * 1.1)
            + Math.sin((nx - ny) * 1.9 - t * 0.6);
    const b = Math.cos(nx * 2.2 - t * 0.8)
            + Math.cos(ny * 3.3 + t * 0.6)
            + Math.cos((nx - ny) * 2.1 - t * 1.0);
    return [a * 0.06, b * 0.06];
  }

  _draw() {
    if (this.portrait) {
      this._drawPortrait();
    } else {
      this._drawGeometric();
    }
  }

  // ─── portrait render path ──────────────────────────────────────────────────
  _drawPortrait() {
    const ctx = this.ctx;
    const S = this.size;
    const t = this.frame * 0.016;
    const lvl = this.smoothedLevel;
    const cx = S / 2, cy = S / 2;
    const D = 2.4;

    const target = PRESETS[this.state] || PRESETS.idle;
    for (const k in target) this.cur[k] += (target[k] - this.cur[k]) * 0.08;

    const amp = this.cur.amp, speed = this.cur.speed, swirl = this.cur.swirl;
    const ripple = this.cur.ripple, mouthAmt = this.cur.mouth;
    const pulse = this.cur.pulse * lvl, twinkle = this.cur.twinkle, jitter = this.cur.jitter;
    const tt = t * speed;

    const turn = this.cur.turn;
    const tYaw = turn * Math.sin(t * 0.5) + (this.state === 'processing' ? 0.25 * Math.sin(tt * 1.5) : 0);
    const tPitch = 0.05 * Math.sin(t * 0.4) + (this.state === 'speaking' ? 0.04 * Math.sin(tt * 8) * lvl : 0);
    this.yaw += (tYaw - this.yaw) * 0.06;
    this.pitch += (tPitch - this.pitch) * 0.06;
    const yaw = this.yaw + (jitter ? (Math.random() - 0.5) * 0.05 : 0);
    const pitch = this.pitch + (jitter ? (Math.random() - 0.5) * 0.05 : 0);

    const stateRgb = hexToRgb((STATE_COLORS[this.state] || STATE_COLORS.idle).hex);
    const tintStrength = this.state === 'error' ? 0.45 : 0.18;
    const tintR = stateRgb[0] * tintStrength;
    const tintG = stateRgb[1] * tintStrength;
    const tintB = stateRgb[2] * tintStrength;

    // Breathing scale.
    const breath = 1 + 0.012 * Math.sin(t * 1.2);
    const faceScale = S * 0.42 * breath;
    const aspect = this.portrait.aspect;
    const sx = aspect >= 1 ? 1 : aspect;
    const sy = aspect >= 1 ? 1 / aspect : 1;

    ctx.clearRect(0, 0, S, S);
    ctx.globalCompositeOperation = 'source-over';

    for (const d of this.dots) {
      let x = d.nx * sx, y = d.ny * sy;
      // Curve the surface back at the edges for a little 3D volume.
      let z = -0.22 * Math.hypot(d.nx, d.ny);

      // Listening: a ripple travels across the surface.
      if (ripple > 0) {
        z += Math.sin(Math.hypot(d.nx, d.ny) * 9 - tt * 5) * Math.exp(-Math.hypot(d.nx, d.ny) * 1.1) * ripple * 0.06;
      }

      // Speaking: mouth region stretches outward from the mouth centre.
      if (d.region === 'mouth') {
        const open = mouthAmt * (0.5 + 0.5 * Math.sin(tt * 9)) * (0.5 + lvl);
        const mx = 0, my = this.portrait.mouthY || 0.36;
        const dx = d.nx - mx, dy = d.ny - my;
        const dist = Math.hypot(dx, dy);
        const f = 1 + open * 0.18 * Math.max(0, 1 - dist / 0.35);
        x = mx + dx * f;
        y = my + dy * f;
      }

      // Thinking: swirl the surface flow around the centre.
      if (swirl > 0) {
        const a = swirl * 0.12;
        const nx2 = x * Math.cos(a) - y * Math.sin(a);
        const ny2 = x * Math.sin(a) + y * Math.cos(a);
        x = nx2; y = ny2;
      }

      // Project to screen with perspective.
      const [rx2, ry2, rz2] = rotate(x, y, z, yaw, pitch);
      const persp = D / (D - rz2);
      let px = cx + rx2 * faceScale * persp;
      let py = cy + ry2 * faceScale * persp;

      // 2D fluid shimmer on top of the projection.
      const [fx, fy] = this._flow(d.nx, d.ny, tt);
      const fg = S * 0.5 * 0.18 * amp;
      px += fx * fg + d.nx * pulse * 5;
      py += fy * fg + d.ny * pulse * 5;

      // Blink dims the eye region.
      let b = 1.0;
      if (d.region === 'eye' && this.blink > 0) b *= 1 - 0.7 * this.blink;

      // Speaking brightens the mouth.
      if (d.region === 'mouth' && this.state === 'speaking') b *= 0.65 + 0.55 * lvl;

      // Flowing brightness bands + per-dot twinkle.
      b += twinkle * 0.14 * Math.sin(tt * 2 + d.phase * d.tw);
      b = Math.max(0.06, Math.min(1.4, b));

      // Apply subtle state tint while preserving the portrait likeness.
      const r = d.color[0] * (1 - tintStrength) + tintR;
      const g = d.color[1] * (1 - tintStrength) + tintG;
      const bC = d.color[2] * (1 - tintStrength) + tintB;

      const alpha = d.baseAlpha * b;
      const radius = d.baseR * (0.85 + 0.4 * b) * (1 + 0.45 * lvl * (this.state === 'speaking' ? 1 : 0));

      ctx.fillStyle = `rgba(${r|0},${g|0},${bC|0},${Math.min(1, alpha)})`;
      ctx.beginPath();
      ctx.arc(px, py, Math.max(0.4, radius), 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // ─── geometric render path (original) ──────────────────────────────────────
  _drawGeometric() {
    const ctx = this.ctx;
    const S = this.size;
    const t = this.frame * 0.016;
    const lvl = this.smoothedLevel;
    const cx = S / 2, cy = S / 2;
    const D = 2.4;                       // camera distance
    const scale = S * 0.42;              // projection scale

    const target = PRESETS[this.state] || PRESETS.idle;
    for (const k in target) this.cur[k] += (target[k] - this.cur[k]) * 0.08;

    const amp = this.cur.amp, speed = this.cur.speed, swirl = this.cur.swirl;
    const ripple = this.cur.ripple, mouthAmt = this.cur.mouth;
    const pulse = this.cur.pulse * lvl, twinkle = this.cur.twinkle, jitter = this.cur.jitter;
    const tt = t * speed;

    const turn = this.cur.turn;
    const tYaw = turn * Math.sin(t * 0.5) + (this.state === 'processing' ? 0.25 * Math.sin(tt * 1.5) : 0);
    const tPitch = 0.05 * Math.sin(t * 0.4) + (this.state === 'speaking' ? 0.04 * Math.sin(tt * 8) * lvl : 0);
    this.yaw += (tYaw - this.yaw) * 0.06;
    this.pitch += (tPitch - this.pitch) * 0.06;
    const yaw = this.yaw + (jitter ? (Math.random() - 0.5) * 0.05 : 0);
    const pitch = this.pitch + (jitter ? (Math.random() - 0.5) * 0.05 : 0);

    const rgb = hexToRgb((STATE_COLORS[this.state] || STATE_COLORS.idle).hex);

    ctx.clearRect(0, 0, S, S);
    ctx.globalCompositeOperation = 'lighter';

    for (const d of this.dots) {
      let x = d.x, y = d.y, z = d.z;
      const dist = Math.hypot(d.nx, d.ny);

      if (ripple > 0) {
        z += Math.sin(dist * 9 - tt * 5) * Math.exp(-dist * 1.1) * ripple * 0.06;
      }

      if (d.region === 'mouth') {
        const open = mouthAmt * (0.5 + 0.5 * Math.sin(tt * 9)) * (0.5 + lvl);
        const taper = 1 - Math.min(1, Math.abs(d.nx) / 0.26);
        const sgn = d.ny >= 0.42 ? 1 : -1;
        z += sgn * open * 0.10 * taper;
        y += -sgn * open * 0.05 * taper;
      }

      if (swirl > 0) {
        const a = swirl * 0.12;
        const nx2 = x * Math.cos(a) - y * Math.sin(a);
        const ny2 = x * Math.sin(a) + y * Math.cos(a);
        x = nx2; y = ny2;
      }

      const [rx2, ry2, rz2] = rotate(x, y, z, yaw, pitch);
      const persp = D / (D - rz2);
      let px = cx + rx2 * scale * persp;
      let py = cy + ry2 * scale * persp;

      const [fx, fy] = this._flow(d.nx, d.ny, tt);
      const fg = S * 0.5 * 0.18 * amp;
      px += fx * fg + d.nx * pulse * 5;
      py += fy * fg + d.ny * pulse * 5;

      if ((d.region === 'eye' || d.region === 'pupil') && this.blink > 0) {
        const ecx = (d.nx >= 0 ? EYE.x : -EYE.x) * RX;
        const ecy = EYE.y * RY;
        px -= (rx2 - ecx) * this.blink * 0.6;
        py -= (ry2 - ecy) * this.blink * 0.6;
      }

      let nxn = rx2 / (RX * RX), nyn = ry2 / (RY * RY), nzn = rz2 / (RZ * RZ);
      const nm = Math.hypot(nxn, nyn, nzn) || 1;
      nxn /= nm; nyn /= nm; nzn /= nm;
      const diff = Math.max(0, nxn * LIGHT[0] + nyn * LIGHT[1] + nzn * LIGHT[2]);
      let shade = 0.22 + 0.85 * diff;

      let b = shade * (0.7 + 0.5 * (0.5 + 0.5 * Math.sin((fx + fy) * 6 + d.phase + tt)));
      b += twinkle * 0.18 * Math.sin(tt * 2 + d.phase * d.tw);
      b = Math.max(0.04, Math.min(1.3, b));
      if (this.state === 'speaking') b *= 0.6 + 0.6 * lvl;
      if (this.state === 'error') b *= 0.8;
      if ((d.region === 'eye' || d.region === 'pupil') && this.blink > 0) b *= 1 - 0.7 * this.blink;

      // Dissolve the face boundary: dots fade out and shrink toward the silhouette,
      // so the face is a floating dot-cloud with no crisp oval outline.
      if (d.rim !== undefined) {
        b *= 0.30 + 0.70 * d.rim;
        if (d.rim < 0.5) b *= d.rim / 0.5;   // outer half fades to nothing
      }

      let r = (d.region === 'pupil' ? 2.6 : d.region === 'eye' ? 2.2
            : d.region === 'mouth' ? 2.0 : d.region === 'brow' || d.region === 'nose' ? 1.9 : 1.15);
      r *= persp * (0.85 + 0.4 * b) * (1 + 0.4 * lvl * (this.state === 'speaking' ? 1 : 0));
      if (d.rim !== undefined) r *= 0.55 + 0.45 * d.rim;

      ctx.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${Math.min(1, b)})`;
      ctx.beginPath();
      ctx.arc(px, py, r, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalCompositeOperation = 'source-over';
  }

  resize(w, h) {
    if (w && h) {
      const s = Math.min(w, h);
      this.canvas.style.width = s + 'px';
      this.canvas.style.height = s + 'px';
    }
    this._resize();
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { GraphFace };
}
