"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";

const PATCH_REFLECTIONS = [
  "A patch fails once. Which proof do you ask for next?",
  "The test passes but the diff is broad. What should Determinex narrow?",
  "A compiler error repeats. Which file owns the broken assumption?",
  "The run is green. Which regression should become training data?",
  "A benchmark family dominates failures. Which universal patch do you try first?",
  "The code is local. Which evidence proves nothing left the machine?",
  "Describe the smallest safe change that would satisfy this test.",
  "A bright trace is useful only when it leads back to proof.",
  "Every accepted fix leaves a record the next run can learn from.",
];

export function RainCityTheme({
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

    // Neon rain drops — thicker, colored vertically
    const DROPS = Array.from({ length: 60 }, () => ({
      x: Math.random() * 2000 - 500,
      y: Math.random() * h * 2 - h,
      speed: 4 + Math.random() * 8,
      len: 30 + Math.random() * 80,
      color:
        Math.random() < 0.6
          ? "var(--dtx-info)"
          : Math.random() < 0.5
            ? "var(--dtx-alt)"
            : "#8b5cf6",
      alpha: 0.2 + Math.random() * 0.4,
      width: 0.5 + Math.random() * 1.5,
    }));

    // City skyline silhouette
    const BUILDINGS: { x: number; w: number; h: number }[] = [];
    let bx = -50;
    while (bx < 2000) {
      const bw = 30 + Math.random() * 80;
      const bh = h * 0.2 + Math.random() * h * 0.35;
      BUILDINGS.push({ x: bx, w: bw, h: bh });
      bx += bw + 2 + Math.random() * 10;
    }

    let tick = 0;
    const ANGLE = (-12 * Math.PI) / 180; // slight diagonal like rain

    let raf: number;
    const draw = () => {
      ctx.fillStyle = "rgba(2,4,18,0.18)";
      ctx.fillRect(0, 0, w, h);

      // City skyline
      ctx.fillStyle = "rgba(5,10,30,0.95)";
      BUILDINGS.forEach((b) => {
        ctx.fillRect(b.x, h - b.h, b.w, b.h);
      });

      // Neon window lights in buildings
      if (tick % 90 === 0) {
        BUILDINGS.forEach((b) => {
          if (Math.random() < 0.15) {
            const wc = Math.random() < 0.5 ? "var(--dtx-info)" : "var(--dtx-alt)";
            ctx.fillStyle = wc + "40";
            const wx = b.x + Math.random() * (b.w - 4) + 2;
            const wy = h - b.h + Math.random() * (b.h - 4) + 2;
            ctx.fillRect(wx, wy, 3 + Math.random() * 6, 2 + Math.random() * 4);
          }
        });
      }

      // Diagonal neon rain
      ctx.save();
      ctx.transform(Math.cos(ANGLE), Math.sin(ANGLE), -Math.sin(ANGLE), Math.cos(ANGLE), 0, 0);

      DROPS.forEach((d) => {
        d.y += d.speed;
        if (d.y - d.len > h * 1.5) d.y = -d.len;

        const grad = ctx.createLinearGradient(d.x, d.y - d.len, d.x, d.y);
        grad.addColorStop(0, d.color + "00");
        grad.addColorStop(
          0.8,
          d.color +
            Math.floor(d.alpha * 255)
              .toString(16)
              .padStart(2, "0")
        );
        grad.addColorStop(
          1,
          "#fff" +
            Math.floor(d.alpha * 200)
              .toString(16)
              .padStart(2, "0")
        );
        ctx.beginPath();
        ctx.moveTo(d.x, d.y - d.len);
        ctx.lineTo(d.x, d.y);
        ctx.strokeStyle = grad;
        ctx.lineWidth = d.width;
        ctx.stroke();
      });
      ctx.restore();

      // Ground neon reflections
      const horizY = h * 0.65;
      const refGrad = ctx.createLinearGradient(0, horizY, 0, h);
      refGrad.addColorStop(0, "rgba(59,130,246,0.0)");
      refGrad.addColorStop(0.5, "rgba(59,130,246,0.04)");
      refGrad.addColorStop(1, "rgba(59,130,246,0.0)");
      ctx.fillStyle = refGrad;
      ctx.fillRect(0, horizY, w, h - horizY);

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

  const blue = "var(--dtx-info)";
  const pink = "var(--dtx-alt)";
  const question = PATCH_REFLECTIONS[Math.floor(Date.now() / 5000) % PATCH_REFLECTIONS.length];

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#02040e" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(2,4,14,0.0)_0%,rgba(2,4,14,0.7)_100%)]" />

        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
          {/* VK machine glow panel */}
          <div
            className="px-6 py-4 border rounded-sm max-w-sm text-center"
            style={{
              borderColor: `${blue}40`,
              background: "rgba(2,4,14,0.7)",
              boxShadow: `0 0 30px ${blue}20, inset 0 0 30px rgba(0,0,0,0.5)`,
            }}
          >
            <p
              className="text-eyebrow font-mono tracking-[0.5em] uppercase mb-2"
              style={{ color: `${blue}60` }}
            >
              RAIN CITY PATCH ANALYZER
            </p>
            <p
              className="text-label font-mono italic text-center leading-relaxed"
              style={{ color: "rgba(200,220,255,0.7)" }}
            >
              &quot;{question}&quot;
            </p>
          </div>

          <div className="relative w-14 h-14">
            <div
              className="absolute inset-0 rounded-full border-2 animate-spin"
              style={{ borderColor: `${blue}30`, borderTopColor: blue, animationDuration: "2s" }}
            />
            <div
              className="absolute inset-2 rounded-full border animate-spin"
              style={{
                borderColor: `${pink}20`,
                borderLeftColor: pink,
                animationDuration: "3s",
                animationDirection: "reverse",
              }}
            />
            {elapsedSeconds !== undefined && elapsedSeconds > 0 && (
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-meta font-mono tabular-nums" style={{ color: blue }}>
                  {elapsedSeconds}s
                </span>
              </div>
            )}
          </div>

          <div className="flex flex-col items-center gap-1">
            <p
              className="text-body font-mono tracking-widest uppercase font-bold"
              style={{ color: blue, textShadow: `0 0 14px ${blue}` }}
            >
              {label}
            </p>
            <p className="text-meta font-mono" style={{ color: `${pink}60` }}>
              LOS ANGELES, 2019 · TYRRELL CORPORATION
            </p>
          </div>

          <div className="flex items-center gap-3 mt-1">
            {[
              { role: "Oracle", active: true, color: blue },
              { role: "Architect", active: false, color: blue },
              { role: "Builder", active: false, color: pink },
              { role: "Compiler", active: false, color: pink },
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
                  <div className="w-4 h-px mb-4" style={{ background: `${blue}20` }} />
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
      style={{ background: "#02040e" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(2,4,14,0.2)_0%,rgba(2,4,14,0.85)_100%)]" />
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
