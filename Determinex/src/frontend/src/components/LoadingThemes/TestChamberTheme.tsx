"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

export function TestChamberTheme({
  active,
  label = "Oracle is thinking...",
  fullPanel = false,
  elapsedSeconds,
}: LoadingThemeProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!active) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let w = (canvas.width = canvas.parentElement?.clientWidth || 400);
    let h = (canvas.height = canvas.parentElement?.clientHeight || 200);
    const ro = new ResizeObserver(() => {
      if (canvas.parentElement) {
        w = canvas.width = canvas.parentElement.clientWidth;
        h = canvas.height = canvas.parentElement.clientHeight;
      }
    });
    if (canvas.parentElement) ro.observe(canvas.parentElement);

    let raf: number,
      t = 0;
    const draw = () => {
      ctx.fillStyle = "rgba(245,245,245,0.18)";
      ctx.fillRect(0, 0, w, h);
      // White tile grid
      ctx.strokeStyle = "rgba(180,180,180,0.32)";
      ctx.lineWidth = 1;
      const tile = 28;
      for (let x = 0; x <= w; x += tile) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      for (let y = 0; y <= h; y += tile) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      // Two portal swirls (blue + orange)
      const drawPortal = (cx: number, cy: number, color: string) => {
        for (let i = 0; i < 5; i++) {
          ctx.strokeStyle = color.replace("X", String(0.45 - i * 0.07));
          ctx.lineWidth = 2;
          const rad = 26 - i * 3;
          ctx.beginPath();
          ctx.ellipse(cx, cy, rad, rad * 0.6, t * 0.02 + i * 0.4, 0, Math.PI * 2);
          ctx.stroke();
        }
      };
      drawPortal(w * 0.28, h * 0.5, "rgba(80,180,255,X)");
      drawPortal(w * 0.72, h * 0.5, "rgba(255,150,40,X)");
      // Trail
      ctx.strokeStyle = "rgba(120,200,255,0.30)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(w * 0.28, h * 0.5);
      ctx.bezierCurveTo(w * 0.45, h * 0.3, w * 0.55, h * 0.7, w * 0.72, h * 0.5);
      ctx.stroke();
      t += 2;
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [active]);
  if (!active) return null;
  const primary = "#1a1a1a",
    dim = "rgba(60,60,60,0.6)";
  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#f0f0f0" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(240,240,240,0)_0%,rgba(220,220,220,0.55)_100%)]" />
        <ThemeOverlay
          label={label}
          elapsedSeconds={elapsedSeconds}
          primary={primary}
          dim={dim}
          subLabel="test chamber loaded — proceed when ready"
          arrow="●"
          rolePalette={{
            oracle: "#1a78c4",
            architect: "#d96b00",
            builder: "#1a78c4",
            compiler: "#d96b00",
          }}
          chipShape="ring"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#f0f0f0" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-90" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
