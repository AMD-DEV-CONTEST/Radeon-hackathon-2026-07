"use client";
import React, { useRef, useEffect } from "react";
import type { LoadingThemeProps } from "./types";

// Terrain-style 3D filesystem navigator.
const FS_LABELS = [
  "/usr",
  "/bin",
  "/etc",
  "/var",
  "/tmp",
  "/home",
  "/lib",
  "/opt",
  "/proc",
  "/dev",
  "/sys",
  "/root",
  "./schema",
  "./cache",
  "./index",
  "./core",
  "./router",
  "./worker",
  "./node-a",
  "./node-b",
  "./node-c",
  "./node-d",
  "./node-e",
  "./queue",
  "./egress",
  "./ingress",
];
const TRACE_LINES = [
  "ACCESS DENIED",
  "AUTHORIZATION REQUIRED",
  "ROUTE NOT FOUND",
  "INDEX LOCKED",
  "TRACE COMPLETE",
  "FILESYSTEM MAP ONLINE",
  "PATCH VERIFIED",
  "QUEUE DEPTH WITHIN BOUNDS",
  "GRAPH WALK RESUMING",
];

export function TerrainNavigatorTheme({
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

    const GREEN = "#00cc44";

    // 3D filesystem — nodes rotating around a center
    interface FSNode {
      label: string;
      theta: number;
      phi: number;
      r: number;
      size: number;
      children: number[];
    }
    const nodes: FSNode[] = FS_LABELS.map((label, i) => ({
      label,
      theta: (i / FS_LABELS.length) * Math.PI * 2 + Math.random() * 0.5,
      phi: (Math.random() - 0.5) * Math.PI * 0.6,
      r: 60 + Math.random() * 80,
      size: 2 + Math.random() * 3,
      children: i < 10 ? [Math.floor(Math.random() * FS_LABELS.length)] : [],
    }));

    let rotX = 0,
      rotY = 0;
    let tick = 0;
    let raf: number;

    const project3D = (x: number, y: number, z: number) => {
      // Rotate around Y
      const cosY = Math.cos(rotY),
        sinY = Math.sin(rotY);
      const rx = cosY * x + sinY * z,
        rz = -sinY * x + cosY * z;
      // Rotate around X
      const cosX = Math.cos(rotX),
        sinX = Math.sin(rotX);
      const ry = cosX * y - sinX * rz,
        rz2 = sinX * y + cosX * rz;
      const fov = 280,
        dz = rz2 + 300;
      return { sx: w / 2 + (rx * fov) / dz, sy: h / 2 + (ry * fov) / dz, depth: dz };
    };

    const draw = () => {
      ctx.fillStyle = "rgba(0,5,2,0.2)";
      ctx.fillRect(0, 0, w, h);

      rotY += 0.004;
      rotX = Math.sin(tick * 0.008) * 0.3;

      // Compute 3D positions
      const positions = nodes.map((n) => {
        const x = n.r * Math.cos(n.theta + rotY * 0.5) * Math.cos(n.phi);
        const y = n.r * Math.sin(n.phi) * 1.5;
        const z = n.r * Math.sin(n.theta + rotY * 0.5) * Math.cos(n.phi);
        return project3D(x, y, z);
      });

      // Draw edges
      nodes.forEach((n, i) => {
        n.children.forEach((ci) => {
          if (ci >= positions.length) return;
          const a = positions[i],
            b = positions[ci];
          const alpha = Math.min(0.25, Math.min(1 / a.depth, 1 / b.depth) * 80);
          ctx.beginPath();
          ctx.moveTo(a.sx, a.sy);
          ctx.lineTo(b.sx, b.sy);
          ctx.strokeStyle = `rgba(0,204,68,${alpha})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        });
      });

      // Draw central hub lines
      nodes.forEach((n, i) => {
        const a = positions[i];
        const alpha = Math.min(0.15, 60 / a.depth);
        ctx.beginPath();
        ctx.moveTo(w / 2, h / 2);
        ctx.lineTo(a.sx, a.sy);
        ctx.strokeStyle = `rgba(0,204,68,${alpha})`;
        ctx.lineWidth = 0.3;
        ctx.stroke();
      });

      // Draw nodes sorted by depth
      const sorted = nodes
        .map((n, i) => ({ n, p: positions[i], i }))
        .sort((a, b) => b.p.depth - a.p.depth);
      sorted.forEach(({ n, p }) => {
        const scale = Math.min(1.5, 200 / p.depth);
        const alpha = Math.min(0.9, 150 / p.depth);

        // Node glow
        ctx.beginPath();
        ctx.arc(p.sx, p.sy, n.size * scale * 2, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(0,204,68,${alpha * 0.15})`;
        ctx.fill();

        // Node core
        ctx.beginPath();
        ctx.arc(p.sx, p.sy, n.size * scale, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(0,204,68,${alpha})`;
        ctx.fill();

        // Label
        if (scale > 0.7 && alpha > 0.3) {
          ctx.fillStyle = `rgba(0,204,68,${alpha * 0.7})`;
          ctx.font = `${Math.floor(7 * scale)}px monospace`;
          ctx.fillText(n.label, p.sx + n.size * scale + 2, p.sy + 3);
        }
      });

      // Center hub
      const hubPulse = Math.sin(tick * 0.05) * 0.3 + 0.7;
      ctx.beginPath();
      ctx.arc(w / 2, h / 2, 8 * hubPulse, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0,204,68,${0.4 * hubPulse})`;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(w / 2, h / 2, 4, 0, Math.PI * 2);
      ctx.fillStyle = GREEN;
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

  const green = "#00cc44";
  const quote = TRACE_LINES[Math.floor(Date.now() / 4500) % TRACE_LINES.length];

  if (fullPanel) {
    return (
      <div className="absolute inset-0 z-20 overflow-hidden" style={{ background: "#000502" }}>
        <canvas ref={canvasRef} className="absolute inset-0" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,5,2,0.0)_0%,rgba(0,5,2,0.7)_100%)]" />

        <div className="absolute bottom-8 left-0 right-0 flex flex-col items-center gap-3">
          <p
            className="text-eyebrow font-mono tracking-[0.6em] uppercase"
            style={{ color: `${green}50` }}
          >
            TERRAIN NAVIGATOR - UNIX FILESYSTEM v4.0.1
          </p>
          <p
            className="text-body font-mono font-bold"
            style={{ color: green, textShadow: `0 0 12px ${green}80` }}
          >
            &quot;{quote}&quot;
          </p>
          <p
            className="text-body font-mono tracking-widest uppercase font-bold"
            style={{ color: `${green}90` }}
          >
            {label}
          </p>
          {elapsedSeconds !== undefined && elapsedSeconds > 0 && (
            <p className="text-meta font-mono tabular-nums" style={{ color: `${green}50` }}>
              ANALYZING — {elapsedSeconds}s
            </p>
          )}

          <div className="flex items-center gap-3 mt-1">
            {[
              { role: "Oracle", active: true },
              { role: "Architect", active: false },
              { role: "Builder", active: false },
              { role: "Compiler", active: false },
            ].map(({ role, active: nodeActive }, i, arr) => (
              <React.Fragment key={role}>
                <div className="flex flex-col items-center gap-1">
                  <div
                    className="w-4 h-4 border flex items-center justify-center"
                    style={{
                      borderColor: nodeActive ? green : `${green}25`,
                      borderRadius: "2px",
                      background: nodeActive ? `${green}20` : "transparent",
                      boxShadow: nodeActive ? `0 0 6px ${green}60` : "none",
                    }}
                  >
                    {nodeActive && <div className="w-1.5 h-1.5" style={{ background: green }} />}
                  </div>
                  <span
                    className="text-eyebrow font-mono uppercase"
                    style={{ color: nodeActive ? green : `${green}30` }}
                  >
                    {role}
                  </span>
                </div>
                {i < arr.length - 1 && (
                  <div className="w-5 h-px mb-4" style={{ background: `${green}20` }} />
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
      style={{ background: "#000502" }}
    >
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,5,2,0.1)_0%,rgba(0,5,2,0.85)_100%)]" />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
        <div
          className="w-6 h-6 border-2 animate-spin"
          style={{ borderColor: `${green}40`, borderTopColor: green, borderRadius: "2px" }}
        />
        <p className="text-meta font-mono tracking-widest uppercase" style={{ color: green }}>
          {label}
        </p>
      </div>
    </div>
  );
}
