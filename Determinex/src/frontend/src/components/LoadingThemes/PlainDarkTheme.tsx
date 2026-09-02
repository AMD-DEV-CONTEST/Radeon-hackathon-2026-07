"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

/**
 * PlainDarkTheme — the no-vibe option.
 *
 * Standard dark loading screen with restrained animation: a soft radial
 * glow, a slow horizontal scan line, and a quiet dotted progress band.
 * For users who do not want a genre theme.
 */
export function PlainDarkTheme({
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
    const draw = () => {
      ctx.fillStyle = "rgba(10,12,16,0.20)";
      ctx.fillRect(0, 0, w, h);
      // Soft radial breathing
      const r = Math.min(w, h) * (0.32 + Math.sin(t * 0.012) * 0.04);
      const grad = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, r);
      grad.addColorStop(0, "rgba(200,210,225,0.08)");
      grad.addColorStop(1, "rgba(10,12,16,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);
      // Slow horizontal scan
      const sy = (t * 0.5) % h;
      const sg = ctx.createLinearGradient(0, sy - 20, 0, sy + 20);
      sg.addColorStop(0, "rgba(200,210,225,0)");
      sg.addColorStop(0.5, "rgba(200,210,225,0.06)");
      sg.addColorStop(1, "rgba(200,210,225,0)");
      ctx.fillStyle = sg;
      ctx.fillRect(0, sy - 20, w, 40);
      // Quiet dotted progress band along the bottom
      const dotSpacing = 18;
      for (let x = dotSpacing; x < w; x += dotSpacing) {
        const phase = Math.sin((x + t * 2) * 0.02);
        const a = 0.15 + Math.abs(phase) * 0.3;
        ctx.fillStyle = `rgba(200,210,225,${a})`;
        ctx.beginPath();
        ctx.arc(x, h - 22, 1.5, 0, Math.PI * 2);
        ctx.fill();
      }
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
  const primary = "#e6eaf2";
  const dim = "rgba(200,210,225,0.55)";

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#0a0c10" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(10,12,16,0)_0%,rgba(10,12,16,0.78)_100%)]" />
        <ThemeOverlay
          label={label}
          elapsedSeconds={elapsedSeconds}
          primary={primary}
          dim={dim}
          subLabel="working"
          arrow="·"
          chipShape="ring"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#0a0c10" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-90" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
