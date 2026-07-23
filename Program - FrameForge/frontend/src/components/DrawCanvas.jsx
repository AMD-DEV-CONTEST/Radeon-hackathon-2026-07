import { useEffect, useRef, useState, useCallback } from "react";
import "./DrawCanvas.css";

/**
 * DrawCanvas — a full brush-based drawing surface.
 *
 * Features:
 *  - Pressure-sensitive brush strokes (pointer events with pressure)
 *  - Adjustable size, opacity, hardness, color
 *  - Eraser tool
 *  - Undo / Redo (stroke history)
 *  - Clear canvas
 *  - Photoshop .abr brush import (basic thumbnail extraction)
 *  - Exports canvas as a PNG data URI for the video pipeline
 *
 * The canvas is fixed at 768×512 (LTX-Video native resolution) so the
 * drawing feeds directly into the Replicate pipeline without resampling.
 */

const CANVAS_W = 768;
const CANVAS_H = 512;

// ── Default built-in brushes ──────────────────────────────────────────
const BUILTIN_BRUSHES = [
  { id: "round",    label: "Round",    shape: "round",  hardness: 0.5 },
  { id: "soft",     label: "Soft",     shape: "round",  hardness: 0.15 },
  { id: "hard",     label: "Hard",     shape: "round",  hardness: 0.95 },
  { id: "flat",     label: "Flat",     shape: "flat",   hardness: 0.7 },
  { id: "chalk",    label: "Chalk",    shape: "round",  hardness: 0.6, scatter: 0.3 },
  { id: "airbrush", label: "Airbrush", shape: "round",  hardness: 0.05, flow: 0.15 },
];

