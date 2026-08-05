"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

export function CaveConsoleTheme({
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
    // Stalactite jagged backdrop
    const draw = () => {
      ctx.fillStyle = "rgba(8,6,2,0.30)";
      ctx.fillRect(0, 0, w, h);
      // Wide angular slabs sweeping a faint amber pulse
      const cx = w / 2;
      for (let i = 0; i < 8; i++) {
        const ang = (i / 8) * Math.PI * 2 + t * 0.002;
        const r = 90 + Math.sin(t * 0.01 + i) * 12;
        const x = cx + Math.cos(ang) * r;
        const y = h / 2 + Math.sin(ang) * r;
        ctx.strokeStyle = `rgba(255,176,32,${0.1 + (i % 3) * 0.05})`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(cx, h / 2);
        ctx.lineTo(x, y);
        ctx.stroke();
      }
      // Glyph swarm
      for (let i = 0; i < 24; i++) {
        const ang = (i / 24) * Math.PI * 2 + Math.sin(t * 0.008 + i) * 0.1;
        const r = 130 + (i % 3) * 14;
        const x = cx + Math.cos(ang) * r;
        const y = h / 2 + Math.sin(ang) * r * 0.6;
        ctx.fillStyle = `rgba(255,196,80,${0.08 + Math.abs(Math.sin(t * 0.02 + i)) * 0.18})`;
        ctx.fillRect(x, y, 3, 5);
      }
      // Scan beam from above
      const beamY = (t * 1.5) % h;
      const grad = ctx.createLinearGradient(0, beamY - 24, 0, beamY + 24);
      grad.addColorStop(0, "rgba(255,176,32,0)");
      grad.addColorStop(0.5, "rgba(255,196,80,0.18)");
      grad.addColorStop(1, "rgba(255,176,32,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, beamY - 24, w, 48);
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
  const primary = "#ffc24a",
    dim = "rgba(255,196,80,0.45)";
  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#08060f" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(8,6,15,0)_0%,rgba(0,0,0,0.78)_100%)]" />
        <ThemeOverlay
          label={label}
          elapsedSeconds={elapsedSeconds}
          primary={primary}
          dim={dim}
          subLabel="cave systems online — silent watch"
          arrow="▸"
          chipShape="diamond"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#08060f" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-75" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
