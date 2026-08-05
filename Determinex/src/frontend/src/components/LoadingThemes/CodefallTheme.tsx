"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";

const GHOST_TOKENS = [
  "fn",
  "let",
  "mut",
  "Arc",
  "Mutex",
  "Result",
  "Option",
  "impl",
  "struct",
  "::",
  "->",
  "=>",
  "<T>",
  "use",
  "pub",
  "async",
  "await",
  "match",
  "Some",
  "None",
  "Ok",
  "Err",
  "Vec",
  "HashMap",
  "Box",
  "String",
  "usize",
  "bool",
  "trait",
  "enum",
  "derive",
  "Clone",
  "Debug",
  "Send",
  "Sync",
  "mod",
  "const",
  "static",
  "return",
  "move",
  "where",
  "for<",
  "dyn",
  "Arc<Mutex<",
  "Box<dyn",
  "impl Future",
  "-> Result<",
  "anyhow::",
  "#[derive(",
  "tokio::spawn",
];
const NUM_COLS = 7,
  ROWS = 18;

export function CodefallTheme({
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

    const chars =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789$+-*/=%\"'#&_(),.;:?!|{}<>[]^~ã‚¢ã‚£ã‚«ã‚µã‚¿ãƒŠãƒãƒžãƒ¤ãƒ©ãƒ¯ã‚¬ã‚¶ãƒ€ãƒãƒ‘ã‚¤ã‚­ã‚·ãƒãƒ‹ãƒ’ãƒŸãƒªã‚®ã‚¸ãƒ‚ãƒ“ãƒ”ã‚¦ã‚¯ã‚¹ãƒ„ãƒŒãƒ•ãƒ ãƒ¦ãƒ¥ãƒ«ã‚°ã‚ºãƒ–ãƒ…ãƒ—ã‚¨ã‚±ã‚»ãƒ†ãƒãƒ˜ãƒ¡ãƒ¬ã‚²ã‚¼ãƒ‡ãƒ™ãƒšã‚ªã‚³ã‚½ãƒˆãƒŽãƒ›ãƒ¢ãƒ¨ãƒ­ã‚´ã‚¾ãƒ‰ãƒœãƒãƒ´ãƒ³";
    const charArr = chars.split("");
    const cols = Math.floor(w / 14);
    const drops = Array(cols).fill(1);

    let raf: number;
    const draw = () => {
      ctx.fillStyle = "rgba(0,0,0,0.06)";
      ctx.fillRect(0, 0, w, h);
      ctx.font = "13px monospace";
      for (let i = 0; i < drops.length; i++) {
        ctx.fillStyle = Math.random() > 0.98 ? "#0ff" : "#0F0";
        ctx.fillText(charArr[Math.floor(Math.random() * charArr.length)], i * 14, drops[i] * 14);
        if (drops[i] * 14 > h && Math.random() > 0.975) drops[i] = 0;
        drops[i]++;
      }
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [active]);

  if (!active) return null;

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden bg-black">
        <canvas ref={canvasRef} className="absolute inset-0 opacity-50" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,0,0,0.2)_0%,rgba(0,0,0,0.82)_100%)]" />
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          {Array.from({ length: NUM_COLS }, (_, ci) => (
            <div
              key={ci}
              className="absolute top-0 flex flex-col gap-3"
              style={{
                left: `${ci * 14 + 3}%`,
                animation: `ghost-scroll ${10 + ci * 1.5}s linear infinite`,
                animationDelay: `${-(ci * 2.7)}s`,
              }}
            >
              {Array.from({ length: ROWS * 2 }, (_, ri) => (
                <span
                  key={ri}
                  className="text-meta font-mono whitespace-nowrap select-none"
                  style={{ color: "#00e5ff", opacity: 0.12 + (ri % 5) * 0.025 }}
                >
                  {GHOST_TOKENS[(ci * 5 + (ri % ROWS) * 3) % GHOST_TOKENS.length]}
                </span>
              ))}
            </div>
          ))}
        </div>
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
          <div className="flex flex-col items-center gap-3">
            <div className="relative">
              <div className="w-8 h-8 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
              {elapsedSeconds !== undefined && elapsedSeconds > 0 && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-meta font-mono font-bold text-cyan-300 tabular-nums leading-none">
                    {elapsedSeconds}s
                  </span>
                </div>
              )}
            </div>
            <p className="text-body font-mono text-cyan-300 tracking-widest uppercase font-bold">
              {label}
            </p>
            <p className="text-label font-mono text-cyan-500/60 tracking-wide">
              encoding semantic intent...
            </p>
          </div>
          <div className="flex items-center gap-3 mt-6">
            {[
              { role: "Oracle", color: "#00e5ff", active: true },
              { role: "Architect", color: "var(--dtx-alt)", active: false },
              { role: "Builder", color: "var(--dtx-ok)", active: false },
              { role: "Compiler", color: "var(--dtx-warn)", active: false },
            ].map(({ role, color, active: nodeActive }, i, arr) => (
              <React.Fragment key={role}>
                <div className="flex flex-col items-center gap-1">
                  <div
                    className="w-5 h-5 rounded-full flex items-center justify-center"
                    style={{
                      background: `${color}${nodeActive ? "30" : "10"}`,
                      border: `1px solid ${color}${nodeActive ? "90" : "30"}`,
                      boxShadow: nodeActive ? `0 0 8px ${color}60` : "none",
                    }}
                  >
                    <div
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: color, opacity: nodeActive ? 1 : 0.3 }}
                    />
                  </div>
                  <span
                    className="text-eyebrow font-mono uppercase tracking-wider"
                    style={{ color, opacity: nodeActive ? 1 : 0.35 }}
                  >
                    {role}
                  </span>
                  {nodeActive && elapsedSeconds !== undefined && (
                    <span
                      className="text-meta font-mono font-bold tabular-nums"
                      style={{ color, opacity: 0.9 }}
                    >
                      {elapsedSeconds}s
                    </span>
                  )}
                </div>
                {i < arr.length - 1 && <span className="text-meta text-cyan-800 mb-4">â†’</span>}
              </React.Fragment>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 z-20 rounded-xl overflow-hidden pointer-events-none">
      <canvas ref={canvasRef} className="absolute inset-0 opacity-50" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,0,0,0.4)_0%,rgba(0,0,0,0.88)_100%)]" />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
        <div className="w-5 h-5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
        <p className="text-meta font-mono text-cyan-300 tracking-widest uppercase">{label}</p>
      </div>
    </div>
  );
}
