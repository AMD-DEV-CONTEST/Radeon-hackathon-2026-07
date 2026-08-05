"use client";

import React, { useMemo } from "react";
import {
  Zap,
  Clock,
  FileCode2,
  Shield,
  Package,
  Target,
  AlertTriangle,
  Wrench,
  ChevronRight,
} from "lucide-react";
import { PathInfo } from "@/components/ConceptLab";

// ─────────────────────────────────────────────────────────────────────────────
// SPEC PARSER — extracts sections from MD spec
// ─────────────────────────────────────────────────────────────────────────────

interface ParsedSpec {
  title: string;
  goal: string;
  language: string;
  constraints: string[];
  files: { name: string; purpose: string }[];
  dependencies: { name: string; why: string }[];
  tests: string[];
  notes: string;
}

function parseSpec(spec: string): ParsedSpec {
  const section = (heading: string): string => {
    const re = new RegExp(`## ${heading}\\n([\\s\\S]*?)(?=\\n## |$)`, "i");
    return spec.match(re)?.[1]?.trim() ?? "";
  };

  const bullets = (raw: string): string[] =>
    raw
      .split("\n")
      .map((l) => l.replace(/^[-*]\s*/, "").trim())
      .filter(Boolean);

  const titleMatch = spec.match(/^#\s+(.+)/m);

  const filesRaw = bullets(section("Files")).map((line) => {
    const m = line.match(/^`?([^`\s]+)`?\s*[—-]+\s*(.+)/);
    return m ? { name: m[1], purpose: m[2] } : { name: line, purpose: "" };
  });

  const depsRaw = bullets(section("Dependencies")).map((line) => {
    const m = line.match(/^`?([^`\s]+)`?\s*[—-]+\s*(.+)/);
    return m ? { name: m[1], why: m[2] } : { name: line, why: "" };
  });

  return {
    title: titleMatch?.[1]?.trim() ?? "Your Project",
    goal: section("Goal"),
    language: section("Language").toLowerCase() || "rust",
    constraints: bullets(section("Constraints")),
    files: filesRaw,
    dependencies: depsRaw,
    tests: bullets(section("Tests")),
    notes: section("Notes"),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// HIVE TIME ESTIMATOR
// ─────────────────────────────────────────────────────────────────────────────

function estimateHiveTime(fileCount: number, complexity: string): string {
  const stepsPerFile = complexity === "low" ? 3 : complexity === "high" ? 7 : 5;
  const totalSteps = Math.max(fileCount * stepsPerFile, 6);
  const minsPerStep = 2.5;
  const total = Math.round(totalSteps * minsPerStep);
  if (total < 30) return "15–30 min";
  if (total < 60) return `${Math.round(total / 10) * 10} min`;
  const hrs = total / 60;
  if (hrs < 1.5) return "~1 hour";
  return `${Math.ceil(hrs * 2) / 2}–${Math.ceil(hrs * 2) / 2 + 0.5} hours`;
}

const LANG_COLOR: Record<string, string> = {
  rust: "var(--dtx-warn)",
  go: "var(--dtx-info)",
  python: "var(--dtx-ok)",
  typescript: "var(--dtx-alt)",
  kotlin: "var(--dtx-alt)",
};

// ─────────────────────────────────────────────────────────────────────────────
// MAIN COMPONENT
// ─────────────────────────────────────────────────────────────────────────────

interface SpecBreakdownViewProps {
  spec: string;
  path: PathInfo | null;
  onBuild?: () => void;
  building?: boolean;
}

export function SpecBreakdownView({
  spec,
  path,
  onBuild,
  building = false,
}: SpecBreakdownViewProps) {
  const parsed = useMemo(() => parseSpec(spec), [spec]);
  const hiveTime = useMemo(
    () => estimateHiveTime(parsed.files.length, path?.complexity ?? "medium"),
    [parsed.files.length, path?.complexity]
  );
  const langColor = LANG_COLOR[parsed.language] ?? "var(--dtx-ok)";
  const pathColor = path?.color ?? "var(--dtx-alt-2)";

  return (
    <div className="flex flex-col h-full bg-[var(--dtx-code-bg)] text-gray-300 overflow-hidden">
      {/* Header */}
      <div className="shrink-0 px-6 py-4 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)]/60 flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-eyebrow uppercase font-bold tracking-widest text-emerald-400/70">
              Blueprint Ready
            </span>
            <span className="text-meta text-gray-700">·</span>
            <span
              className="text-meta font-mono px-1.5 py-0.5 rounded"
              style={{ color: langColor, background: `${langColor}15` }}
            >
              {parsed.language}
            </span>
          </div>
          <h2 className="text-title font-black text-gray-100 leading-tight truncate">
            {parsed.title}
          </h2>
        </div>
        {/* HIGH LEVEL notice */}
        <div className="shrink-0 flex items-center gap-1.5 bg-amber-950/40 border border-amber-500/25 rounded-xl px-3 py-1.5 max-w-[200px]">
          <AlertTriangle size={10} className="text-amber-400 shrink-0" />
          <span className="text-meta text-amber-300/80 leading-tight">
            High-level plan. Small details refined in the build loop.
          </span>
        </div>
      </div>

      {/* Time comparison banner */}
      <div
        className="shrink-0 mx-5 mt-4 rounded-2xl border overflow-hidden"
        style={{ borderColor: `${pathColor}25` }}
      >
        <div className="grid grid-cols-2">
          {/* Traditional */}
          <div className="px-5 py-4 border-r border-[var(--dtx-code-border)] flex flex-col gap-1">
            <div className="flex items-center gap-1.5 mb-1">
              <Clock size={10} className="text-gray-600" />
              <span className="text-eyebrow uppercase font-bold tracking-widest text-gray-600">
                Traditional Dev
              </span>
            </div>
            <div className="text-display font-black text-gray-500 leading-none">
              {path?.buildTime ?? "4–8 wks"}
            </div>
            <div className="text-meta text-gray-700 mt-0.5">
              Design · Sprint planning · PR cycles · QA · Deploy
            </div>
          </div>
          {/* Hive */}
          <div className="px-5 py-4 flex flex-col gap-1" style={{ background: `${pathColor}06` }}>
            <div className="flex items-center gap-1.5 mb-1">
              <Zap size={10} style={{ color: pathColor }} />
              <span
                className="text-eyebrow uppercase font-bold tracking-widest"
                style={{ color: pathColor }}
              >
                Determinex Hive Mind
              </span>
            </div>
            <div className="text-display font-black leading-none" style={{ color: pathColor }}>
              {hiveTime}
            </div>
            <div className="text-meta text-gray-600 mt-0.5">
              {parsed.files.length} files · compiler-verified every step · no guessing
            </div>
          </div>
        </div>
        <div className="px-5 py-2 border-t border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)]/40 flex items-center justify-center">
          <span className="text-meta text-gray-600">
            Each step is a compiler-validated sprint — not a guess
          </span>
        </div>
      </div>

      {/* Scrollable breakdown */}
      <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 flex flex-col gap-4">
        {/* Goal */}
        {parsed.goal && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Target size={10} className="text-cyan-400" />
              <span className="text-eyebrow uppercase font-bold tracking-widest text-cyan-400/80">
                What it does
              </span>
            </div>
            <p
              className="text-body text-gray-300 leading-relaxed pl-4 border-l-2"
              style={{ borderColor: `${pathColor}40` }}
            >
              {parsed.goal}
            </p>
          </div>
        )}

        {/* Constraints */}
        {parsed.constraints.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Shield size={10} className="text-purple-400" />
              <span className="text-eyebrow uppercase font-bold tracking-widest text-purple-400/80">
                Constraints & requirements
              </span>
            </div>
            <div className="flex flex-col gap-1.5 pl-4">
              {parsed.constraints.map((c, i) => (
                <div key={i} className="flex items-start gap-2">
                  <ChevronRight size={9} className="text-gray-600 shrink-0 mt-0.5" />
                  <span className="text-label text-gray-400 leading-relaxed">{c}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Files */}
        {parsed.files.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <FileCode2 size={10} style={{ color: langColor }} />
              <span
                className="text-eyebrow uppercase font-bold tracking-widest"
                style={{ color: `${langColor}cc` }}
              >
                {parsed.files.length} files the Hive will build
              </span>
            </div>
            <div className="flex flex-col gap-1.5 pl-4">
              {parsed.files.map((f, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 rounded-lg px-2.5 py-1.5 border border-[var(--dtx-code-border)] bg-[var(--dtx-code-bg)]"
                >
                  <code
                    className="text-meta font-mono shrink-0 mt-0.5"
                    style={{ color: langColor }}
                  >
                    {f.name}
                  </code>
                  {f.purpose && (
                    <span className="text-meta text-gray-600 leading-relaxed">— {f.purpose}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Dependencies */}
        {parsed.dependencies.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Package size={10} className="text-sky-400" />
              <span className="text-eyebrow uppercase font-bold tracking-widest text-sky-400/80">
                Dependencies
              </span>
            </div>
            <div className="flex flex-wrap gap-2 pl-4">
              {parsed.dependencies.map((d, i) => (
                <div
                  key={i}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)]"
                >
                  <code className="text-meta font-mono text-sky-400">{d.name}</code>
                  {d.why && <span className="text-meta text-gray-600">— {d.why}</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* External services */}
        {path?.prerequisites && path.prerequisites.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Wrench size={10} className="text-amber-400" />
              <span className="text-eyebrow uppercase font-bold tracking-widest text-amber-400/80">
                Services to set up before deploying
              </span>
            </div>
            <div className="flex flex-col gap-1.5 pl-4">
              {path.prerequisites.map((prereq, i) => {
                const [name, ...rest] = prereq.split("—");
                return (
                  <div key={i} className="flex items-start gap-2">
                    <div className="w-1 h-1 rounded-full bg-amber-400/50 shrink-0 mt-[5px]" />
                    <span className="text-label">
                      <span className="font-bold text-gray-300">{name.trim()}</span>
                      {rest.length > 0 && (
                        <span className="text-gray-600"> — {rest.join("—").trim()}</span>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Bottom spacer so content clears the sticky footer */}
        <div className="h-2" />
      </div>

      {/* Sticky build CTA */}
      {onBuild && (
        <div className="shrink-0 border-t border-[var(--dtx-code-border)] px-5 py-4 bg-[var(--dtx-code-bg)] flex flex-col gap-2">
          <button
            onClick={onBuild}
            disabled={building}
            className="w-full py-3.5 text-body font-black uppercase tracking-widest rounded-2xl transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 flex items-center justify-center gap-2"
            style={{
              background: `${pathColor}18`,
              border: `1px solid ${pathColor}55`,
              color: pathColor,
              boxShadow: `0 0 28px ${pathColor}12`,
            }}
          >
            {building ? (
              <>
                <div
                  className="w-3.5 h-3.5 border-2 rounded-full border-t-transparent animate-spin"
                  style={{ borderColor: pathColor }}
                />{" "}
                Launching Hive Mind...
              </>
            ) : (
              <>
                <Zap size={14} /> Build It — Launch Hive Mind
              </>
            )}
          </button>
          <p className="text-meta text-gray-700 text-center">
            This is the high-level plan · once built, small details can be refined in the build loop
          </p>
        </div>
      )}
    </div>
  );
}
