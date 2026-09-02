"use client";

import { useEffect, useRef } from "react";
import { useIterationTheme } from "@/contexts/IterationThemeContext";
import type { SkinPack } from "@/theme/skinPacks";

function hexToRgb(hex: string) {
  const cleaned = hex.replace("#", "");
  if (cleaned.length !== 6) return { r: 255, g: 255, b: 255 };
  return {
    r: Number.parseInt(cleaned.slice(0, 2), 16),
    g: Number.parseInt(cleaned.slice(2, 4), 16),
    b: Number.parseInt(cleaned.slice(4, 6), 16),
  };
}

function alpha(hex: string, opacity: number) {
  const { r, g, b } = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

function drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number, pack: SkinPack, t: number) {
  const step = pack.id === "vector" ? 64 : 84;
  const offset = (t * 0.018) % step;
  ctx.strokeStyle = alpha(pack.colors.accent, 0.14);
  ctx.lineWidth = 1;
  for (let x = -step; x < w + step; x += step) {
    ctx.beginPath();
    ctx.moveTo(x + offset, 0);
    ctx.lineTo(x - w * 0.1 + offset * 0.4, h);
    ctx.stroke();
  }
  for (let y = -step; y < h + step; y += step) {
    ctx.beginPath();
    ctx.moveTo(0, y + offset);
    ctx.lineTo(w, y + offset * 0.4);
    ctx.stroke();
  }
}

function drawCodefall(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  pack: SkinPack,
  t: number
) {
  const colWidth = 28;
  ctx.font = `11px ${pack.fonts.mono}`;
  ctx.textBaseline = "top";
  for (let x = 0; x < w; x += colWidth) {
    const speed = 0.025 + (x % 7) * 0.004;
    const yOffset = (t * speed + x * 1.7) % (h + 180);
    for (let y = -180; y < h; y += 18) {
      const v = y + yOffset;
      const fade = Math.max(0, 1 - Math.abs(v - h * 0.35) / h);
      ctx.fillStyle = alpha(pack.colors.accent, 0.08 + fade * 0.22);
      ctx.fillText((x + y) % 3 === 0 ? "01" : (x + y) % 5 === 0 ? "{}" : "<>", x, v);
    }
  }
}

function drawLens(ctx: CanvasRenderingContext2D, w: number, h: number, pack: SkinPack, t: number) {
  const cx = w * 0.78;
  const cy = h * 0.22;
  const pulse = Math.sin(t * 0.003) * 0.5 + 0.5;
  for (let i = 0; i < 5; i += 1) {
    ctx.beginPath();
    ctx.strokeStyle = alpha(pack.colors.accent, 0.26 - i * 0.035);
    ctx.lineWidth = 1.5;
    ctx.arc(cx, cy, 42 + i * 34 + pulse * 18, 0, Math.PI * 2);
    ctx.stroke();
  }
  const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, 140);
  gradient.addColorStop(0, alpha(pack.colors.accent, 0.35));
  gradient.addColorStop(1, alpha(pack.colors.accent, 0));
  ctx.fillStyle = gradient;
  ctx.fillRect(cx - 160, cy - 160, 320, 320);
}

