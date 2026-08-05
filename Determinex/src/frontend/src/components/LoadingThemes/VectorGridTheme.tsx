"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";

export function VectorGridTheme({
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

    let tick = 0;
    const BLUE = "#00d4ff";
    const GOLD = "#e8c547";

    // Vector trails
    interface Cycle {
      x: number;
      y: number;
      vx: number;
      vy: number;
      trail: { x: number; y: number }[];
      color: string;
    }
    const cycles: Cycle[] = [
      { x: w * 0.3, y: h * 0.5, vx: 2, vy: 0, trail: [], color: BLUE },
      { x: w * 0.7, y: h * 0.5, vx: -2, vy: 0, trail: [], color: GOLD },
    ];

    let raf: number;
    const draw = () => {
      ctx.fillStyle = "rgba(0,5,20,0.12)";
      ctx.fillRect(0, 0, w, h);

      const vp = { x: w / 2, y: h * 0.42 }; // vanishing point
      const GRID_LINES = 18;
      const GRID_ROWS = 12;

      // Perspective grid floor
      for (let i = 0; i <= GRID_LINES; i++) {
        const t = i / GRID_LINES;
        const lx = w * t;
        const alpha = 0.06 + (i % 3 === 0 ? 0.08 : 0);
        ctx.beginPath();
        ctx.moveTo(vp.x + (lx - vp.x) * 0.05, vp.y);
        ctx.lineTo(lx, h);
        ctx.strokeStyle = `rgba(0,212,255,${alpha})`;
        ctx.lineWidth = i % 3 === 0 ? 0.8 : 0.4;
        ctx.stroke();
      }
      for (let j = 0; j <= GRID_ROWS; j++) {
        const t = j / GRID_ROWS;
        const gy = vp.y + (h - vp.y) * Math.pow(t, 1.6);
        const spread = vp.x * (1 - Math.pow(1 - t, 2));
        const alpha = 0.04 + t * 0.12;
        ctx.beginPath();
        ctx.moveTo(vp.x - spread, gy);
        ctx.lineTo(vp.x + spread, gy);
        ctx.strokeStyle = `rgba(0,212,255,${alpha})`;
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }

      // Vector trail movement
      cycles.forEach((cycle) => {
        cycle.trail.push({ x: cycle.x, y: cycle.y });
        if (cycle.trail.length > 80) cycle.trail.shift();

        // Bounce
        if (cycle.x < 10 || cycle.x > w - 10) {
          cycle.vx *= -1;
          if (Math.random() < 0.3) {
            cycle.vy = (Math.random() - 0.5) * 2;
          }
        }
        if (cycle.y < h * 0.5 || cycle.y > h - 10) {
          cycle.vy *= -1;
        }
        cycle.x += cycle.vx;
        cycle.y += cycle.vy;

        // Draw trail
        for (let t = 1; t < cycle.trail.length; t++) {
          const alpha = t / cycle.trail.length;
          ctx.beginPath();
          ctx.moveTo(cycle.trail[t - 1].x, cycle.trail[t - 1].y);
          ctx.lineTo(cycle.trail[t].x, cycle.trail[t].y);
          ctx.strokeStyle =
            cycle.color +
            Math.floor(alpha * 200)
              .toString(16)
              .padStart(2, "0");
          ctx.lineWidth = 2;
          ctx.stroke();
        }

        // Cycle head glow
        ctx.beginPath();
        ctx.arc(cycle.x, cycle.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = cycle.color;
        ctx.shadowBlur = 12;
        ctx.shadowColor = cycle.color;
        ctx.fill();
        ctx.shadowBlur = 0;
      });

      // Pulsing horizon line
      const horizonAlpha = 0.4 + Math.sin(tick * 0.05) * 0.2;
      ctx.beginPath();
      ctx.moveTo(0, vp.y);
      ctx.lineTo(w, vp.y);
      ctx.strokeStyle = `rgba(0,212,255,${horizonAlpha})`;
      ctx.lineWidth = 1;
      ctx.shadowBlur = 8;
      ctx.shadowColor = BLUE;
      ctx.stroke();
      ctx.shadowBlur = 0;

      tick++;
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [active]);

  if (!active) return null;

  const accent = "#00d4ff";
  const gold = "#e8c547";

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#000514" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,5,20,0.0)_0%,rgba(0,5,20,0.65)_100%)]" />

        <div
          className="absolute inset-0 flex flex-col items-center justify-center gap-4"
          style={{ paddingBottom: "20%" }}
        >
          {/* Rotating dual ring */}
          <div className="relative w-16 h-16">
            <div
              className="absolute inset-0 rounded-full border-2 animate-spin"
              style={{
                borderColor: `${accent}40`,
                borderTopColor: accent,
                animationDuration: "1.5s",
              }}
            />
            <div
              className="absolute inset-3 rounded-full border animate-spin"
              style={{
                borderColor: `${gold}30`,
                borderRightColor: gold,
                animationDuration: "2.5s",
                animationDirection: "reverse",
              }}
            />
            {elapsedSeconds !== undefined && elapsedSeconds > 0 && (
              <div className="absolute inset-0 flex items-center justify-center">
                <span
                  className="text-meta font-mono font-bold tabular-nums"
                  style={{ color: accent }}
                >
                  {elapsedSeconds}s
                </span>
              </div>
            )}
          </div>

          <div className="flex flex-col items-center gap-1">
            <p
              className="text-eyebrow font-mono tracking-[0.6em] uppercase"
              style={{ color: `${accent}60` }}
            >
              END OF LINE
            </p>
            <p
              className="text-title font-mono font-bold tracking-widest uppercase"
              style={{ color: accent, textShadow: `0 0 16px ${accent}` }}
            >
              {label}
            </p>
            <p className="text-meta font-mono" style={{ color: `${gold}70` }}>
              GRID CYCLE ACTIVE • PROGRAM EXECUTING
            </p>
          </div>

          <div className="flex items-center gap-3 mt-2">
            {[
              { role: "Oracle", active: true, color: accent },
              { role: "Architect", active: false, color: accent },
              { role: "Builder", active: false, color: accent },
              { role: "Compiler", active: false, color: gold },
            ].map(({ role, active: nodeActive, color }, i, arr) => (
              <React.Fragment key={role}>
                <div className="flex flex-col items-center gap-1">
                  <div
                    className="w-5 h-5 rounded-full border-2 flex items-center justify-center"
                    style={{
                      borderColor: nodeActive ? color : `${color}25`,
                      background: nodeActive ? `${color}15` : "transparent",
                      boxShadow: nodeActive ? `0 0 10px ${color}60` : "none",
                    }}
                  >
                    <div
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: color, opacity: nodeActive ? 1 : 0.2 }}
                    />
                  </div>
                  <span
                    className="text-eyebrow font-mono uppercase tracking-wider"
                    style={{ color, opacity: nodeActive ? 1 : 0.3 }}
                  >
                    {role}
                  </span>
                </div>
                {i < arr.length - 1 && (
                  <div className="w-4 h-px mb-4" style={{ background: `${accent}30` }} />
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#000514" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,5,20,0.2)_0%,rgba(0,5,20,0.85)_100%)]" />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
        <div
          className="w-6 h-6 border-2 rounded-full animate-spin"
          style={{ borderColor: `${accent}40`, borderTopColor: accent }}
        />
        <p className="text-meta font-mono tracking-widest uppercase" style={{ color: accent }}>
          {label}
        </p>
      </div>
    </div>
  );
}
