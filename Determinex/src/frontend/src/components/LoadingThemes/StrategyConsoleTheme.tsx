"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";

const STRATEGY_LINES = [
  "RUN A STRATEGY PASS?",
  "GLOBAL REGRESSION MAP",
  "CHESS",
  "SEARCH MAZE",
  "GREETINGS OPERATOR",
  "STRATEGY CORE ONLINE",
  "SANDBOX ACCESS GRANTED",
  "SHARD LINK ACTIVE",
  "RISK ANALYSIS",
  "PATCH SEQUENCE NOMINAL",
  "AWAITING AUTHORIZATION",
  "SEARCHING FOR SOLUTION",
];

export function StrategyConsoleTheme({
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

    const GREEN = "#33ff33";
    let tick = 0;

    // Dots representing cities on a map grid
    const dots: { x: number; y: number; label: string; size: number; pulse: number }[] = [
      { x: 0.15, y: 0.35, label: "SEA", size: 3, pulse: 0 },
      { x: 0.28, y: 0.42, label: "SFO", size: 2.5, pulse: 1.2 },
      { x: 0.32, y: 0.55, label: "LAX", size: 3.5, pulse: 0.4 },
      { x: 0.52, y: 0.38, label: "CHI", size: 3, pulse: 2.1 },
      { x: 0.62, y: 0.35, label: "NYC", size: 4, pulse: 0.8 },
      { x: 0.58, y: 0.48, label: "DC", size: 3.5, pulse: 1.6 },
      { x: 0.72, y: 0.25, label: "MON", size: 2, pulse: 3.0 },
      { x: 0.8, y: 0.3, label: "LDN", size: 2.5, pulse: 0.2 },
      { x: 0.42, y: 0.6, label: "DAL", size: 2, pulse: 1.9 },
      { x: 0.88, y: 0.38, label: "PAR", size: 2, pulse: 2.5 },
    ];

    // Arc trajectories between random pairs
    const arcs = Array.from({ length: 6 }, (_, i) => ({
      from: dots[(i * 2) % dots.length],
      to: dots[(i * 2 + 3) % dots.length],
      progress: Math.random(),
      speed: 0.003 + Math.random() * 0.004,
    }));

    let raf: number;
    const draw = () => {
      ctx.fillStyle = "rgba(0,0,0,0.15)";
      ctx.fillRect(0, 0, w, h);

      // Grid lines
      ctx.strokeStyle = "rgba(51,255,51,0.06)";
      ctx.lineWidth = 0.5;
      for (let gx = 0; gx < w; gx += 40) {
        ctx.beginPath();
        ctx.moveTo(gx, 0);
        ctx.lineTo(gx, h);
        ctx.stroke();
      }
      for (let gy = 0; gy < h; gy += 40) {
        ctx.beginPath();
        ctx.moveTo(0, gy);
        ctx.lineTo(w, gy);
        ctx.stroke();
      }

      // Latitude-style curved lines
      ctx.strokeStyle = "rgba(51,255,51,0.05)";
      for (let lat = 0; lat < 5; lat++) {
        ctx.beginPath();
        const ly = h * (0.2 + lat * 0.15);
        for (let lx = 0; lx <= w; lx += 4) {
          const curve = Math.sin((lx / w) * Math.PI) * 8;
          lx === 0 ? ctx.moveTo(lx, ly + curve) : ctx.lineTo(lx, ly + curve);
        }
        ctx.stroke();
      }

      // Arc trajectories
      arcs.forEach((arc) => {
        arc.progress += arc.speed;
        if (arc.progress > 1) arc.progress = 0;
        const fx = arc.from.x * w,
          fy = arc.from.y * h;
        const tx = arc.to.x * w,
          ty = arc.to.y * h;
        const mx = (fx + tx) / 2,
          my = Math.min(fy, ty) - Math.abs(tx - fx) * 0.4;

        // Draw arc up to progress point
        ctx.beginPath();
        ctx.strokeStyle = `rgba(51,255,51,0.5)`;
        ctx.lineWidth = 1;
        for (let t = 0; t <= arc.progress; t += 0.02) {
          const bt = 1 - t;
          const px = bt * bt * fx + 2 * bt * t * mx + t * t * tx;
          const py = bt * bt * fy + 2 * bt * t * my + t * t * ty;
          t === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
        }
        ctx.stroke();

        // Draw warhead dot at tip
        const t = arc.progress;
        const bt = 1 - t;
        const hx = bt * bt * fx + 2 * bt * t * mx + t * t * tx;
        const hy = bt * bt * fy + 2 * bt * t * my + t * t * ty;
        ctx.beginPath();
        ctx.arc(hx, hy, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = "#fff";
        ctx.fill();
      });

      // City dots with pulse rings
      dots.forEach((dot) => {
        const dx = dot.x * w,
          dy = dot.y * h;
        const pulse = Math.sin(tick * 0.04 + dot.pulse) * 0.5 + 0.5;
        // Pulse ring
        ctx.beginPath();
        ctx.arc(dx, dy, dot.size + pulse * 6, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(51,255,51,${0.1 + pulse * 0.15})`;
        ctx.lineWidth = 0.5;
        ctx.stroke();
        // Core dot
        ctx.beginPath();
        ctx.arc(dx, dy, dot.size, 0, Math.PI * 2);
        ctx.fillStyle = GREEN;
        ctx.fill();
        // Label
        ctx.fillStyle = `rgba(51,255,51,0.6)`;
        ctx.font = "7px monospace";
        ctx.fillText(dot.label, dx + dot.size + 2, dy - dot.size);
      });

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

  const accent = "#33ff33";

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden bg-black">
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,0,0,0.1)_0%,rgba(0,0,0,0.72)_100%)]" />

        {/* Phosphor scanlines */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage:
              "repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(0,0,0,0.08) 3px, rgba(0,0,0,0.08) 4px)",
          }}
        />

        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
          <div className="flex flex-col items-center gap-2 text-center">
            <p
              className="text-eyebrow font-mono tracking-[0.5em] uppercase"
              style={{ color: `${accent}60` }}
            >
              STRATEGY CONSOLE — REGRESSION PLAN RESPONSE
            </p>
            <p
              className="text-display font-mono font-bold tracking-widest uppercase"
              style={{ color: accent, textShadow: `0 0 20px ${accent}60` }}
            >
              {STRATEGY_LINES[Math.floor(Date.now() / 3000) % STRATEGY_LINES.length]}
            </p>
            <p
              className="text-body font-mono tracking-wider uppercase"
              style={{ color: `${accent}80` }}
            >
              {label}
            </p>
            {elapsedSeconds !== undefined && elapsedSeconds > 0 && (
              <p className="text-label font-mono tabular-nums" style={{ color: `${accent}60` }}>
                T+{elapsedSeconds}s
              </p>
            )}
          </div>

          {/* Blinking cursor */}
          <div className="flex items-center gap-1 mt-2">
            <span className="text-label font-mono" style={{ color: accent }}>
              PROCESSING_
            </span>
            <span className="w-2 h-3 animate-pulse" style={{ background: accent }} />
          </div>

          {/* Pipeline nodes as DEFCON-style indicators */}
          <div className="flex items-center gap-4 mt-4">
            {[
              { role: "Oracle", active: true },
              { role: "Architect", active: false },
              { role: "Builder", active: false },
              { role: "Compiler", active: false },
            ].map(({ role, active: nodeActive }, i, arr) => (
              <React.Fragment key={role}>
                <div className="flex flex-col items-center gap-1.5">
                  <div
                    className="w-4 h-4 border flex items-center justify-center"
                    style={{
                      borderColor: nodeActive ? accent : `${accent}30`,
                      background: nodeActive ? `${accent}20` : "transparent",
                    }}
                  >
                    {nodeActive && (
                      <div className="w-1.5 h-1.5 animate-pulse" style={{ background: accent }} />
                    )}
                  </div>
                  <span
                    className="text-eyebrow font-mono tracking-wider uppercase"
                    style={{ color: nodeActive ? accent : `${accent}35` }}
                  >
                    {role}
                  </span>
                </div>
                {i < arr.length - 1 && (
                  <div className="w-6 h-px mb-5" style={{ background: `${accent}30` }} />
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none bg-black">
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,0,0,0.3)_0%,rgba(0,0,0,0.85)_100%)]" />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
        <span className="text-label font-mono animate-pulse" style={{ color: accent }}>
          â–ˆ
        </span>
        <p className="text-meta font-mono tracking-widest uppercase" style={{ color: accent }}>
          {label}
        </p>
      </div>
    </div>
  );
}
