"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";

export function AegisAssistantTheme({
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
    const BLUE = "#4fc3f7";
    const GOLD = "#ffd54f";

    // Hex tiles on canvas for background
    const HEX = 22;
    const hexes: { cx: number; cy: number; phase: number; lit: boolean }[] = [];
    const hh = HEX * Math.sqrt(3);
    const cols = Math.ceil(w / (HEX * 1.5)) + 2,
      rows = Math.ceil(h / hh) + 2;
    for (let c = -1; c < cols; c++) {
      for (let r = -1; r < rows; r++) {
        hexes.push({
          cx: c * HEX * 1.5,
          cy: r * hh + (c % 2 === 0 ? 0 : hh / 2),
          phase: Math.random() * Math.PI * 2,
          lit: Math.random() < 0.05,
        });
      }
    }

    // Arcs of data streaming
    interface DataArc {
      angle: number;
      radius: number;
      speed: number;
      color: string;
    }
    const arcs: DataArc[] = Array.from({ length: 8 }, (_, i) => ({
      angle: (i / 8) * Math.PI * 2,
      radius: 60 + i * 20,
      speed: (0.01 + i * 0.003) * (i % 2 === 0 ? 1 : -1),
      color: i % 3 === 0 ? GOLD : BLUE,
    }));

    let raf: number;
    const draw = () => {
      ctx.fillStyle = "rgba(0,10,30,0.14)";
      ctx.fillRect(0, 0, w, h);

      // Hex grid
      hexes.forEach((hex) => {
        const pulse = Math.sin(tick * 0.025 + hex.phase) * 0.5 + 0.5;
        ctx.beginPath();
        for (let s = 0; s < 6; s++) {
          const ang = (Math.PI / 180) * (60 * s - 30);
          const px = hex.cx + HEX * Math.cos(ang),
            py = hex.cy + HEX * Math.sin(ang);
          s === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
        }
        ctx.closePath();
        const alpha = hex.lit ? 0.08 + pulse * 0.12 : 0.03 + pulse * 0.02;
        ctx.strokeStyle = `rgba(79,195,247,${alpha})`;
        ctx.lineWidth = 0.6;
        ctx.stroke();
        if (hex.lit) {
          ctx.fillStyle = `rgba(79,195,247,${0.04 + pulse * 0.06})`;
          ctx.fill();
        }
      });

      // Rotating arc rings
      const cx = w / 2,
        cy = h / 2;
      arcs.forEach((arc) => {
        arc.angle += arc.speed;
        const startAngle = arc.angle;
        const sweep = Math.PI * (0.6 + Math.sin(tick * 0.02) * 0.2);
        ctx.beginPath();
        ctx.arc(cx, cy, arc.radius, startAngle, startAngle + sweep);
        ctx.strokeStyle = arc.color + "90";
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Dot at arc tip
        const tipX = cx + arc.radius * Math.cos(startAngle + sweep);
        const tipY = cy + arc.radius * Math.sin(startAngle + sweep);
        ctx.beginPath();
        ctx.arc(tipX, tipY, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = arc.color;
        ctx.fill();
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

  const blue = "#4fc3f7";
  const gold = "#ffd54f";

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#000a1e" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,10,30,0.05)_0%,rgba(0,10,30,0.65)_100%)]" />

        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
          {/* Reactor ring */}
          <div className="relative w-20 h-20">
            <div
              className="absolute inset-0 rounded-full border-2 animate-spin"
              style={{ borderColor: `${blue}30`, borderTopColor: blue, animationDuration: "2s" }}
            />
            <div
              className="absolute inset-2 rounded-full border animate-spin"
              style={{
                borderColor: `${gold}20`,
                borderRightColor: gold,
                animationDuration: "3s",
                animationDirection: "reverse",
              }}
            />
            <div
              className="absolute inset-4 rounded-full border animate-spin"
              style={{ borderColor: `${blue}20`, borderBottomColor: blue, animationDuration: "4s" }}
            />
            <div className="absolute inset-0 flex items-center justify-center">
              <div
                className="w-6 h-6 rounded-full"
                style={{
                  background: `radial-gradient(circle,${blue}80 0%,${blue}20 60%,transparent 100%)`,
                }}
              />
            </div>
          </div>

          <div className="flex flex-col items-center gap-1">
            <p
              className="text-eyebrow font-mono tracking-[0.6em] uppercase"
              style={{ color: `${blue}60` }}
            >
              AEGIS ASSISTANT ONLINE
            </p>
            <p
              className="text-title font-mono font-bold tracking-widest uppercase"
              style={{ color: blue, textShadow: `0 0 16px ${blue}80` }}
            >
              {label}
            </p>
            <p className="text-meta font-mono" style={{ color: `${gold}70` }}>
              {elapsedSeconds !== undefined && elapsedSeconds > 0
                ? `PROCESSING — ${elapsedSeconds}s ELAPSED`
                : "AEGIS ASSISTANT NETWORK ACTIVE"}
            </p>
          </div>

          <div className="flex items-center gap-3 mt-1">
            {[
              { role: "Oracle", active: true, color: blue },
              { role: "Architect", active: false, color: blue },
              { role: "Builder", active: false, color: blue },
              { role: "Compiler", active: false, color: gold },
            ].map(({ role, active: nodeActive, color }, i, arr) => (
              <React.Fragment key={role}>
                <div className="flex flex-col items-center gap-1">
                  <div
                    className="w-5 h-5 rounded-full border-2 flex items-center justify-center"
                    style={{
                      borderColor: nodeActive ? color : `${color}25`,
                      background: nodeActive ? `${color}15` : "transparent",
                      boxShadow: nodeActive ? `0 0 10px ${color}70` : "none",
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
                  <div className="w-4 h-px mb-4" style={{ background: `${blue}30` }} />
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
      style={{ background: "#000a1e" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,10,30,0.1)_0%,rgba(0,10,30,0.85)_100%)]" />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
        <div
          className="w-6 h-6 border-2 rounded-full animate-spin"
          style={{ borderColor: `${blue}40`, borderTopColor: blue }}
        />
        <p className="text-meta font-mono tracking-widest uppercase" style={{ color: blue }}>
          {label}
        </p>
      </div>
    </div>
  );
}
