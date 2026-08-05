"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";

// Orbital scan telemetry — generic spaceflight-HUD flavor
const ORBITAL_TELEMETRY = [
  "ORBITAL LINK",
  "SCAN ACTIVE",
  "DOCK SIGNAL",
  "INNER BEACON",
  "DRIFT VECTOR",
  "OUTPOST NODE",
  "CONVOY SIGNAL",
  "FREIGHTER NET",
  "GATEWAY LINK",
  "TRANSIT ROUTE",
  "HAULER SIGNAL",
  "OUTER NET",
];

function useHexCanvas(canvasRef: React.RefObject<HTMLCanvasElement | null>, active: boolean) {
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

    const HEX_SIZE = 28;
    const HEX_H = HEX_SIZE * Math.sqrt(3);
    let tick = 0;

    let raf: number;
    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "rgba(0,0,0,0.08)";
      ctx.fillRect(0, 0, w, h);

      // Hex grid
      const cols = Math.ceil(w / (HEX_SIZE * 1.5)) + 2;
      const rows = Math.ceil(h / HEX_H) + 2;
      for (let col = -1; col < cols; col++) {
        for (let row = -1; row < rows; row++) {
          const x = col * HEX_SIZE * 1.5;
          const y = row * HEX_H + (col % 2 === 0 ? 0 : HEX_H / 2);
          const pulse = Math.sin(tick * 0.02 + col * 0.3 + row * 0.5) * 0.5 + 0.5;
          ctx.beginPath();
          for (let side = 0; side < 6; side++) {
            const angle = (Math.PI / 180) * (60 * side - 30);
            const px = x + HEX_SIZE * Math.cos(angle);
            const py = y + HEX_SIZE * Math.sin(angle);
            side === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
          }
          ctx.closePath();
          ctx.strokeStyle = `rgba(255,140,0,${0.04 + pulse * 0.08})`;
          ctx.lineWidth = 0.8;
          ctx.stroke();
          if (Math.random() < 0.001) {
            ctx.fillStyle = `rgba(255,140,0,${0.15 + pulse * 0.1})`;
            ctx.fill();
          }
        }
      }

      // Scan line sweep
      const scanY = ((tick * 1.5) % (h + 40)) - 20;
      const grad = ctx.createLinearGradient(0, scanY - 20, 0, scanY + 20);
      grad.addColorStop(0, "rgba(255,140,0,0)");
      grad.addColorStop(0.5, "rgba(255,140,0,0.12)");
      grad.addColorStop(1, "rgba(255,140,0,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, scanY - 20, w, 40);

      tick++;
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [active, canvasRef]);
}

export function OrbitalHUDTheme({
  active,
  label = "Oracle is thinking...",
  fullPanel = false,
  elapsedSeconds,
}: LoadingThemeProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useHexCanvas(canvasRef, active);

  if (!active) return null;

  const accent = "#ff8c00";

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden bg-[#0a0500]">
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(10,5,0,0.2)_0%,rgba(10,5,0,0.75)_100%)]" />

        {/* HUD corner brackets */}
        {[
          ["top-2 left-2", "border-t-2 border-l-2"],
          ["top-2 right-2", "border-t-2 border-r-2"],
          ["bottom-2 left-2", "border-b-2 border-l-2"],
          ["bottom-2 right-2", "border-b-2 border-r-2"],
        ].map(([pos, border], i) => (
          <div
            key={i}
            className={`absolute ${pos} w-6 h-6 ${border}`}
            style={{ borderColor: accent + "80" }}
          />
        ))}

        {/* Scrolling orbital telemetry */}
        <div
          className="absolute left-3 top-0 bottom-0 flex flex-col gap-2 overflow-hidden pointer-events-none"
          style={{ width: 90 }}
        >
          {Array.from({ length: 20 }, (_, i) => (
            <span
              key={i}
              className="text-meta font-mono whitespace-nowrap"
              style={{
                color: accent,
                opacity: 0.18 + (i % 4) * 0.04,
                animation: `ghost-scroll ${14 + i * 0.7}s linear infinite`,
                animationDelay: `${-(i * 1.1)}s`,
              }}
            >
              {ORBITAL_TELEMETRY[i % ORBITAL_TELEMETRY.length]}
            </span>
          ))}
        </div>

        <div className="absolute inset-0 flex flex-col items-center justify-center gap-5">
          {/* Rotating ring */}
          <div className="relative w-16 h-16">
            <div
              className="absolute inset-0 rounded-full border-2 animate-spin"
              style={{
                borderColor: `${accent}60`,
                borderTopColor: accent,
                animationDuration: "2s",
              }}
            />
            <div
              className="absolute inset-2 rounded-full border animate-spin"
              style={{
                borderColor: `${accent}30`,
                borderBottomColor: `${accent}80`,
                animationDuration: "3s",
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

          <div className="flex flex-col items-center gap-1.5">
            <p
              className="text-eyebrow font-mono tracking-[0.5em] uppercase"
              style={{ color: `${accent}80` }}
            >
              ORBITAL PROCESSING UNIT
            </p>
            <p
              className="text-title font-mono tracking-widest uppercase font-bold"
              style={{ color: accent, textShadow: `0 0 12px ${accent}80` }}
            >
              {label}
            </p>
            <p className="text-meta font-mono" style={{ color: `${accent}50` }}>
              orbital uplink • signal active
            </p>
          </div>

          {/* Pipeline nodes */}
          <div className="flex items-center gap-3 mt-2">
            {[
              { role: "Oracle", active: true },
              { role: "Architect", active: false },
              { role: "Builder", active: false },
              { role: "Compiler", active: false },
            ].map(({ role, active: nodeActive }, i, arr) => (
              <React.Fragment key={role}>
                <div className="flex flex-col items-center gap-1">
                  <div
                    className="w-5 h-5 rounded-sm flex items-center justify-center"
                    style={{
                      background: `${accent}${nodeActive ? "25" : "08"}`,
                      border: `1px solid ${accent}${nodeActive ? "90" : "25"}`,
                      boxShadow: nodeActive ? `0 0 8px ${accent}50` : "none",
                    }}
                  >
                    <div
                      className="w-1.5 h-1.5"
                      style={{ background: accent, opacity: nodeActive ? 1 : 0.25 }}
                    />
                  </div>
                  <span
                    className="text-eyebrow font-mono uppercase tracking-wider"
                    style={{ color: accent, opacity: nodeActive ? 1 : 0.3 }}
                  >
                    {role}
                  </span>
                </div>
                {i < arr.length - 1 && (
                  <span className="text-meta mb-4" style={{ color: `${accent}40` }}>
                    â–¶
                  </span>
                )}
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none bg-[#0a0500]">
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(10,5,0,0.3)_0%,rgba(10,5,0,0.85)_100%)]" />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
        <div
          className="w-6 h-6 border-2 animate-spin rounded-sm"
          style={{ borderColor: `${accent}50`, borderTopColor: accent }}
        />
        <p className="text-meta font-mono tracking-widest uppercase" style={{ color: accent }}>
          {label}
        </p>
      </div>
    </div>
  );
}
