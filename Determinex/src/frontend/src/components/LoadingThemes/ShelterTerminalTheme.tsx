"use client";
import React, { useRef, useEffect, useState } from "react";
import type { LoadingThemeProps } from "./types";

const SHELTER_BOOT = [
  "LOCAL MODE ONLINE",
  "SHELTER INDEX READY",
  "PROOF CACHE SEALED",
  "SOURCE MATERIAL LOCAL",
  "NO TELEMETRY ACTIVE",
  "AUTHORITY REQUIRED",
  "FIXTURE REQUIRED",
  "VERIFIER REQUIRED",
  "LEDGER CLEAN",
  "MUTATION LOCKED",
];

export function ShelterTerminalTheme({
  active,
  label = "Oracle is thinking...",
  fullPanel = false,
  elapsedSeconds,
}: LoadingThemeProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [visibleLines, setVisibleLines] = useState(0);

  useEffect(() => {
    if (!active) return;
    setVisibleLines(0);
    const interval = setInterval(() => {
      setVisibleLines((n) => (n >= SHELTER_BOOT.length ? n : n + 1));
    }, 380);
    return () => clearInterval(interval);
  }, [active]);

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

    let raf: number;
    let t = 0;
    const draw = () => {
      ctx.fillStyle = "rgba(0,12,4,0.20)";
      ctx.fillRect(0, 0, w, h);
      // CRT scanlines
      ctx.fillStyle = "rgba(0,255,80,0.04)";
      for (let y = 0; y < h; y += 3) ctx.fillRect(0, y, w, 1);
      // Slow phosphor wave
      ctx.strokeStyle = "rgba(0,255,80,0.18)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = 0; x < w; x++) {
        const y = h / 2 + Math.sin((x + t) * 0.018) * 18 + Math.sin((x + t) * 0.05) * 6;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      // Radiation needle gauge
      const cx = w - 70,
        cy = 60;
      ctx.strokeStyle = "rgba(0,255,80,0.55)";
      ctx.beginPath();
      ctx.arc(cx, cy, 28, Math.PI, Math.PI * 2);
      ctx.stroke();
      const ang = Math.PI + (Math.sin(t * 0.04) * 0.5 + 0.5) * Math.PI;
      ctx.strokeStyle = "#7fff9c";
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(ang) * 26, cy + Math.sin(ang) * 26);
      ctx.stroke();
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
  const phosphor = "#00ff66";
  const phosphorDim = "rgba(0,255,80,0.45)";

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#000c04" }}>
        <canvas ref={canvasRef} className="absolute inset-0 opacity-90" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,12,4,0)_0%,rgba(0,12,4,0.85)_100%)]" />
        <div className="absolute inset-0 flex">
          <div className="flex-1 flex flex-col justify-center px-8 gap-1">
            <p
              className="text-eyebrow font-mono tracking-widest uppercase mb-3"
              style={{ color: phosphorDim }}
            >
              ◄ SHELTER TERMINAL V3.7 ►
            </p>
            {SHELTER_BOOT.slice(0, visibleLines).map((line, i) => (
              <p
                key={i}
                className="text-meta font-mono"
                style={{
                  color: i === visibleLines - 1 ? phosphor : phosphorDim,
                  textShadow: `0 0 6px ${phosphor}55`,
                }}
              >
                {">"} {line}
              </p>
            ))}
            <p className="text-meta font-mono mt-2" style={{ color: phosphorDim }}>
              {">"} <span className="animate-pulse">_</span>
            </p>
          </div>
          <div className="flex flex-col items-center justify-center pr-10 gap-4">
            <p
              className="text-title font-mono tracking-widest uppercase font-bold"
              style={{ color: phosphor, textShadow: `0 0 14px ${phosphor}80` }}
            >
              {label}
            </p>
            {elapsedSeconds !== undefined && elapsedSeconds > 0 && (
              <p className="text-label font-mono tabular-nums" style={{ color: phosphorDim }}>
                LOCAL UPTIME: {elapsedSeconds}s
              </p>
            )}
            <div className="flex items-center gap-3 mt-2">
              {[
                { role: "Oracle", active: true },
                { role: "Architect", active: false },
                { role: "Builder", active: false },
                { role: "Compiler", active: false },
              ].map(({ role, active: a }, i, arr) => (
                <React.Fragment key={role}>
                  <div className="flex flex-col items-center gap-1">
                    <div
                      className="w-5 h-5 border flex items-center justify-center"
                      style={{
                        borderColor: a ? phosphor : phosphorDim,
                        background: a ? `${phosphor}25` : "transparent",
                        boxShadow: a ? `0 0 10px ${phosphor}60` : "none",
                      }}
                    >
                      <div className="w-1 h-1" style={{ background: a ? phosphor : phosphorDim }} />
                    </div>
                    <span
                      className="text-eyebrow font-mono uppercase tracking-wider"
                      style={{ color: a ? phosphor : phosphorDim }}
                    >
                      {role}
                    </span>
                  </div>
                  {i < arr.length - 1 && (
                    <span className="text-meta mb-4" style={{ color: phosphorDim }}>
                      {"->"}
                    </span>
                  )}
                </React.Fragment>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#000c04" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-80" />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
        <div
          className="w-5 h-5 border-2 rounded-full animate-spin"
          style={{ borderColor: phosphor, borderTopColor: "transparent" }}
        />
        <p className="text-meta font-mono tracking-widest uppercase" style={{ color: phosphor }}>
          {label}
        </p>
      </div>
    </div>
  );
}
