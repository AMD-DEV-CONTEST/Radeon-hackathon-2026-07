"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

export function AetherConsoleTheme({
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

    // Crystalline lattice particles drifting upward
    const N = 80;
    const particles = Array.from({ length: N }, () => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.15,
      vy: -0.25 - Math.random() * 0.4,
      r: 0.6 + Math.random() * 1.4,
      ph: Math.random() * Math.PI * 2,
    }));

    let raf: number,
      t = 0;
    const draw = () => {
      ctx.fillStyle = "rgba(2,4,10,0.18)";
      ctx.fillRect(0, 0, w, h);
      // Soft glow center
      const grad = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.min(w, h) / 2);
      grad.addColorStop(0, "rgba(180,210,255,0.10)");
      grad.addColorStop(1, "rgba(2,4,10,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);
      // Particles
      particles.forEach((p) => {
        p.x += p.vx + Math.sin(t * 0.01 + p.ph) * 0.1;
        p.y += p.vy;
        if (p.y < -4) {
          p.y = h + 4;
          p.x = Math.random() * w;
        }
        const a = 0.35 + Math.sin(t * 0.04 + p.ph) * 0.25;
        ctx.fillStyle = `rgba(190,220,255,${a})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      });
      // Connect near pairs (lattice)
      ctx.strokeStyle = "rgba(170,210,255,0.10)";
      ctx.lineWidth = 0.6;
      for (let i = 0; i < N; i++) {
        for (let j = i + 1; j < N; j++) {
          const dx = particles[i].x - particles[j].x,
            dy = particles[i].y - particles[j].y;
          const d2 = dx * dx + dy * dy;
          if (d2 < 3600) {
            ctx.beginPath();
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.stroke();
          }
        }
      }
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
  const primary = "#cfe3ff",
    dim = "rgba(180,210,255,0.45)";
  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#02040a" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(2,4,10,0)_0%,rgba(2,4,10,0.85)_100%)]" />
        <ThemeOverlay
          label={label}
          elapsedSeconds={elapsedSeconds}
          primary={primary}
          dim={dim}
          subLabel="aether lattice resonating — patience"
          arrow="·"
          chipShape="ring"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#02040a" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-70" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
