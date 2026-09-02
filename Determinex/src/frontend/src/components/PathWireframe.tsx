"use client";

import React from "react";
import { PathInfo } from "@/components/ConceptLab";
import { AndroidBaselineMock } from "./wireframes/AndroidBaselineMock";

// ─────────────────────────────────────────────────────────────────────────────
// Detects the wireframe type from path name + stack
// ─────────────────────────────────────────────────────────────────────────────

function detectType(
  path: PathInfo
): "crossPlatform" | "mobile" | "api" | "cli" | "dashboard" | "web" {
  const sig = (path.name + " " + path.stack).toLowerCase();
  if (
    sig.includes("web + mobile") ||
    sig.includes("website + mobile") ||
    sig.includes("web and mobile") ||
    sig.includes("mobile and web") ||
    (sig.includes("next.js") && (sig.includes("react native") || sig.includes("flutter")))
  )
    return "crossPlatform";
  if (
    sig.includes("mobile") ||
    sig.includes("flutter") ||
    sig.includes("react native") ||
    sig.includes("expo") ||
    sig.includes("ios") ||
    sig.includes("android")
  )
    return "mobile";
  if (
    sig.includes("api") ||
    sig.includes("backend") ||
    sig.includes("actix") ||
    sig.includes("axum") ||
    sig.includes("fastapi") ||
    sig.includes("ktor") ||
    sig.includes("rest") ||
    sig.includes("graphql")
  )
    return "api";
  if (
    sig.includes("cli") ||
    sig.includes("command") ||
    sig.includes("terminal") ||
    sig.includes("daemon")
  )
    return "cli";
  if (
    sig.includes("dashboard") ||
    sig.includes("analytics") ||
    sig.includes("metrics") ||
    sig.includes("monitor")
  )
    return "dashboard";
  return "web";
}

// ─────────────────────────────────────────────────────────────────────────────
// MOBILE
// ─────────────────────────────────────────────────────────────────────────────

function MobileWireframe({ color }: { color: string }) {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="relative" style={{ width: 170, height: 310 }}>
        <div
          className="absolute inset-0 rounded-[28px] border-2"
          style={{ borderColor: `${color}45` }}
        />
        <div className="absolute inset-[5px] rounded-[23px] bg-[var(--dtx-code-bg-deep)] overflow-hidden">
          <div className="h-5 flex items-center justify-between px-4 border-b border-gray-800/60">
            <div className="w-8 h-1 rounded bg-gray-700" />
            <div className="w-3 h-3 rounded-full border border-gray-700" />
          </div>
          <div
            className="mx-2.5 mt-2 h-20 rounded-xl border flex items-center justify-center"
            style={{ borderColor: `${color}20`, background: `${color}08` }}
          >
            <div className="w-8 h-8 rounded-xl border" style={{ borderColor: `${color}35` }} />
          </div>
          {[1, 0.7, 0.5].map((w, i) => (
            <div key={i} className="mx-2.5 mt-2.5 flex gap-2 items-center">
              <div
                className="w-6 h-6 rounded-lg border shrink-0"
                style={{
                  borderColor: `${color}${i === 0 ? "40" : "20"}`,
                  background: `${color}${i === 0 ? "12" : "06"}`,
                }}
              />
              <div className="flex-1 flex flex-col gap-1">
                <div className="h-1.5 rounded bg-gray-700" style={{ width: `${w * 100}%` }} />
                <div className="h-1 rounded bg-gray-800" style={{ width: `${w * 60}%` }} />
              </div>
            </div>
          ))}
          <div className="absolute bottom-0 inset-x-0 h-10 border-t border-gray-800/60 flex items-center justify-around px-3">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex flex-col items-center gap-1">
                <div
                  className="w-3.5 h-3.5 rounded-md"
                  style={{
                    background: i === 0 ? `${color}25` : "transparent",
                    border: `1px solid ${i === 0 ? color + "50" : "var(--dtx-code-border)"}`,
                  }}
                />
                <div
                  className="w-3.5 h-1 rounded"
                  style={{ background: i === 0 ? `${color}40` : "var(--dtx-code-raised)" }}
                />
              </div>
            ))}
          </div>
        </div>
        <div className="absolute top-[5px] left-1/2 -translate-x-1/2 w-12 h-4 rounded-b-xl bg-[var(--dtx-code-bg-deep)]" />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// WEB
