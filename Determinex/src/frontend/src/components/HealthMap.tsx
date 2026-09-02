"use client";
import { useState, useCallback } from "react";
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
  LayoutGrid,
  FileCode,
} from "lucide-react";
import { getHealthTelemetry, isTauri } from "@/lib/api";

type FileHealth = {
  path: string;
  dir: string;
  status: "pass" | "warn" | "error";
  errors: number;
  warnings: number;
  lastChecked: string;
};

const INITIAL_HEALTH: FileHealth[] = [];

const STATUS_CONFIG = {
  pass: { color: "var(--dtx-ok)", glow: "rgba(52,211,153,0.3)", Icon: CheckCircle2, label: "PASS" },
  warn: {
    color: "var(--dtx-warn)",
    glow: "rgba(245,158,11,0.3)",
    Icon: AlertTriangle,
    label: "WARN",
  },
  error: { color: "var(--dtx-fail)", glow: "rgba(248,113,113,0.3)", Icon: XCircle, label: "ERROR" },
};

function FileCard({
  file,
  selected,
  onClick,
}: {
  file: FileHealth;
  selected: boolean;
  onClick: () => void;
}) {
  const cfg = STATUS_CONFIG[file.status];
  return (
    <button
      onClick={onClick}
      className="group relative text-left rounded-xl border px-3 py-2.5 transition-all hover:scale-[1.02]"
      style={{
        borderColor: selected ? cfg.color + "60" : "rgba(255,255,255,0.07)",
        background: selected
          ? `linear-gradient(135deg, ${cfg.glow}, rgba(0,0,0,0.4))`
          : "rgba(255,255,255,0.02)",
        boxShadow: selected ? `0 0 12px ${cfg.glow}` : undefined,
      }}
    >
      <div
        className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r"
        style={{ background: cfg.color, boxShadow: `0 0 6px ${cfg.glow}` }}
      />
      <div className="pl-2 flex items-center justify-between gap-1.5 mb-1">
        <span className="text-label font-bold text-white/70 truncate">{file.path}</span>
        <cfg.Icon size={11} style={{ color: cfg.color }} className="shrink-0" />
      </div>
      <div className="pl-2 flex items-center justify-between">
        <span className="text-meta text-white/25 font-mono truncate">{file.dir}/</span>
        {(file.errors > 0 || file.warnings > 0) && (
          <span className="text-meta font-mono" style={{ color: cfg.color }}>
            {file.errors > 0 ? `${file.errors}e` : `${file.warnings}w`}
          </span>
        )}
      </div>
    </button>
  );
}

