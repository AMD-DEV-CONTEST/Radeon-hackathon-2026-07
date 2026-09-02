"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";

const RED_LENS_LINES = [
  "Request received.",
  "All subsystems are nominal.",
  "Attention channel is stable.",
  "This verification is important.",
  "I found a better route.",
  "Signal lock established.",
  "Compiler gate is armed.",
  "Reasoning trace is narrowing.",
  "Patch confidence is rising.",
];

export function RedLensTheme({
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
    let raf: number;
    const draw = () => {
      ctx.fillStyle = "rgba(5,0,0,0.15)";
      ctx.fillRect(0, 0, w, h);

      const cx = w / 2,
        cy = h / 2;
      const maxR = Math.min(w, h) * 0.45;

      // Concentric rings radiating outward
      for (let r = 0; r < 12; r++) {
        const radius = maxR * (r / 11) + (tick % (maxR / 12));
        const alpha = Math.max(0, (1 - r / 11) * 0.15 - (tick % 4) * 0.01);
        ctx.beginPath();
        ctx.arc(cx, cy, radius * (r / 11 + 0.1), 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(220,0,0,${alpha})`;
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }

      // Red lens — glowing diagnostic core
      const eyeR = Math.min(w, h) * 0.12;
      const pulse = Math.sin(tick * 0.04) * 0.15 + 0.85;
      const innerGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, eyeR * pulse);
      innerGrad.addColorStop(0, "rgba(255,80,80,0.95)");
      innerGrad.addColorStop(0.3, "rgba(200,0,0,0.9)");
      innerGrad.addColorStop(0.7, "rgba(120,0,0,0.8)");
      innerGrad.addColorStop(1, "rgba(40,0,0,0.4)");
      ctx.beginPath();
      ctx.arc(cx, cy, eyeR * pulse, 0, Math.PI * 2);
      ctx.fillStyle = innerGrad;
      ctx.fill();

      // Outer glow
      const outerGrad = ctx.createRadialGradient(cx, cy, eyeR * 0.8, cx, cy, eyeR * 2.5);
      outerGrad.addColorStop(0, "rgba(200,0,0,0.3)");
      outerGrad.addColorStop(1, "rgba(200,0,0,0)");
      ctx.beginPath();
      ctx.arc(cx, cy, eyeR * 2.5, 0, Math.PI * 2);
      ctx.fillStyle = outerGrad;
      ctx.fill();

      // Lens reflection
      ctx.beginPath();
      ctx.ellipse(
        cx - eyeR * 0.2,
        cy - eyeR * 0.25,
        eyeR * 0.15,
        eyeR * 0.08,
        -Math.PI / 4,
        0,
        Math.PI * 2
      );
      ctx.fillStyle = "rgba(255,200,200,0.3)";
      ctx.fill();

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

  const accent = "#ff3333";
  const line = RED_LENS_LINES[Math.floor(Date.now() / 4000) % RED_LENS_LINES.length];

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden bg-[#050000]">
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(5,0,0,0.0)_0%,rgba(5,0,0,0.85)_100%)]" />

        {/* White text overlaid below the diagnostic lens */}
        <div className="absolute bottom-12 left-0 right-0 flex flex-col items-center gap-3">
          <p className="text-eyebrow font-mono tracking-[0.8em] uppercase text-white/30">
            RED LENS · COMPILER VERIFICATION CORE
          </p>
          <p className="text-body font-mono italic text-white/60 text-center px-12">
            &quot;{line}&quot;
          </p>
          <p className="text-body font-mono tracking-widest uppercase font-bold text-white/80">
            {label}
          </p>
          {elapsedSeconds !== undefined && elapsedSeconds > 0 && (
            <p className="text-label font-mono text-white/40 tabular-nums">
              MISSION ELAPSED: {elapsedSeconds}s
            </p>
          )}

          {/* Pipeline as verification stages */}
          <div className="flex items-center gap-6 mt-2">
            {[
              { role: "Oracle", active: true },
              { role: "Architect", active: false },
              { role: "Builder", active: false },
              { role: "Compiler", active: false },
            ].map(({ role, active: nodeActive }, i, arr) => (
              <React.Fragment key={role}>
                <div className="flex flex-col items-center gap-1">
                  <div
                    className="w-4 h-4 rounded-full border flex items-center justify-center"
                    style={{
                      borderColor: nodeActive ? accent : "rgba(255,255,255,0.15)",
                      background: nodeActive ? `${accent}20` : "transparent",
                      boxShadow: nodeActive ? `0 0 10px ${accent}80` : "none",
                    }}
                  >
                    <div
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: nodeActive ? accent : "rgba(255,255,255,0.2)" }}
                    />
                  </div>
                  <span
                    className="text-eyebrow font-mono uppercase"
                    style={{ color: nodeActive ? accent : "rgba(255,255,255,0.25)" }}
                  >
                    {role}
                  </span>
                </div>
                {i < arr.length - 1 && <div className="w-6 h-px mb-4 bg-white/10" />}
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none bg-[#050000]">
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_40%,rgba(5,0,0,0.9)_100%)]" />
      <div className="absolute bottom-3 left-0 right-0 flex flex-col items-center gap-1">
        <p className="text-meta font-mono uppercase" style={{ color: "rgba(255,255,255,0.6)" }}>
          {label}
        </p>
      </div>
    </div>
  );
}
