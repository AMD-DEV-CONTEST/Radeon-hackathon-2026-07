"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";
import { ThemeOverlay, SmallPanel } from "./_themePanel";

const FRAG = "01∇∆∮∂Σπ∞◇◊◆□■▣▤▥▦▧▨▩";

export function WraithTerminalTheme({
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
      // Translucent fade for ghosting effect
      ctx.fillStyle = "rgba(2,8,12,0.10)";
      ctx.fillRect(0, 0, w, h);
      // Signal noise band
      for (let y = 0; y < h; y += 1) {
        const noise = Math.random() * 0.04;
        ctx.fillStyle = `rgba(120,220,220,${noise})`;
        ctx.fillRect(0, y, w, 1);
      }
      // Drifting glyph wisps
      ctx.font = "12px monospace";
      for (let i = 0; i < 18; i++) {
        const x = (Math.sin(t * 0.003 + i) * 0.5 + 0.5) * w;
        const y = ((t * 0.6 + i * 47) % (h + 40)) - 20;
        const ch = FRAG[(Math.floor(t * 0.05) + i * 3) % FRAG.length];
        ctx.fillStyle = `rgba(180,255,240,${0.1 + (i % 4) * 0.06})`;
        ctx.fillText(ch, x, y);
      }
      // Faint vertical signal pulse
      const px = (t * 1.2) % w;
      const grad = ctx.createLinearGradient(px - 30, 0, px + 30, 0);
      grad.addColorStop(0, "rgba(120,220,220,0)");
      grad.addColorStop(0.5, "rgba(180,255,240,0.18)");
      grad.addColorStop(1, "rgba(120,220,220,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(px - 30, 0, 60, h);
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
  const primary = "#b8fff0",
    dim = "rgba(140,220,210,0.45)";
  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#02080c" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(2,8,12,0)_0%,rgba(2,8,12,0.82)_100%)]" />
        <ThemeOverlay
          label={label}
          elapsedSeconds={elapsedSeconds}
          primary={primary}
          dim={dim}
          subLabel="signal coherence rising"
          arrow="∿"
          chipShape="ring"
        />
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none"
      style={{ background: "#02080c" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0 opacity-80" />
      <SmallPanel label={label} primary={primary} />
    </div>
  );
}