export function HealthMap() {
  const [files, setFiles] = useState<FileHealth[]>(INITIAL_HEALTH);
  const [selected, setSelected] = useState<FileHealth | null>(null);
  const [scanning, setScanning] = useState(false);
  const [lastScan, setLastScan] = useState<string>("not run");

  const dirs = Array.from(new Set(files.map((f) => f.dir))).sort();
  const passing = files.filter((f) => f.status === "pass").length;
  const warnings = files.filter((f) => f.status === "warn").length;
  const errors = files.filter((f) => f.status === "error").length;

  const runScan = useCallback(async () => {
    setScanning(true);
    const telemetry = await getHealthTelemetry();
    // get_health_telemetry (ipc_health.rs) only ever returns "online" or "degraded" --
    // the "healthy"/"ok"/"offline"/"dev-mode" vocabulary below never matched, so status was
    // silently "warn" on every real call regardless of actual backend health. Real mapping
    // added; the old strings are kept in case a future caller uses them.
    const isHealthy =
      telemetry.status === "online" || telemetry.status === "healthy" || telemetry.status === "ok";
    const isDown =
      telemetry.status === "degraded" ||
      telemetry.status === "offline" ||
      telemetry.status === "dev-mode";
    const status: FileHealth["status"] = isHealthy ? "pass" : isDown ? "warn" : "error";
    setFiles([
      {
        path: "backend telemetry",
        dir: "runtime",
        status,
        errors: status === "error" ? 1 : 0,
        warnings: status === "warn" ? 1 : 0,
        lastChecked: "just now",
      },
    ]);
    setScanning(false);
    setLastScan(telemetry.status);
  }, []);

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden p-5">
      <div className="pointer-events-none absolute inset-0 opacity-10">
        <div
          className="absolute left-0 bottom-0 h-[400px] w-[400px] -translate-x-1/3 translate-y-1/3 rounded-full"
          style={{ background: "var(--determinex-accent)", filter: "blur(100px)" }}
        />
      </div>

      <div className="relative z-10 flex min-h-0 flex-1 flex-col gap-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-white/10 pb-4">
          <div>
            <div className="flex items-center gap-2 text-meta font-black uppercase tracking-widest text-[var(--determinex-accent)] mb-2">
              <LayoutGrid size={13} /> Project Health
            </div>
            <h2
              className="text-hero font-black leading-tight text-[var(--determinex-text)]"
              style={{ fontFamily: "var(--determinex-font-display)" }}
            >
              Oracle Map
            </h2>
          </div>
          <div className="flex flex-col items-end gap-2">
            <button
              onClick={runScan}
              disabled={scanning}
              className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-meta font-bold uppercase tracking-widest text-gray-400 transition-all hover:border-[var(--determinex-accent)]/40 hover:text-white disabled:opacity-40"
            >
              <RefreshCw size={12} className={scanning ? "animate-spin" : ""} />
              {scanning ? "Scanning…" : "Re-scan"}
            </button>
            <span className="text-meta text-gray-700 font-mono">Last scan: {lastScan}</span>
          </div>
        </div>

        {/* Summary chips */}
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: "Passing", count: passing, color: "var(--dtx-ok)" },
            { label: "Warnings", count: warnings, color: "var(--dtx-warn)" },
            { label: "Errors", count: errors, color: "var(--dtx-fail)" },
          ].map((s) => (
            <div
              key={s.label}
              className="rounded-xl border border-white/8 bg-black/30 p-3 text-center"
            >
              <div className="font-mono text-display font-black" style={{ color: s.color }}>
                {s.count}
              </div>
              <div className="text-eyebrow uppercase tracking-widest text-gray-600 mt-0.5">
                {s.label}
              </div>
            </div>
          ))}
        </div>

        {/* File grid grouped by dir */}
        <div className="flex-1 overflow-y-auto no-scrollbar space-y-4">
          {dirs.length === 0 && (
            <div className="flex h-full min-h-[160px] flex-col items-center justify-center gap-1 opacity-40">
              <p className="text-label text-gray-500">No file diagnostics loaded</p>
              <p className="max-w-[300px] text-center text-meta text-gray-700">
                Re-scan reads backend telemetry. File-level oracle diagnostics need a collector
                feed.
              </p>
            </div>
          )}
          {dirs.map((dir) => {
            const dirFiles = files.filter((f) => f.dir === dir);
            return (
              <div key={dir}>
                <div className="flex items-center gap-2 mb-2">
                  <FileCode size={11} className="text-gray-600" />
                  <span className="text-eyebrow font-mono uppercase tracking-widest text-gray-600">
                    {dir}/
                  </span>
                  <div className="flex-1 h-px bg-white/5" />
                  <span className="text-meta font-mono text-gray-700">{dirFiles.length}</span>
                </div>
                <div className="grid grid-cols-2 gap-1.5">
                  {dirFiles.map((f) => (
                    <FileCard
                      key={f.path}
                      file={f}
                      selected={selected?.path === f.path}
                      onClick={() => setSelected(selected?.path === f.path ? null : f)}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        {/* Selected file detail */}
        {selected && (
          <div className="rounded-2xl border border-white/10 bg-black/40 p-4 shrink-0">
            <div className="flex items-center justify-between mb-3">
              <span className="text-label font-black text-white">{selected.path}</span>
              <span
                className={`text-meta font-mono font-black px-2 py-0.5 rounded`}
                style={{
                  color: STATUS_CONFIG[selected.status].color,
                  background: STATUS_CONFIG[selected.status].glow,
                }}
              >
                {STATUS_CONFIG[selected.status].label}
              </span>
            </div>
            <div className="text-label text-gray-500 font-mono">{selected.dir}/</div>
            <div className="flex gap-4 mt-3 text-label font-mono">
              <span className={selected.errors > 0 ? "text-red-400" : "text-gray-700"}>
                {selected.errors} errors
              </span>
              <span className={selected.warnings > 0 ? "text-amber-400" : "text-gray-700"}>
                {selected.warnings} warnings
              </span>
              <span className="text-gray-700">checked {selected.lastChecked}</span>
            </div>
          </div>
        )}

        {!isTauri() && (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2 text-meta text-gray-700 font-mono text-center shrink-0">
            Browser mode cannot read native telemetry. Open the Tauri desktop app for live status.
          </div>
        )}
      </div>
    </div>
  );
}
