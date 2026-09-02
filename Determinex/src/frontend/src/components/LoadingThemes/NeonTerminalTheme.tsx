"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";

const HACK_TEXT = [
  "TRACE ONLINE",
  "ACCESS GRANTED",
  "NEON NODE ONLINE",
  "CIPHER READY",
  "SIGNAL BURN",
  "LENS ROUTER",
  "FAULT TRACE",
  "OVERRIDE PATH",
  "PACKET PHASE",
  "CHECKSUM CLEAN",
  "ICE BREAKER",
  "ROOT ACCESS",
  "KERNEL PANIC",
  "NULL POINTER",
  "BUFFER OVERFLOW",
  "STACK SMASH",
  "HEAP SPRAY",
  "ROP CHAIN",
  "SHELLCODE",
  "PAYLOAD DEPLOY",
];

export function NeonTerminalTheme({
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

    // 3D wireframe city — buildings as boxes in perspective
    interface Building {
      x: number;
      z: number;
      width: number;
      depth: number;
      height: number;
      color: string;
    }
    const palette = [
      "#7c3aed",
      "#a855f7",
      "#06b6d4",
      "#8b5cf6",
      "var(--dtx-info)",
      "var(--dtx-alt)",
    ];
    const buildings: Building[] = Array.from({ length: 40 }, () => ({
      x: (Math.random() - 0.5) * 600,
      z: Math.random() * 400 + 50,
      width: 20 + Math.random() * 40,
      depth: 20 + Math.random() * 40,
      height: 40 + Math.random() * 160,
      color: palette[Math.floor(Math.random() * palette.length)],
    }));
    buildings.sort((a, b) => b.z - a.z); // painter's sort

    let camZ = 0;
    let tick = 0;
    let raf: number;

    const project = (x: number, y: number, z: number) => {
      const fov = 300;
      const dz = z - camZ;
      if (dz <= 0) return null;
      const sx = w / 2 + (x * fov) / dz;
      const sy = h * 0.55 + (y * fov) / dz;
      return { x: sx, y: sy, scale: fov / dz };
    };

    const draw = () => {
      ctx.fillStyle = "rgba(5,0,15,0.18)";
      ctx.fillRect(0, 0, w, h);

      camZ += 0.8; // fly forward

      // Stars / data particles
      for (let i = 0; i < 3; i++) {
        const px = Math.random() * w,
          py = Math.random() * h * 0.55;
        ctx.fillStyle = `rgba(167,139,250,${Math.random() * 0.3 + 0.05})`;
        ctx.fillRect(px, py, 1, 1);
      }

      // Ground grid
      ctx.strokeStyle = "rgba(124,58,237,0.12)";
      ctx.lineWidth = 0.5;
      for (let gz = 0; gz < 600; gz += 40) {
        const near = project(-300, 0, camZ + gz),
          far = project(-300, 0, camZ + gz + 40);
        if (!near || !far) continue;
        for (let gx = -300; gx <= 300; gx += 40) {
          const p1 = project(gx, 0, camZ + gz);
          const p2 = project(gx, 0, camZ + gz + 40);
          if (!p1 || !p2) continue;
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();
        }
        if (!near) continue;
        const l = project(-300, 0, camZ + gz),
          r = project(300, 0, camZ + gz);
        if (!l || !r) continue;
        ctx.beginPath();
        ctx.moveTo(l.x, l.y);
        ctx.lineTo(r.x, r.y);
        ctx.stroke();
      }

      // Buildings
      buildings.forEach((b) => {
        const effectiveZ = ((b.z - (camZ % 500) + 500) % 500) + 50;
        const bx = b.x;
        const corners = [
          project(bx - b.width / 2, 0, effectiveZ),
          project(bx + b.width / 2, 0, effectiveZ),
          project(bx + b.width / 2, 0, effectiveZ + b.depth),
          project(bx - b.width / 2, 0, effectiveZ + b.depth),
          project(bx - b.width / 2, -b.height, effectiveZ),
          project(bx + b.width / 2, -b.height, effectiveZ),
          project(bx + b.width / 2, -b.height, effectiveZ + b.depth),
          project(bx - b.width / 2, -b.height, effectiveZ + b.depth),
        ];
        if (corners.some((c) => c === null)) return;
        const cs = corners as { x: number; y: number; scale: number }[];

        const alpha = Math.min(0.8, cs[0].scale * 0.4);
        ctx.strokeStyle =
          b.color +
          Math.floor(alpha * 255)
            .toString(16)
            .padStart(2, "0");
        ctx.lineWidth = 0.8;

        // Draw wireframe edges
        const edges = [
          [0, 1],
          [1, 2],
          [2, 3],
          [3, 0],
          [4, 5],
          [5, 6],
          [6, 7],
          [7, 4],
          [0, 4],
          [1, 5],
          [2, 6],
          [3, 7],
        ];
        edges.forEach(([a, b2]) => {
          ctx.beginPath();
          ctx.moveTo(cs[a].x, cs[a].y);
          ctx.lineTo(cs[b2].x, cs[b2].y);
          ctx.stroke();
        });

        // Random lit window
        if (Math.random() < 0.002) {
          ctx.fillStyle = b.color + "40";
          ctx.fillRect(
            cs[4].x + 2,
            cs[4].y + 2,
            Math.abs(cs[5].x - cs[4].x) - 4,
            Math.abs(cs[0].y - cs[4].y) - 4
          );
        }
      });

      // Floating hack text
      if (Math.random() < 0.015) {
        const text = HACK_TEXT[Math.floor(Math.random() * HACK_TEXT.length)];
        const tx = Math.random() * (w - 80) + 20;
        const ty = Math.random() * (h - 30) + 15;
        ctx.fillStyle = `rgba(168,85,247,${Math.random() * 0.4 + 0.1})`;
        ctx.font = `${8 + Math.random() * 6}px monospace`;
        ctx.fillText(text, tx, ty);
      }

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

  const purple = "#a855f7";
  const cyan = "#06b6d4";

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#05000f" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(5,0,15,0.0)_0%,rgba(5,0,15,0.7)_100%)]" />

        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
          <div className="relative w-16 h-16">
            <div
              className="absolute inset-0 rounded-full border-2 animate-spin"
              style={{
                borderColor: `${purple}40`,
                borderTopColor: purple,
                animationDuration: "1.8s",
              }}
            />
            <div
              className="absolute inset-2 rounded-full border animate-spin"
              style={{
                borderColor: `${cyan}30`,
                borderRightColor: cyan,
                animationDuration: "2.8s",
                animationDirection: "reverse",
              }}
            />
            {elapsedSeconds !== undefined && elapsedSeconds > 0 && (
              <div className="absolute inset-0 flex items-center justify-center">
                <span
                  className="text-meta font-mono font-bold tabular-nums"
                  style={{ color: purple }}
                >
                  {elapsedSeconds}s
                </span>
              </div>
            )}
          </div>

          <div className="flex flex-col items-center gap-1">
            <p
              className="text-eyebrow font-mono tracking-[0.5em] uppercase"
              style={{ color: `${purple}60` }}
            >
              TRACE THE SYSTEM
            </p>
            <p
              className="text-title font-mono font-bold tracking-widest uppercase"
              style={{ color: purple, textShadow: `0 0 16px ${purple}` }}
            >
              {label}
            </p>
            <p className="text-meta font-mono" style={{ color: `${cyan}70` }}>
              NEON TERMINAL TRACE ACTIVE
            </p>
          </div>

          <div className="flex items-center gap-3">
            {[
              { role: "Oracle", active: true, color: purple },
              { role: "Architect", active: false, color: purple },
              { role: "Builder", active: false, color: cyan },
              { role: "Compiler", active: false, color: cyan },
            ].map(({ role, active: nodeActive, color }, i, arr) => (
              <React.Fragment key={role}>
                <div className="flex flex-col items-center gap-1">
                  <div
                    className="w-5 h-5 rounded-md border-2 flex items-center justify-center"
                    style={{
                      borderColor: nodeActive ? color : `${color}25`,
                      background: nodeActive ? `${color}15` : "transparent",
                      boxShadow: nodeActive ? `0 0 10px ${color}70` : "none",
                    }}
                  >
                    <div
                      className="w-1.5 h-1.5"
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
                  <div className="w-4 h-px mb-4" style={{ background: `${purple}25` }} />
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
      style={{ background: "#05000f" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(5,0,15,0.2)_0%,rgba(5,0,15,0.85)_100%)]" />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
        <div
          className="w-6 h-6 border-2 rounded-full animate-spin"
          style={{ borderColor: `${purple}40`, borderTopColor: purple }}
        />
        <p className="text-meta font-mono tracking-widest uppercase" style={{ color: purple }}>
          {label}
        </p>
      </div>
    </div>
  );
}
