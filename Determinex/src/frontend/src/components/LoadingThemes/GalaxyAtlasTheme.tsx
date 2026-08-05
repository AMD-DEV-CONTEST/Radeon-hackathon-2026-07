"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

export function GalaxyAtlasTheme({
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

    const stars = Array.from({ length: 180 }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      r: Math.random() * 1.2 + 0.2,
      p: Math.random() * Math.PI * 2,
    }));
    let raf: number,
      t = 0;
    const draw = () => {
      ctx.fillStyle = "rgba(6,4,18,0.30)";
      ctx.fillRect(0, 0, w, h);
      // Spiral arms (parametric)
      const cx = w / 2,
        cy = h / 2;
      for (let arm = 0; arm < 3; arm++) {
        ctx.strokeStyle = `rgba(140,120,255,${0.18 - arm * 0.04})`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        for (let s = 0; s < 220; s++) {
          const a = arm * ((Math.PI * 2) / 3) + s * 0.03 + t * 0.0015;
          const r = 6 + s * 0.7;
          const x = cx + Math.cos(a) * r;
          const y = cy + Math.sin(a) * r * 0.55;
          if (s === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      // Stars twinkle
      stars.forEach((s) => {
        const a = 0.4 + Math.sin(t * 0.04 + s.p) * 0.4;
        ctx.fillStyle = `rgba(220,210,255,${a})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();
      });
      // Hex tile pickers
      const drawHex = (x: number, y: number, size: number, color: string) => {
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 0; i < 6; i++) {
          const a = (i / 6) * Math.PI * 2 + Math.PI / 6;
          const px = x + Math.cos(a) * size,
            py = y + Math.sin(a) * size;
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.stroke();
      };
      drawHex(w - 80, 60, 18, "rgba(180,160,255,0.45)");
      drawHex(60, h - 50, 14, "rgba(180,160,255,0.45)");
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
  const primary = "#c4b5ff",
    dim = "rgba(196,181,255,0.5)";
  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#060412" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(6,4,18,0)_0%,rgba(6,4,18,0.78)_100%)]" />
        <ThemeOverlay
          label={label}
          elapsedSeconds={elapsedSeconds}
          primary={primary}
          dim={dim}
          subLabel="galactic atlas synchronized"
          arrow="◈"
          chipShape="ring"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#060412" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-80" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
