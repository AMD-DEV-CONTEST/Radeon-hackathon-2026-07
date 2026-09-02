"use client";
import React, { useRef, useEffect, useState } from "react";
import type { LoadingThemeProps } from "./types";

const ARCHIVE_BOOT = [
  "ARCHIVE CORE TERMINAL ONLINE",
  "DETERMINEX",
  "DETERMINEX EVIDENCE VESSEL",
  "MANIFEST CODE: 180924609",
  "ANALYZING TRANSMISSION SOURCE...",
  "ORACLE QUERY: INITIATED",
  "APPEND-ONLY LEDGER — ACTIVE",
  "TRAINING ELIGIBILITY: FALSE",
  "PRIORITY ONE OVERRIDE",
  "VERIFIER LINK: ESTABLISHED",
  "SHELTER MONITORING: NOMINAL",
  "MUTATION GATE: ARMED",
];

export function ArchiveCoreTheme({
  active,
  label = "Oracle is thinking...",
  fullPanel = false,
  elapsedSeconds,
}: LoadingThemeProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [visibleLines, setVisibleLines] = useState(0);

  // Typewriter-style line reveal
  useEffect(() => {
    if (!active) {
      setVisibleLines(0);
      return;
    }
    let idx = 0;
    const iv = setInterval(() => {
      idx++;
      setVisibleLines(idx);
      if (idx >= ARCHIVE_BOOT.length) clearInterval(iv);
    }, 280);
    return () => clearInterval(iv);
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

    const AMBER = "#d4a017";
    let tick = 0;
    let raf: number;
    const draw = () => {
      ctx.fillStyle = "rgba(0,0,0,0.2)";
      ctx.fillRect(0, 0, w, h);

      // Dot-matrix pattern — rows of amber dots
      const COLS = Math.floor(w / 8),
        ROWS = Math.floor(h / 8);
      for (let r = 0; r < ROWS; r++) {
        for (let c = 0; c < COLS; c++) {
          const flicker = Math.random() > 0.998;
          const base = flicker ? 0.25 : 0.04;
          const scan = Math.abs(Math.sin(tick * 0.015 + r * 0.1)) * 0.04;
          ctx.beginPath();
          ctx.arc(c * 8 + 4, r * 8 + 4, 0.8, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(212,160,23,${base + scan})`;
          ctx.fill();
        }
      }

      // Horizontal scan sweep
      const scanY = (tick * 0.8) % (h + 10);
      ctx.fillStyle = `rgba(212,160,23,0.06)`;
      ctx.fillRect(0, scanY, w, 6);

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

  const amber = "#d4a017";
  const amberDim = "#7a5a0a";

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden bg-black">
        <canvas ref={canvasRef} className="absolute inset-0 opacity-60" />
        {/* Phosphor amber scanlines */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage:
              "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.12) 2px, rgba(0,0,0,0.12) 3px)",
          }}
        />

        <div className="absolute inset-0 flex">
          {/* Left: ARCHIVE CORE terminal log */}
          <div className="flex-1 flex flex-col justify-center px-8 gap-1">
            <p
              className="text-eyebrow font-mono tracking-widest uppercase mb-3"
              style={{ color: amberDim }}
            >
              ◄ ARCHIVE CORE 6000 TERMINAL ►
            </p>
            {ARCHIVE_BOOT.slice(0, visibleLines).map((line, i) => (
              <p
                key={i}
                className="text-meta font-mono"
                style={{ color: i === visibleLines - 1 ? amber : amberDim }}
              >
                {i === visibleLines - 1 ? "â–º " : "  "}
                {line}
                {i === visibleLines - 1 && <span className="animate-pulse">â–ˆ</span>}
              </p>
            ))}
          </div>

          {/* Right: status + pipeline */}
          <div
            className="w-52 border-l flex flex-col items-center justify-center gap-4 px-4"
            style={{ borderColor: `${amber}20` }}
          >
            <div className="flex flex-col items-center gap-2">
              <div
                className="w-10 h-10 border-2 rounded-full flex items-center justify-center animate-pulse"
                style={{ borderColor: amber, boxShadow: `0 0 12px ${amber}50` }}
              >
                <span className="text-meta font-mono font-bold" style={{ color: amber }}>
                  MU
                </span>
              </div>
              <p
                className="text-meta font-mono font-bold tracking-widest uppercase text-center"
                style={{ color: amber }}
              >
                {label}
              </p>
              {elapsedSeconds !== undefined && elapsedSeconds > 0 && (
                <p className="text-meta font-mono tabular-nums" style={{ color: amberDim }}>
                  ELAPSED: {elapsedSeconds}s
                </p>
              )}
            </div>

            <div className="flex flex-col gap-2 w-full">
              {[
                { role: "Oracle", active: true },
                { role: "Architect", active: false },
                { role: "Builder", active: false },
                { role: "Compiler", active: false },
              ].map(({ role, active: nodeActive }) => (
                <div key={role} className="flex items-center gap-2">
                  <div
                    className="w-2 h-2 rounded-sm"
                    style={{
                      background: nodeActive ? amber : amberDim,
                      boxShadow: nodeActive ? `0 0 6px ${amber}80` : "none",
                    }}
                  />
                  <span
                    className="text-eyebrow font-mono uppercase"
                    style={{ color: nodeActive ? amber : amberDim }}
                  >
                    {role}
                  </span>
                  <span className="text-meta font-mono ml-auto" style={{ color: amberDim }}>
                    {nodeActive ? "ACTIVE" : "STBY"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none bg-black">
      <canvas ref={canvasRef} className="absolute inset-0 opacity-60" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,0,0,0.3)_0%,rgba(0,0,0,0.85)_100%)]" />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
        <span className="text-label font-mono animate-pulse" style={{ color: amber }}>
          â–ˆ
        </span>
        <p className="text-eyebrow font-mono tracking-widest uppercase" style={{ color: amberDim }}>
          {label}
        </p>
      </div>
    </div>
  );
}