function drawTerrain(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  pack: SkinPack,
  t: number
) {
  ctx.lineWidth = 1.2;
  for (let row = 0; row < 8; row += 1) {
    ctx.beginPath();
    ctx.strokeStyle = alpha(row % 3 === 0 ? pack.colors.accent3 : pack.colors.accent2, 0.1);
    const base = h * 0.12 + row * 72;
    for (let x = -40; x <= w + 40; x += 24) {
      const y =
        base + Math.sin((x + t * 0.035) * 0.012 + row) * 18 + Math.cos((x - t * 0.02) * 0.019) * 8;
      if (x === -40) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
  ctx.strokeStyle = alpha(pack.colors.accent, 0.22);
  ctx.setLineDash([8, 10]);
  ctx.strokeRect(w * 0.68, h * 0.16, 180, 118);
  ctx.setLineDash([]);
}

function drawRain(ctx: CanvasRenderingContext2D, w: number, h: number, pack: SkinPack, t: number) {
  ctx.lineWidth = 1;
  for (let i = 0; i < 110; i += 1) {
    const x = (i * 47 + t * 0.06) % (w + 120);
    const y = (i * 83 + t * 0.18) % (h + 160);
    ctx.strokeStyle = alpha(i % 4 === 0 ? pack.colors.accent2 : pack.colors.accent, 0.12);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x - 18, y + 64);
    ctx.stroke();
  }
}

function drawOrbit(ctx: CanvasRenderingContext2D, w: number, h: number, pack: SkinPack, t: number) {
  const cx = w * 0.78;
  const cy = h * 0.3;
  ctx.lineWidth = 1.2;
  for (let i = 0; i < 4; i += 1) {
    const r = 54 + i * 34;
    ctx.beginPath();
    ctx.strokeStyle = alpha(i % 2 ? pack.colors.accent2 : pack.colors.accent, 0.16);
    ctx.ellipse(cx, cy, r * 1.45, r, -0.35 + i * 0.16, 0, Math.PI * 2);
    ctx.stroke();
    const a = t * 0.0013 + i * 1.4;
    ctx.fillStyle = alpha(pack.colors.accent3, 0.34);
    ctx.beginPath();
    ctx.arc(cx + Math.cos(a) * r * 1.45, cy + Math.sin(a) * r, 2.2, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawMech(ctx: CanvasRenderingContext2D, w: number, h: number, pack: SkinPack, t: number) {
  ctx.lineWidth = 2;
  ctx.strokeStyle = alpha(pack.colors.accent, 0.18);
  for (let i = -2; i < 8; i += 1) {
    const x = i * 220 + ((t * 0.03) % 220);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x - 120, h);
    ctx.stroke();
  }
  ctx.fillStyle = alpha(pack.colors.accent2, 0.08);
  const scanY = (t * 0.08) % h;
  ctx.fillRect(0, scanY, w, 18);
}

function drawSignals(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  pack: SkinPack,
  t: number
) {
  ctx.lineWidth = 1;
  for (let i = 0; i < 70; i += 1) {
    const x = (i * 137.5) % w;
    const y = (i * 73.25) % h;
    const pulse = Math.sin(t * 0.002 + i) * 0.5 + 0.5;
    ctx.fillStyle = alpha(i % 2 ? pack.colors.accent2 : pack.colors.accent, 0.08 + pulse * 0.1);
    ctx.beginPath();
    ctx.arc(x, y, 1.3 + pulse * 1.4, 0, Math.PI * 2);
    ctx.fill();
  }
}

export function SkinBackdrop() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { themePack } = useIterationTheme();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    let w = 0;
    let h = 0;
    let dpr = 1;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
      w = Math.max(1, rect.width);
      h = Math.max(1, rect.height);
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = (time: number) => {
      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";
      drawGrid(ctx, w, h, themePack, time);
      ctx.globalCompositeOperation = "lighter";

      switch (themePack.iconKey) {
        case "binary":
          drawCodefall(ctx, w, h, themePack, time);
          break;
        case "lens":
          drawLens(ctx, w, h, themePack, time);
          break;
        case "terrain":
          drawTerrain(ctx, w, h, themePack, time);
          break;
        case "rain":
          drawRain(ctx, w, h, themePack, time);
          break;
        case "mech":
          drawMech(ctx, w, h, themePack, time);
          break;
        case "orbit":
        case "atlas":
        case "signal":
        case "ring":
          drawOrbit(ctx, w, h, themePack, time);
          drawSignals(ctx, w, h, themePack, time);
          break;
        default:
          drawSignals(ctx, w, h, themePack, time);
          break;
      }

      if (!reduceMotion) raf = requestAnimationFrame(draw);
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    draw(0);
    if (!reduceMotion) raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [themePack]);

  const isLogo = themePack.backdropImage?.includes("determinex-logo");

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <div className="matrix-rain absolute inset-0" />

      {/* Generated Artwork Backdrop */}
      {themePack.backdropImage && (
        <div
          className={`absolute inset-0 transition-all duration-1000 ${isLogo ? "bg-contain bg-center bg-no-repeat m-32" : "bg-cover bg-center"}`}
          style={{
            backgroundImage: `url('${themePack.backdropImage}')`,
            opacity: isLogo ? (themePack.id === "plainlight" ? 0.2 : 0.4) : 0.4,
            filter: isLogo ? "none" : "saturate(1.2) contrast(1.1)",
            mixBlendMode: themePack.id === "plainlight" ? "multiply" : "screen",
          }}
        />
      )}

      <canvas
        ref={canvasRef}
        className="absolute inset-0 h-full w-full"
        style={{
          opacity: themePack.id === "plainlight" ? 0.52 : 0.82,
          mixBlendMode: themePack.rainBlend,
        }}
      />
    </div>
  );
}
