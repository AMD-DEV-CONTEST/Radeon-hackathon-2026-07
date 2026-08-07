// 只读像素画布 —— FRONTEND_PLAN.md §6.1
//
// 关键约束：
//  · 缩放只有 1/2/4/8/16/32 六档，没有连续缩放。
//  · 原点恒为整数，平移按整数步进。
//  · 全程在设备像素空间计算，避免 150% DPI 下出现半像素。
//  · 分三层重绘：背景层(棋盘)、素材层、叠加层(网格线/高亮)。

import * as C from './coords.js';

export const ZOOM_LEVELS = C.ZOOM_LEVELS;

export class CanvasView extends EventTarget {
  constructor(canvas) {
    super();
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: false });

    this.image = null; // HTMLImageElement
    this.pixels = null; // ImageData，用于取色
    this.imgW = 0;
    this.imgH = 0;

    this.zoomIndex = 3; // 8x
    this.originX = 0; // 设备像素，整数
    this.originY = 0;
    this.lightChecker = false;
    this.showGrid = true;

    this.cursor = null; // {x, y} 素材坐标
    this.overlay = null; // 预渲染的叠加层 canvas，与素材同尺寸
    this._panning = null;
    this._dpr = 1;

    this._bind();
    this._observe();
  }

  get zoom() {
    return ZOOM_LEVELS[this.zoomIndex];
  }

  // ------------------------------------------------------------ 坐标换算
  // 往返必须精确：imageToScreen(screenToImage(p)) 落在同一格内。

  get _view() {
    return { originX: this.originX, originY: this.originY, zoom: this.zoom, zoomIndex: this.zoomIndex };
  }

  screenToImage(deviceX, deviceY) {
    return C.screenToImage(deviceX, deviceY, this._view);
  }

  imageToScreen(imgX, imgY) {
    return C.imageToScreen(imgX, imgY, this._view);
  }

  inBounds(p) {
    return C.inBounds(p, this.imgW, this.imgH);
  }

  // ------------------------------------------------------------ 载入

  async load(url, { keepView = false } = {}) {
    const img = new Image();
    // 取色器要读回像素，必须以 CORS 模式加载，否则画布被污染、getImageData 抛错。
    img.crossOrigin = 'anonymous';
    img.src = url;
    await img.decode();

    const first = this.image === null;
    const sizeChanged = img.naturalWidth !== this.imgW || img.naturalHeight !== this.imgH;

    this.image = img;
    this.imgW = img.naturalWidth;
    this.imgH = img.naturalHeight;

    // 离屏取一次像素，供取色器使用（不走后端往返）
    const off = document.createElement('canvas');
    off.width = this.imgW;
    off.height = this.imgH;
    const octx = off.getContext('2d', { willReadFrequently: true });
    octx.imageSmoothingEnabled = false;
    octx.drawImage(img, 0, 0);
    this.pixels = octx.getImageData(0, 0, this.imgW, this.imgH);

    if (first || sizeChanged || !keepView) this.fit();
    else this.render();

    this._emitChange();
  }

  clear() {
    this.image = null;
    this.pixels = null;
    this.overlay = null;
    this.imgW = 0;
    this.imgH = 0;
    this.render();
  }

  /**
   * 用遮罩把「将被擦除」的像素染色叠在素材上。
   * 遮罩的 alpha 是「保留的形状」，所以 alpha 低的地方才是要染的。
   * 叠加层预渲染成与素材同尺寸的位图，缩放时随主图一起最近邻放大，
   * 不会在高倍下变成模糊色块。
   */
  async setMaskOverlay(url, { color = [255, 0, 255], strength = 0.45 } = {}) {
    if (!url) {
      this.overlay = null;
      this.render();
      return;
    }

    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = url;
    await img.decode();

    const w = img.naturalWidth;
    const h = img.naturalHeight;
    const off = document.createElement('canvas');
    off.width = w;
    off.height = h;
    const ctx = off.getContext('2d', { willReadFrequently: true });
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(img, 0, 0);

    const data = ctx.getImageData(0, 0, w, h);
    const px = data.data;
    for (let i = 0; i < w * h; i += 1) {
      const keep = px[i * 4 + 3] >= 128;
      px[i * 4] = color[0];
      px[i * 4 + 1] = color[1];
      px[i * 4 + 2] = color[2];
      px[i * 4 + 3] = keep ? 0 : Math.round(255 * strength);
    }
    ctx.putImageData(data, 0, 0);

    this.overlay = off;
    this.render();
  }

  // ------------------------------------------------------------ 视图操作

  /** 选一个能整体放下的最大档位，并居中。 */
  fit() {
    if (!this.imgW) return;
    this._syncBackingStore();
    const { width, height } = this._deviceSize();
    this.zoomIndex = C.fitZoomIndex(this.imgW, this.imgH, width, height, 24 * this._dpr);
    this.center();
  }

  center() {
    const { width, height } = this._deviceSize();
    const o = C.centerOrigin(this.imgW, this.imgH, this.zoom, width, height);
    this.originX = o.originX;
    this.originY = o.originY;
    this.render();
    this._emitChange();
  }

  /** 以某个设备像素点为锚做缩放，锚点下的素材像素保持不动。 */
  zoomAt(deviceX, deviceY, delta) {
    // _view 是 getter，每次调用返回新对象，必须先取一次再比较引用
    const view = this._view;
    const next = C.zoomAt(view, deviceX, deviceY, delta);
    if (next === view) return; // 已在端点，无变化
    this.zoomIndex = next.zoomIndex;
    this.originX = next.originX;
    this.originY = next.originY;
    this.render();
    this._emitChange();
  }

  setZoomIndex(index) {
    const { width, height } = this._deviceSize();
    this.zoomAt(width / 2, height / 2, index - this.zoomIndex);
  }

  panBy(dx, dy) {
    this.originX += Math.round(dx);
    this.originY += Math.round(dy);
    this.render();
  }

  toggleChecker() {
    this.lightChecker = !this.lightChecker;
    this.render();
  }

  toggleGrid() {
    this.showGrid = !this.showGrid;
    this.render();
  }

  // ------------------------------------------------------------ 取色

  colorAt(imgX, imgY) {
    if (!this.pixels || !this.inBounds({ x: imgX, y: imgY })) return null;
    const i = (imgY * this.imgW + imgX) * 4;
    const d = this.pixels.data;
    return { r: d[i], g: d[i + 1], b: d[i + 2], a: d[i + 3] };
  }

  static formatColor(c) {
    if (!c) return '--';
    if (c.a === 0) return '透明';
    const hex = (n) => n.toString(16).padStart(2, '0').toUpperCase();
    const base = `#${hex(c.r)}${hex(c.g)}${hex(c.b)}`;
    return c.a === 255 ? base : `${base}${hex(c.a)}`;
  }

  // ------------------------------------------------------------ 渲染

  render() {
    const ctx = this.ctx;
    const { width, height } = this._syncBackingStore();

    ctx.imageSmoothingEnabled = false;

    // 层 1：视口底色
    ctx.fillStyle = getVar('--canvas-void', '#262626');
    ctx.fillRect(0, 0, width, height);

    if (!this.image) return;

    const z = this.zoom;
    const w = this.imgW * z;
    const h = this.imgH * z;

    // 层 1b：素材范围内的中性棋盘格。格子固定 8 设备像素，不随缩放变化，
    // 避免与素材自身花纹产生摩尔纹（§6.1）。
    const cell = 8 * this._dpr;
    const a = this.lightChecker
      ? getVar('--checker-light-a', '#c8c8c8')
      : getVar('--checker-a', '#4a4a4a');
    const b = this.lightChecker
      ? getVar('--checker-light-b', '#b4b4b4')
      : getVar('--checker-b', '#3a3a3a');
    ctx.save();
    ctx.beginPath();
    ctx.rect(this.originX, this.originY, w, h);
    ctx.clip();
    ctx.fillStyle = a;
    ctx.fillRect(this.originX, this.originY, w, h);
    ctx.fillStyle = b;
    const cols = Math.ceil(w / cell);
    const rows = Math.ceil(h / cell);
    for (let r = 0; r < rows; r += 1) {
      for (let c = (r % 2); c < cols; c += 2) {
        ctx.fillRect(this.originX + c * cell, this.originY + r * cell, cell, cell);
      }
    }
    ctx.restore();

    // 层 2：素材
    ctx.drawImage(this.image, this.originX, this.originY, w, h);

    // 层 2b：遮罩染色，尺寸与素材一致时才叠
    if (this.overlay && this.overlay.width === this.imgW && this.overlay.height === this.imgH) {
      ctx.drawImage(this.overlay, this.originX, this.originY, w, h);
    }

    // 层 3：叠加。像素网格线只在 >= 8x 时出现。
    if (this.showGrid && z >= 8) {
      ctx.strokeStyle = getVar('--grid-line', 'rgba(255,255,255,0.14)');
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = 0; x <= this.imgW; x += 1) {
        const sx = this.originX + x * z + 0.5;
        ctx.moveTo(sx, this.originY);
        ctx.lineTo(sx, this.originY + h);
      }
      for (let y = 0; y <= this.imgH; y += 1) {
        const sy = this.originY + y * z + 0.5;
        ctx.moveTo(this.originX, sy);
        ctx.lineTo(this.originX + w, sy);
      }
      ctx.stroke();
    }

    // 素材外框
    ctx.strokeStyle = '#000';
    ctx.lineWidth = 1;
    ctx.strokeRect(this.originX - 0.5, this.originY - 0.5, w + 1, h + 1);

    // 光标所在像素高亮
    if (this.cursor && this.inBounds(this.cursor)) {
      const p = this.imageToScreen(this.cursor.x, this.cursor.y);
      ctx.strokeStyle = getVar('--guide', '#ffaa00');
      ctx.lineWidth = Math.max(1, Math.round(this._dpr));
      ctx.strokeRect(p.x + 0.5, p.y + 0.5, z - 1, z - 1);
    }
  }

  // ------------------------------------------------------------ 内部

  _deviceSize() {
    return { width: this.canvas.width, height: this.canvas.height };
  }

  _syncBackingStore() {
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(rect.width * dpr));
    const h = Math.max(1, Math.round(rect.height * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this._dpr = dpr;
    return { width: w, height: h };
  }

  _toDevice(event) {
    const rect = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    return { x: (event.clientX - rect.left) * dpr, y: (event.clientY - rect.top) * dpr };
  }

  _bind() {
    const c = this.canvas;

    c.addEventListener('mousemove', (e) => {
      const d = this._toDevice(e);
      if (this._panning) {
        this.panBy(d.x - this._panning.x, d.y - this._panning.y);
        this._panning = d;
        this._emitChange();
        return;
      }
      const p = this.screenToImage(d.x, d.y);
      const changed = !this.cursor || this.cursor.x !== p.x || this.cursor.y !== p.y;
      this.cursor = p;
      if (changed) {
        this.render();
        this._emitCursor();
      }
    });

    c.addEventListener('mouseleave', () => {
      this.cursor = null;
      this.render();
      this._emitCursor();
    });

    c.addEventListener('mousedown', (e) => {
      // 中键或右键平移；左键在阶段 A 是取色器
      if (e.button === 1 || e.button === 2) {
        e.preventDefault();
        this._panning = this._toDevice(e);
        c.style.cursor = 'grabbing';
      } else if (e.button === 0) {
        const d = this._toDevice(e);
        const p = this.screenToImage(d.x, d.y);
        const color = this.colorAt(p.x, p.y);
        if (color) this.dispatchEvent(new CustomEvent('pick', { detail: { color, point: p } }));
      }
    });

    window.addEventListener('mouseup', () => {
      if (this._panning) {
        this._panning = null;
        c.style.cursor = '';
      }
    });

    c.addEventListener('contextmenu', (e) => e.preventDefault());

    c.addEventListener(
      'wheel',
      (e) => {
        e.preventDefault();
        const d = this._toDevice(e);
        this.zoomAt(d.x, d.y, e.deltaY < 0 ? 1 : -1);
      },
      { passive: false },
    );
  }

  _observe() {
    const ro = new ResizeObserver(() => this.render());
    ro.observe(this.canvas);
  }

  _emitCursor() {
    this.dispatchEvent(
      new CustomEvent('cursor', {
        detail: {
          point: this.cursor && this.inBounds(this.cursor) ? this.cursor : null,
          color: this.cursor ? this.colorAt(this.cursor.x, this.cursor.y) : null,
        },
      }),
    );
  }

  _emitChange() {
    this.dispatchEvent(
      new CustomEvent('viewchange', {
        detail: { zoom: this.zoom, width: this.imgW, height: this.imgH },
      }),
    );
  }
}

function getVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
