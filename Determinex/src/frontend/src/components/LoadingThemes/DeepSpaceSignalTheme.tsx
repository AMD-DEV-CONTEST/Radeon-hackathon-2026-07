"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

const TELEMETRY = [
  "T+00:00:00",
  "RANGE 4.2e7 km",
  "DELTA-V 0.0 m/s",
  "SIGNAL +3 dB",
  "AOS NOMINAL",
  "TLM CHAN 6 LOCKED",
];

export function DeepSpaceSignalTheme({
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
      ctx.fillStyle = "rgba(0,4,10,0.22)";
      ctx.fillRect(0, 0, w, h);
      // Starfield + horizon line
      for (let i = 0; i < 120; i++) {
        const x = (Math.sin(i * 12.9) * 0.5 + 0.5) * w;
        const y = (Math.cos(i * 7.7) * 0.5 + 0.5) * h * 0.55;
        const a = 0.35 + Math.sin(t * 0.03 + i) * 0.35;
        ctx.fillStyle = `rgba(220,235,255,${a})`;
        ctx.fillRect(x, y, 1, 1);
      }
      // Horizon
      ctx.strokeStyle = "rgba(120,170,255,0.30)";
      ctx.beginPath();
      ctx.moveTo(0, h * 0.62);
      ctx.lineTo(w, h * 0.62);
      ctx.stroke();
      // Trajectory arc
      ctx.strokeStyle = "rgba(180,210,255,0.55)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (let x = 0; x < w; x++) {
        const y = h * 0.62 - Math.sin((x / w) * Math.PI) * (h * 0.35);
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      // Spacecraft pip
      const px = (t * 0.6) % w;
      const py = h * 0.62 - Math.sin((px / w) * Math.PI) * (h * 0.35);
      ctx.fillStyle = "rgba(255,255,255,0.95)";
      ctx.beginPath();
      ctx.arc(px, py, 2.5, 0, Math.PI * 2);
      ctx.fill();
      // Side ticks
      ctx.strokeStyle = "rgba(180,210,255,0.40)";
      for (let i = 0; i < 10; i++) {
        const y = (i / 10) * h;
        ctx.beginPath();
        ctx.moveTo(w - 18, y);
        ctx.lineTo(w - 8, y);
        ctx.stroke();
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
  const primary = "#b8d2ff",
    dim = "rgba(184,210,255,0.55)";
  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#02060e" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(2,6,14,0)_0%,rgba(2,6,14,0.72)_100%)]" />
        <div className="absolute top-6 left-6 flex flex-col gap-0.5">
          {TELEMETRY.map((l, i) => (
            <p key={i} className="text-meta font-mono tracking-widest" style={{ color: dim }}>
              {l}
            </p>
          ))}
        </div>
        <ThemeOverlay
          label={label}
          elapsedSeconds={elapsedSeconds}
          primary={primary}
          dim={dim}
          subLabel="deep-space signal acquired"
          arrow="►"
          chipShape="square"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#02060e" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-80" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
