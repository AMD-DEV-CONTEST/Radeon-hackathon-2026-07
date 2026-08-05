"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

export function RingArrayTheme({
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
      ctx.fillStyle = "rgba(0,8,16,0.20)";
      ctx.fillRect(0, 0, w, h);
      const cx = w / 2,
        cy = h / 2;
      // Concentric ring arrays
      for (let r = 30; r < Math.min(w, h); r += 18) {
        const phase = (t * 0.003 + r * 0.02) % (Math.PI * 2);
        ctx.strokeStyle = `rgba(80,200,255,${0.05 + Math.abs(Math.sin(phase)) * 0.12})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();
        // Glyph studs
        for (let a = 0; a < 8; a++) {
          const ang = (a / 8) * Math.PI * 2 + phase;
          const x = cx + Math.cos(ang) * r;
          const y = cy + Math.sin(ang) * r * 0.4; // tilted ellipse
          ctx.fillStyle = `rgba(140,220,255,${0.2 + (r / 200) * 0.1})`;
          ctx.fillRect(x - 1, y - 1, 2, 2);
        }
      }
      // Slow rotating outer arc
      ctx.strokeStyle = "rgba(120,220,255,0.45)";
      ctx.lineWidth = 2;
      const start = (t * 0.01) % (Math.PI * 2);
      ctx.beginPath();
      ctx.arc(cx, cy, Math.min(w, h) * 0.42, start, start + 1.5);
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
  const primary = "#82d8ff",
    dim = "rgba(130,216,255,0.45)";
  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#001016" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,16,22,0)_0%,rgba(0,8,12,0.78)_100%)]" />
        <ThemeOverlay
          label={label}
          elapsedSeconds={elapsedSeconds}
          primary={primary}
          dim={dim}
          subLabel="ring array calibrating"
          arrow="◯"
          chipShape="ring"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#001016" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-80" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
