"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

const TARGET_LINES = [
  "SCAN: ACTIVE",
  "OBJECT CLASS: SOURCE TREE",
  "THREAT: UNSCORED",
  "INTENT: REPAIR",
  "OVERRIDE: REQUIRES AUTHORITY",
];

export function EndoframeHUDTheme({
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
      ctx.fillStyle = "rgba(8,0,0,0.28)";
      ctx.fillRect(0, 0, w, h);
      // Vertical scanlines (CRT)
      ctx.strokeStyle = "rgba(255,40,40,0.07)";
      ctx.lineWidth = 1;
      for (let y = 0; y < h; y += 2) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      // Reticle crosshair
      const cx = w / 2,
        cy = h / 2;
      ctx.strokeStyle = "rgba(255,32,32,0.55)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, 36 + Math.sin(t * 0.04) * 3, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx, cy, 64 + Math.sin(t * 0.03) * 4, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(cx - 90, cy);
      ctx.lineTo(cx + 90, cy);
      ctx.moveTo(cx, cy - 90);
      ctx.lineTo(cx, cy + 90);
      ctx.stroke();
      // Sweep
      ctx.strokeStyle = "rgba(255,128,80,0.35)";
      ctx.beginPath();
      const sweep = (t * 0.02) % (Math.PI * 2);
      ctx.arc(cx, cy, 64, sweep, sweep + 0.8);
      ctx.stroke();
      // Bracket corners
      ctx.strokeStyle = "rgba(255,32,32,0.75)";
      ctx.lineWidth = 2;
      const off = 90;
      [
        [-1, -1],
        [1, -1],
        [-1, 1],
        [1, 1],
      ].forEach(([sx, sy]) => {
        ctx.beginPath();
        ctx.moveTo(cx + sx * off, cy + sy * (off - 12));
        ctx.lineTo(cx + sx * off, cy + sy * off);
        ctx.lineTo(cx + sx * (off - 12), cy + sy * off);
        ctx.stroke();
      });
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
  const primary = "#ff2222",
    dim = "rgba(255,80,80,0.55)";
  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#0a0000" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(10,0,0,0)_0%,rgba(10,0,0,0.85)_100%)]" />
        <div className="absolute top-6 left-8 flex flex-col gap-1 pointer-events-none">
          {TARGET_LINES.map((l, i) => (
            <p key={i} className="text-meta font-mono tracking-widest" style={{ color: dim }}>
              {">"} {l}
            </p>
          ))}
        </div>
        <ThemeOverlay
          label={label}
          elapsedSeconds={elapsedSeconds}
          primary={primary}
          dim={dim}
          subLabel="endoframe vision — diagnostic only"
          arrow="►"
          chipShape="square"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#0a0000" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-80" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
