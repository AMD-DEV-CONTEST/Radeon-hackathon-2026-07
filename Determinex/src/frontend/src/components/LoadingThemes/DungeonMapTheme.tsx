"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

const PARTY_LINES = [
  "Oracle reads the room.",
  "Architect plans the corridor.",
  "Builder picks the lock.",
  "Compiler casts truth.",
];

export function DungeonMapTheme({
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
    const ROOMS = [
      { x: 0.18, y: 0.28, w: 0.16, h: 0.18 },
      { x: 0.48, y: 0.22, w: 0.18, h: 0.22 },
      { x: 0.74, y: 0.4, w: 0.14, h: 0.18 },
      { x: 0.3, y: 0.62, w: 0.2, h: 0.16 },
      { x: 0.58, y: 0.66, w: 0.16, h: 0.14 },
    ];
    const draw = () => {
      // Parchment fade
      ctx.fillStyle = "rgba(20,16,10,0.28)";
      ctx.fillRect(0, 0, w, h);
      // Grid graph paper
      ctx.strokeStyle = "rgba(120,90,40,0.10)";
      ctx.lineWidth = 1;
      for (let x = 0; x < w; x += 16) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      for (let y = 0; y < h; y += 16) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      // Rooms
      ROOMS.forEach((r, i) => {
        ctx.strokeStyle = `rgba(120,200,90,${0.45 + Math.sin(t * 0.04 + i) * 0.18})`;
        ctx.lineWidth = 2;
        ctx.strokeRect(r.x * w, r.y * h, r.w * w, r.h * h);
        // floor stipple
        ctx.fillStyle = "rgba(120,200,90,0.06)";
        ctx.fillRect(r.x * w, r.y * h, r.w * w, r.h * h);
      });
      // Corridors between rooms
      ctx.strokeStyle = "rgba(180,220,140,0.45)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < ROOMS.length - 1; i++) {
        const a = ROOMS[i],
          b = ROOMS[i + 1];
        const ax = (a.x + a.w / 2) * w,
          ay = (a.y + a.h / 2) * h;
        const bx = (b.x + b.w / 2) * w,
          by = (b.y + b.h / 2) * h;
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, ay);
        ctx.lineTo(bx, by);
      }
      ctx.stroke();
      // Party torch (4 dots moving along the path)
      const PATH = ROOMS.flatMap((r, i, arr) => {
        if (i === arr.length - 1) return [];
        const a = ROOMS[i],
          b = ROOMS[i + 1];
        return [
          [(a.x + a.w / 2) * w, (a.y + a.h / 2) * h] as [number, number],
          [(b.x + b.w / 2) * w, (a.y + a.h / 2) * h] as [number, number],
          [(b.x + b.w / 2) * w, (b.y + b.h / 2) * h] as [number, number],
        ];
      });
      const idx = Math.floor((t * 0.02) % PATH.length);
      const [px, py] = PATH[idx];
      const colors = ["#9be38a", "#d6b35a", "#7fbfff", "#ff8a7a"];
      colors.forEach((c, i) => {
        ctx.fillStyle = c + "cc";
        ctx.beginPath();
        ctx.arc(px + (i - 1.5) * 6, py, 3, 0, Math.PI * 2);
        ctx.fill();
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
  const primary = "#cfe7a6",
    dim = "rgba(207,231,166,0.55)";
  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#0d0a06" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(13,10,6,0)_0%,rgba(13,10,6,0.78)_100%)]" />
        <div className="absolute bottom-6 left-6 flex flex-col gap-0.5">
          {PARTY_LINES.map((l, i) => (
            <p key={i} className="text-label font-serif italic" style={{ color: dim }}>
              · {l}
            </p>
          ))}
        </div>
        <ThemeOverlay
          label={label}
          elapsedSeconds={elapsedSeconds}
          primary={primary}
          dim={dim}
          subLabel="party advances on the map"
          arrow="✦"
          rolePalette={{
            oracle: "#9be38a",
            architect: "#d6b35a",
            builder: "#7fbfff",
            compiler: "#ff8a7a",
          }}
          chipShape="diamond"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#0d0a06" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-85" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