// ─────────────────────────────────────────────────────────────────────────────

function WebWireframe({ color }: { color: string }) {
  return (
    <div className="flex items-center justify-center h-full px-6">
      <div className="w-full" style={{ maxWidth: 520 }}>
        <div className="rounded-t-xl border border-b-0 border-gray-700/60 bg-[var(--dtx-code-panel)]">
          <div className="h-7 flex items-center gap-2 px-3">
            <div className="flex gap-1.5">
              {["var(--dtx-fail)", "var(--dtx-warn)", "var(--dtx-ok)"].map((c) => (
                <div
                  key={c}
                  className="w-2 h-2 rounded-full opacity-50"
                  style={{ background: c }}
                />
              ))}
            </div>
            <div className="flex-1 h-3.5 rounded bg-[var(--dtx-code-bg-deep)] border border-gray-800 mx-2 flex items-center px-2">
              <div className="h-1 w-16 rounded bg-gray-700" />
            </div>
          </div>
        </div>
        <div className="border border-gray-700/60 rounded-b-xl bg-[var(--dtx-code-bg-deep)] overflow-hidden">
          <div
            className="h-8 flex items-center gap-3 px-4 border-b"
            style={{ borderColor: `${color}18` }}
          >
            <div className="h-2 w-14 rounded" style={{ background: `${color}45` }} />
            <div className="flex-1 flex gap-3 justify-end items-center">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-1.5 w-8 rounded bg-gray-800" />
              ))}
              <div
                className="h-4 w-12 rounded"
                style={{ background: `${color}20`, border: `1px solid ${color}40` }}
              />
            </div>
          </div>
          <div className="px-4 pt-3 pb-2">
            <div className="h-2.5 w-2/3 rounded bg-gray-700 mb-1.5" />
            <div className="h-1.5 w-1/2 rounded bg-gray-800 mb-2.5" />
            <div className="flex gap-2">
              <div
                className="h-6 w-16 rounded-lg"
                style={{ background: `${color}25`, border: `1px solid ${color}50` }}
              />
              <div className="h-6 w-16 rounded-lg border border-gray-800" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 px-4 pb-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="rounded-xl border p-2"
                style={{
                  borderColor: i === 0 ? `${color}30` : "var(--dtx-code-border)",
                  background: i === 0 ? `${color}08` : "var(--dtx-code-bg)",
                }}
              >
                <div
                  className="h-8 rounded-lg mb-1.5"
                  style={{ background: i === 0 ? `${color}15` : "var(--dtx-code-panel)" }}
                />
                <div className="h-1.5 w-3/4 rounded bg-gray-700 mb-1" />
                <div className="h-1 w-1/2 rounded bg-gray-800" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function CrossPlatformWireframe({ color }: { color: string }) {
  return (
    <div className="flex h-full items-center justify-center gap-5 px-5">
      <div className="h-[82%] min-w-0 flex-[1.4] rounded-2xl border border-gray-700/60 bg-[var(--dtx-code-bg-deep)] p-3">
        <div className="mb-3 flex items-center gap-1.5">
          <div className="h-2.5 w-2.5 rounded-full bg-red-400/70" />
          <div className="h-2.5 w-2.5 rounded-full bg-yellow-400/70" />
          <div className="h-2.5 w-2.5 rounded-full bg-emerald-400/70" />
          <div className="ml-auto h-2 w-20 rounded bg-gray-700" />
        </div>
        <div className="grid h-[calc(100%-24px)] grid-cols-[0.42fr_1fr] gap-3">
          <div className="rounded-xl border border-gray-800 bg-[var(--dtx-code-bg)] p-3">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="mb-2 h-6 rounded-lg border"
                style={{
                  borderColor: i === 0 ? `${color}55` : "var(--dtx-code-raised)",
                  background: i === 0 ? `${color}14` : "var(--dtx-code-panel)",
                }}
              />
            ))}
          </div>
          <div
            className="rounded-xl border p-4"
            style={{ borderColor: `${color}25`, background: `${color}08` }}
          >
            <div
              className="h-20 rounded-xl border"
              style={{ borderColor: `${color}35`, background: `${color}10` }}
            />
            <div className="mt-4 grid grid-cols-3 gap-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-16 rounded-lg border border-gray-800 bg-[var(--dtx-code-panel)]"
                />
              ))}
            </div>
            <div className="mt-4 h-2 w-2/3 rounded bg-gray-700" />
            <div className="mt-2 h-2 w-1/2 rounded bg-gray-800" />
          </div>
        </div>
      </div>
      <div
        className="h-[76%] w-[132px] shrink-0 rounded-[26px] border-2 p-1"
        style={{ borderColor: `${color}45` }}
      >
        <div className="h-full overflow-hidden rounded-[21px] bg-[var(--dtx-code-bg-deep)]">
          <div className="h-5 border-b border-gray-800/60" />
          <div
            className="mx-2 mt-2 h-20 rounded-xl border"
            style={{ borderColor: `${color}35`, background: `${color}12` }}
          />
          {[0, 1, 2].map((i) => (
            <div key={i} className="mx-2 mt-2 flex items-center gap-2">
              <div className="h-6 w-6 rounded-lg border" style={{ borderColor: `${color}30` }} />
              <div className="min-w-0 flex-1">
                <div className="h-1.5 rounded bg-gray-700" />
                <div className="mt-1 h-1 w-2/3 rounded bg-gray-800" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

function ApiWireframe({ color }: { color: string }) {
  const endpoints = [
    { method: "GET", status: 200 },
    { method: "POST", status: 201 },
    { method: "GET", status: 200 },
    { method: "PUT", status: 200 },
    { method: "DELETE", status: 204 },
  ];
  const mc: Record<string, string> = {
    GET: "var(--dtx-ok)",
    POST: "var(--dtx-info)",
    PUT: "var(--dtx-warn)",
    DELETE: "var(--dtx-fail)",
  };
  const widths = [100, 80, 130, 130, 130];
  return (
    <div className="flex items-center justify-center h-full px-6">
      <div className="w-full" style={{ maxWidth: 460 }}>
        <div className="flex items-center gap-2 mb-3">
          <div className="w-2 h-2 rounded-full" style={{ background: color }} />
          <div className="h-1.5 w-20 rounded bg-gray-700" />
          <div className="ml-auto text-meta font-mono" style={{ color: `${color}80` }}>
            v1.0
          </div>
        </div>
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: `${color}25` }}>
          {endpoints.map((ep, i) => (
            <div
              key={i}
              className="flex items-center gap-3 px-4 py-2"
              style={{
                borderBottom: i < 4 ? "1px solid var(--dtx-code-border-subtle)" : "none",
                background: i === 0 ? `${color}07` : "transparent",
              }}
            >
              <div
                className="text-meta font-black font-mono w-10 shrink-0"
                style={{ color: mc[ep.method] || color }}
              >
                {ep.method}
              </div>
              <div className="flex-1 flex items-center gap-1">
                <div className="h-1.5 rounded bg-gray-700" style={{ width: widths[i] }} />
              </div>
              <div
                className="text-meta font-mono"
                style={{
                  color: ep.status < 300 ? "var(--dtx-ok)" : "var(--dtx-fail)",
                  opacity: 0.7,
                }}
              >
                {ep.status}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {["Auth (JWT)", "Schema"].map((_, i) => (
            <div
              key={i}
              className="border border-gray-800 rounded-xl p-3"
              style={{ borderColor: i === 0 ? `${color}20` : undefined }}
            >
              <div className="h-1.5 w-12 rounded bg-gray-700 mb-1.5" />
              <div className="h-1 w-full rounded bg-gray-800 mb-1" />
              <div className="h-1 w-3/4 rounded bg-gray-800" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// CLI
// ─────────────────────────────────────────────────────────────────────────────

function CliWireframe({ color }: { color: string }) {
  const lines = [
    { prompt: true, text: "mytool --watch ./src --run tests", kind: "cmd" },
    { prompt: false, text: "→ Watching 14 files", kind: "info" },
    { prompt: false, text: "✓ PASS  12 tests  84ms", kind: "pass" },
    { prompt: false, text: "→ File changed: src/parser.go", kind: "info" },
    { prompt: false, text: "✓ PASS  12 tests  91ms", kind: "pass" },
    { prompt: true, text: "_", kind: "cursor" },
  ];
  const lc = (kind: string) =>
    kind === "pass"
      ? "var(--dtx-ok)"
      : kind === "cmd"
        ? "var(--dtx-code-text)"
        : kind === "cursor"
          ? color
          : "var(--dtx-code-muted)";
  return (
    <div className="flex items-center justify-center h-full px-6">
      <div className="w-full" style={{ maxWidth: 460 }}>
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: `${color}30` }}>
          <div className="h-7 flex items-center gap-2 px-3 bg-[var(--dtx-code-panel)] border-b border-gray-800">
            {["var(--dtx-fail)", "var(--dtx-warn)", "var(--dtx-ok)"].map((c) => (
              <div key={c} className="w-2 h-2 rounded-full opacity-50" style={{ background: c }} />
            ))}
            <div className="flex-1 text-center text-meta font-mono text-gray-600">zsh</div>
          </div>
          <div className="bg-[var(--dtx-code-bg-deep)] px-4 py-3 font-mono text-meta flex flex-col gap-1.5">
            {lines.map((line, i) => (
              <div key={i} className="flex gap-2">
                <span style={{ color: line.prompt ? `${color}90` : "var(--dtx-code-border)" }}>
                  {line.prompt ? "$" : "·"}
                </span>
                <span style={{ color: lc(line.kind) }}>
                  {line.text === "_" ? <span className="animate-pulse">▌</span> : line.text}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// DASHBOARD
// ─────────────────────────────────────────────────────────────────────────────

function DashboardWireframe({ color }: { color: string }) {
  const bars = [60, 42, 76, 55, 88, 48, 71];
  return (
    <div className="flex items-center justify-center h-full px-6">
      <div className="w-full" style={{ maxWidth: 500 }}>
        <div className="grid grid-cols-4 gap-2 mb-3">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="border rounded-xl p-2.5"
              style={{
                borderColor: i === 0 ? `${color}35` : "var(--dtx-code-border)",
                background: i === 0 ? `${color}08` : "var(--dtx-code-bg)",
              }}
            >
              <div className="h-1 w-8 rounded bg-gray-700 mb-1.5" />
              <div
                className="h-4 w-10 rounded"
                style={{ background: i === 0 ? `${color}40` : "var(--dtx-code-border)" }}
              />
              <div className="h-1 w-6 rounded bg-gray-800 mt-1.5" />
            </div>
          ))}
        </div>
        <div className="grid grid-cols-5 gap-2">
          <div
            className="col-span-3 border border-gray-700/50 rounded-xl p-3"
            style={{ borderColor: `${color}20` }}
          >
            <div className="h-1.5 w-14 rounded bg-gray-700 mb-3" />
            <div className="flex items-end gap-1 h-14">
              {bars.map((h, i) => (
                <div
                  key={i}
                  className="flex-1 rounded-t"
                  style={{ height: `${h}%`, background: i === 4 ? color : `${color}28` }}
                />
              ))}
            </div>
          </div>
          <div className="col-span-2 flex flex-col gap-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="border border-gray-800 rounded-xl p-2 flex items-center gap-2"
              >
                <div
                  className="w-4 h-4 rounded-lg shrink-0"
                  style={{ background: `${color}${["25", "18", "10"][i]}` }}
                />
                <div className="flex flex-col gap-1">
                  <div className="h-1.5 w-12 rounded bg-gray-700" />
                  <div className="h-1 w-8 rounded bg-gray-800" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC EXPORT
// ─────────────────────────────────────────────────────────────────────────────

export function PathWireframe({
  path,
  className = "",
  colorOverride,
}: {
  path: PathInfo;
  className?: string;
  /** When set (e.g. extracted from a user-attached image), overrides path.color in the wireframe. */
  colorOverride?: string;
}) {
  const type = detectType(path);
  const color = colorOverride || path.color;
  const isIceCream =
    path.name.toLowerCase().includes("ice") || path.stack.toLowerCase().includes("ice");

  const inner =
    type === "crossPlatform" ? (
      <CrossPlatformWireframe color={color} />
    ) : type === "mobile" ? (
      isIceCream ? (
        <AndroidBaselineMock color={color} />
      ) : (
        <MobileWireframe color={color} />
      )
    ) : type === "api" ? (
      <ApiWireframe color={color} />
    ) : type === "cli" ? (
      <CliWireframe color={color} />
    ) : type === "dashboard" ? (
      <DashboardWireframe color={color} />
    ) : (
      <WebWireframe color={color} />
    );

  return <div className={`h-full w-full ${className}`}>{inner}</div>;
}