export default function DrawCanvas({ onCanvasReady }) {
  const canvasRef = useRef(null);
  const ctxRef = useRef(null);

  // Drawing state
  const [isDrawing, setIsDrawing] = useState(false);
  const lastPoint = useRef(null);
  const strokeBuffer = useRef(null); // offscreen buffer for current stroke

  // Tool state
  const [tool, setTool] = useState("brush"); // brush | eraser
  const [brushId, setBrushId] = useState("soft");
  const [color, setColor] = useState("#c6ff3a");
  const [size, setSize] = useState(24);
  const [opacity, setOpacity] = useState(0.85);
  const [hardness, setHardness] = useState(0.15);
  const [flow, setFlow] = useState(1.0);
  const [scatter, setScatter] = useState(0);

  // Imported brushes (from .abr or custom)
  const [customBrushes, setCustomBrushes] = useState([]);
  const [selectedCustomBrush, setSelectedCustomBrush] = useState(null);

  // Undo / Redo
  const undoStack = useRef([]);
  const redoStack = useRef([]);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  // ── Initialize canvas ───────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.width = CANVAS_W;
    canvas.height = CANVAS_H;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctxRef.current = ctx;

    // Fill with dark background so the drawing has a base
    ctx.fillStyle = "#0a0a0a";
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

    // Save initial state for undo
    pushUndo(ctx);

    if (onCanvasReady) onCanvasReady(canvas);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Undo / Redo helpers ─────────────────────────────────────────────
  function pushUndo(ctx) {
    const data = ctx.getImageData(0, 0, CANVAS_W, CANVAS_H);
    undoStack.current.push(data);
    if (undoStack.current.length > 30) undoStack.current.shift();
    redoStack.current = [];
    setCanUndo(undoStack.current.length > 1);
    setCanRedo(false);
  }

  function handleUndo() {
    const ctx = ctxRef.current;
    if (!ctx || undoStack.current.length < 2) return;
    const current = undoStack.current.pop();
    redoStack.current.push(current);
    const prev = undoStack.current[undoStack.current.length - 1];
    ctx.putImageData(prev, 0, 0);
    setCanUndo(undoStack.current.length > 1);
    setCanRedo(redoStack.current.length > 0);
  }

  function handleRedo() {
    const ctx = ctxRef.current;
    if (!ctx || redoStack.current.length === 0) return;
    const data = redoStack.current.pop();
    undoStack.current.push(data);
    ctx.putImageData(data, 0, 0);
    setCanUndo(undoStack.current.length > 1);
    setCanRedo(redoStack.current.length > 0);
  }

  function handleClear() {
    const ctx = ctxRef.current;
    if (!ctx) return;
    ctx.fillStyle = "#0a0a0a";
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
    pushUndo(ctx);
  }

  // ── Brush stamp rendering ───────────────────────────────────────────
  /**
   * Render a single brush stamp at (x, y) with the given pressure.
   * Uses texture image for imported brushes, otherwise shape/hardness.
   */
  function stampAt(ctx, x, y, pressure) {
    const effectiveSize = size * (0.3 + 0.7 * pressure);
    const r = effectiveSize / 2;
    const alpha = opacity * flow * pressure;

    const brush = getActiveBrush();
    const isEraser = tool === "eraser";

    // Use imported brush texture if available
    if (brush.textureImg && !isEraser) {
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.globalCompositeOperation = "source-over";
      ctx.drawImage(brush.textureImg, x - r, y - r, effectiveSize, effectiveSize);
      ctx.restore();
      return;
    }

    // Scatter offset for non-textured brushes
    let sx = x, sy = y;
    if (brush.scatter && scatter > 0) {
      const off = r * scatter;
      sx += (Math.random() - 0.5) * off * 2;
      sy += (Math.random() - 0.5) * off * 2;
    }

    ctx.save();
    ctx.globalAlpha = alpha;

    if (isEraser) {
      ctx.globalCompositeOperation = "destination-out";
      const grad = ctx.createRadialGradient(sx, sy, 0, sx, sy, r);
      grad.addColorStop(0, `rgba(0,0,0,${alpha})`);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, Math.PI * 2);
      ctx.fill();
    } else if (brush.shape === "flat") {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.ellipse(sx, sy, r, r * 0.5, 0, 0, Math.PI * 2);
      ctx.fill();
    } else {
      const innerStop = brush.hardness ?? hardness;
      const grad = ctx.createRadialGradient(sx, sy, 0, sx, sy, r);
      grad.addColorStop(0, color);
      grad.addColorStop(innerStop, color);
      grad.addColorStop(1, hexToRgba(color, 0));
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function getActiveBrush() {
    if (selectedCustomBrush) return selectedCustomBrush;
    return BUILTIN_BRUSHES.find((b) => b.id === brushId) || BUILTIN_BRUSHES[0];
  }

  // ── Pointer events ─────────────────────────────────────────────────
  function getPos(e) {
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const scaleX = CANVAS_W / rect.width;
    const scaleY = CANVAS_H / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
      pressure: e.pressure > 0 ? e.pressure : 0.5,
    };
  }

  function handlePointerDown(e) {
    e.preventDefault();
    canvasRef.current.setPointerCapture(e.pointerId);
    const ctx = ctxRef.current;
    const p = getPos(e);
    lastPoint.current = p;
    setIsDrawing(true);
    stampAt(ctx, p.x, p.y, p.pressure);
  }

  function handlePointerMove(e) {
    if (!isDrawing) return;
    e.preventDefault();
    const ctx = ctxRef.current;
    const p = getPos(e);
    const lp = lastPoint.current;
    if (!lp) return;

    // Interpolate stamps between last point and current for smooth strokes
    const dx = p.x - lp.x;
    const dy = p.y - lp.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const spacing = Math.max(1, size * 0.08);
    const steps = Math.max(1, Math.ceil(dist / spacing));

    for (let i = 1; i <= steps; i++) {
      const t = i / steps;
      const ix = lp.x + dx * t;
      const iy = lp.y + dy * t;
      const ip = lp.pressure + (p.pressure - lp.pressure) * t;
      stampAt(ctx, ix, iy, ip);
    }

    lastPoint.current = p;
  }

  function handlePointerUp(e) {
    if (!isDrawing) return;
    e.preventDefault();
    setIsDrawing(false);
    lastPoint.current = null;
    pushUndo(ctxRef.current);
  }

  // ── Export canvas as data URI ───────────────────────────────────────
  function exportDataURI() {
    return canvasRef.current?.toDataURL("image/png") || null;
  }

  // Expose export function to parent via callback
  useEffect(() => {
    if (onCanvasReady) {
      canvasRef.current._exportDataURI = exportDataURI;
    }
  });

  // ── Photoshop .abr brush import ────────────────────────────────────
  /**
   * Parse a Photoshop .abr brush file.
   * The .abr format is a binary container. We extract brush tip thumbnails
   * (PNG images embedded in the file) and use them as stamp textures.
   *
   * This is a simplified parser that handles ABR version 6+ (used by
   * Photoshop CS+). It scans for embedded PNG thumbnails.
   */
  async function handleAbrImport(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      const buf = await file.arrayBuffer();
      const bytes = new Uint8Array(buf);
      const brushes = extractAbrThumbnails(bytes, file.name);
      if (brushes.length === 0) {
        alert("No brush thumbnails found in this .abr file. It may use an older format.");
        return;
      }
      setCustomBrushes((prev) => [...prev, ...brushes]);
      setSelectedCustomBrush(brushes[0]);
    } catch (err) {
      alert(`Failed to parse .abr file: ${err.message}`);
    }
    e.target.value = "";
  }

  /**
   * Extract PNG thumbnails from an ABR binary buffer.
   * ABR files embed brush tip previews as PNG images. We scan for the
   * PNG magic bytes (89 50 4E 47) and extract each embedded image.
   */
  function extractAbrThumbnails(bytes, fileName) {
    const brushes = [];
    const PNG_MAGIC = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
    const PNG_END = [0x49, 0x45, 0x4e, 0x44]; // "IEND"

    let pos = 0;
    let brushIndex = 0;

    while (pos < bytes.length - 8) {
      // Find PNG header
      if (matchBytes(bytes, pos, PNG_MAGIC)) {
        const pngStart = pos;
        // Find IEND chunk
        let end = pos + 8;
        while (end < bytes.length - 4) {
          if (matchBytes(bytes, end, PNG_END)) {
            end += 8; // include IEND + CRC
            break;
          }
          end++;
        }

        if (end > pngStart) {
          const pngData = bytes.slice(pngStart, end);
          const blob = new Blob([pngData], { type: "image/png" });
          const url = URL.createObjectURL(blob);
          brushes.push({
            id: `abr_${Date.now()}_${brushIndex}`,
            label: `${fileName.replace(/\.abr$/i, "")} ${brushIndex + 1}`,
            shape: "round",
            hardness: 0.5,
            textureUrl: url,
            scatter: 0,
          });
          brushIndex++;
          pos = end;
          continue;
        }
      }
      pos++;
    }

    return brushes;
  }

  function matchBytes(bytes, pos, pattern) {
    for (let i = 0; i < pattern.length; i++) {
      if (bytes[pos + i] !== pattern[i]) return false;
    }
    return true;
  }

  // Load texture images for custom brushes
  useEffect(() => {
    customBrushes.forEach((brush) => {
      if (!brush.textureUrl || brush.textureImg) return;
      const img = new Image();
      img.onload = () => {
        brush.textureImg = img;
      };
      img.src = brush.textureUrl;
    });
  }, [customBrushes]);

  // ── Color helpers ──────────────────────────────────────────────────
  function hexToRgba(hex, alpha) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  // ── Color swatches ─────────────────────────────────────────────────
  const SWATCHES = [
    "#c6ff3a", "#ff3a8c", "#3a8cff", "#ff8c3a", "#8c3aff",
    "#ffffff", "#888888", "#000000", "#ff3a3a", "#3aff8c",
  ];

  const allBrushes = [...BUILTIN_BRUSHES, ...customBrushes];

  return (
    <div className="draw-canvas">
      {/* ── Toolbar ─────────────────────────────────────────────────── */}
      <div className="draw-toolbar">
        <div className="draw-toolbar__group">
          <button
            className={`tool-btn ${tool === "brush" ? "tool-btn--active" : ""}`}
            onClick={() => setTool("brush")}
            title="Brush"
          >
            🖌
          </button>
          <button
            className={`tool-btn ${tool === "eraser" ? "tool-btn--active" : ""}`}
            onClick={() => setTool("eraser")}
            title="Eraser"
          >
            ⌫
          </button>
        </div>

        <div className="draw-toolbar__group draw-toolbar__group--brushes">
          {BUILTIN_BRUSHES.map((b) => (
            <button
              key={b.id}
              className={`brush-chip ${brushId === b.id && !selectedCustomBrush ? "brush-chip--active" : ""}`}
              onClick={() => { setBrushId(b.id); setSelectedCustomBrush(null); }}
              title={b.label}
            >
              {b.label}
            </button>
          ))}
          {customBrushes.map((b) => (
            <button
              key={b.id}
              className={`brush-chip brush-chip--custom ${selectedCustomBrush?.id === b.id ? "brush-chip--active" : ""}`}
              onClick={() => { setSelectedCustomBrush(b); setTool("brush"); }}
              title={b.label}
            >
              {b.textureUrl && <img src={b.textureUrl} alt={b.label} className="brush-chip__thumb" />}
              <span>{b.label}</span>
            </button>
          ))}
          <label className="brush-chip brush-chip--import" title="Import Photoshop .abr brushes">
            <input type="file" accept=".abr" onChange={handleAbrImport} hidden />
            + ABR
          </label>
        </div>

        <div className="draw-toolbar__group">
          <button className="tool-btn" onClick={handleUndo} disabled={!canUndo} title="Undo">↶</button>
          <button className="tool-btn" onClick={handleRedo} disabled={!canRedo} title="Redo">↷</button>
          <button className="tool-btn tool-btn--danger" onClick={handleClear} title="Clear">✕</button>
        </div>
      </div>

      {/* ── Canvas ──────────────────────────────────────────────────── */}
      <div className="canvas-wrap">
        <canvas
          ref={canvasRef}
          className="draw-surface"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
          style={{ touchAction: "none" }}
        />
      </div>

      {/* ── Controls ────────────────────────────────────────────────── */}
      <div className="draw-controls">
        <div className="draw-controls__row">
          <label className="draw-slider">
            <span className="draw-slider__label">Size</span>
            <input type="range" min="1" max="200" value={size} onChange={(e) => setSize(+e.target.value)} />
            <span className="draw-slider__val">{size}px</span>
          </label>
          <label className="draw-slider">
            <span className="draw-slider__label">Opacity</span>
            <input type="range" min="1" max="100" value={Math.round(opacity * 100)} onChange={(e) => setOpacity(+e.target.value / 100)} />
            <span className="draw-slider__val">{Math.round(opacity * 100)}%</span>
          </label>
          <label className="draw-slider">
            <span className="draw-slider__label">Hardness</span>
            <input type="range" min="0" max="100" value={Math.round(hardness * 100)} onChange={(e) => setHardness(+e.target.value / 100)} />
            <span className="draw-slider__val">{Math.round(hardness * 100)}%</span>
          </label>
          <label className="draw-slider">
            <span className="draw-slider__label">Flow</span>
            <input type="range" min="1" max="100" value={Math.round(flow * 100)} onChange={(e) => setFlow(+e.target.value / 100)} />
            <span className="draw-slider__val">{Math.round(flow * 100)}%</span>
          </label>
        </div>

        <div className="draw-controls__row draw-controls__row--colors">
          <div className="color-swatches">
            {SWATCHES.map((c) => (
              <button
                key={c}
                className={`swatch ${color === c ? "swatch--active" : ""}`}
                style={{ background: c }}
                onClick={() => setColor(c)}
              />
            ))}
          </div>
          <label className="color-picker-wrap">
            <input type="color" value={color} onChange={(e) => setColor(e.target.value)} />
            <span className="color-picker-wrap__label">{color}</span>
          </label>
        </div>
      </div>
    </div>
  );
}
