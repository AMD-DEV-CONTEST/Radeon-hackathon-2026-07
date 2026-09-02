"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

const DIAG = [
  "SERVO BANK A: NOMINAL",
  "SERVO BANK B: NOMINAL",
  "HYDRAULIC PRESSURE: 92%",
  "ARMOR INTEGRITY: 100%",
  "POWER CORE: STABLE",
  "RELEASE GATE: CLOSED",
];

export function MechBayTheme({
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
      ctx.fillStyle = "rgba(10,10,10,0.25)";
      ctx.fillRect(0, 0, w, h);
      // Vertical gantry beams
      ctx.strokeStyle = "rgba(255,200,60,0.18)";
      ctx.lineWidth = 2;
      for (let x = w * 0.18; x < w * 0.82; x += 60) {
        ctx.beginPath();
        ctx.moveTo(x, h * 0.1);
        ctx.lineTo(x, h * 0.85);
        ctx.stroke();
      }
      // Horizontal gantry crossbars
      ctx.strokeStyle = "rgba(255,200,60,0.30)";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(w * 0.1, h * 0.1);
      ctx.lineTo(w * 0.9, h * 0.1);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(w * 0.1, h * 0.85);
      ctx.lineTo(w * 0.9, h * 0.85);
      ctx.stroke();
      // Central mech silhouette (blocky)
      const cx = w / 2,
        cy = h * 0.5;
      ctx.fillStyle = "rgba(40,40,50,0.85)";
      ctx.fillRect(cx - 36, cy - 60, 72, 30); // chest
      ctx.fillRect(cx - 50, cy - 30, 28, 60); // left shoulder/arm
      ctx.fillRect(cx + 22, cy - 30, 28, 60); // right shoulder/arm
      ctx.fillRect(cx - 26, cy + 30, 22, 60); // left leg
      ctx.fillRect(cx + 4, cy + 30, 22, 60); // right leg
      ctx.fillRect(cx - 14, cy - 80, 28, 22); // head
      // Eye glow
      const glow = 0.6 + Math.sin(t * 0.06) * 0.35;
      ctx.fillStyle = `rgba(255,200,60,${glow})`;
      ctx.fillRect(cx - 8, cy - 70, 16, 4);
      // Pulse line on chest
      ctx.strokeStyle = "rgba(120,255,200,0.65)";
      ctx.beginPath();
      for (let x = cx - 30; x < cx + 30; x++) {
        const y = cy - 45 + Math.sin((x + t) * 0.4) * 6;
        if (x === cx - 30) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      // Sparks
      for (let i = 0; i < 6; i++) {
        const sx = cx + Math.sin(t * 0.05 + i) * 90;
        const sy = cy + Math.cos(t * 0.08 + i) * 50;
        ctx.fillStyle = `rgba(255,180,40,${0.4 + Math.sin(t * 0.1 + i) * 0.4})`;
        ctx.fillRect(sx, sy, 2, 2);
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
  const primary = "#ffc83c",
    dim = "rgba(255,200,60,0.5)";
  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#0a0a0a" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(10,10,10,0)_0%,rgba(10,10,10,0.75)_100%)]" />
        <div className="absolute top-6 right-8 flex flex-col gap-0.5 text-right">
          {DIAG.map((l, i) => (
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
          subLabel="mech bay diagnostic — release gate closed"
          arrow="▣"
          rolePalette={{
            oracle: "#ffc83c",
            architect: "#78ffc8",
            builder: "#ffc83c",
            compiler: "#ff7a4a",
          }}
          chipShape="square"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#0a0a0a" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-85" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
