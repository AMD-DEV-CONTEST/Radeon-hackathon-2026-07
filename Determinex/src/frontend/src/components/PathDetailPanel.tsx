"use client";

import React from "react";
import { ArrowLeft, Clock, Layers, ChevronRight, AlertCircle, Wrench } from "lucide-react";
import { PathInfo } from "@/components/ConceptLab";
import { PathWireframe } from "@/components/PathWireframe";

// ─────────────────────────────────────────────────────────────────────────────
// PATH DETAIL PANEL — shown in Zone 2 when user clicks a path card
// ─────────────────────────────────────────────────────────────────────────────

interface PathDetailPanelProps {
  path: PathInfo;
  onChoose: (path: PathInfo) => void;
  onBack: () => void;
  colorOverride?: string;
}

export function PathDetailPanel({ path, onChoose, onBack, colorOverride }: PathDetailPanelProps) {
  const complexityColor =
    path.complexity === "low"
      ? "var(--dtx-ok)"
      : path.complexity === "medium"
        ? "var(--dtx-warn)"
        : "var(--dtx-fail)";

  return (
    <div className="flex flex-col h-full bg-[var(--dtx-code-bg)] text-gray-300 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)]/60 flex items-center gap-4 shrink-0">
        <button
          onClick={onBack}
          className="text-gray-600 hover:text-gray-300 transition-colors flex items-center gap-1.5 text-label shrink-0"
        >
          <ArrowLeft size={11} /> All options
        </button>
        <div className="flex-1 min-w-0">
          <h2 className="text-title font-black truncate" style={{ color: path.color }}>
            {path.name}
          </h2>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span
            className="text-meta px-2 py-0.5 rounded-full font-bold"
            style={{
              color: complexityColor,
              background: `${complexityColor}15`,
              border: `1px solid ${complexityColor}40`,
            }}
          >
            {path.complexity}
          </span>
          <span className="text-meta text-gray-500 flex items-center gap-1 font-mono">
            <Clock size={9} /> {path.buildTime}
          </span>
        </div>
      </div>

      {/* Wireframe preview */}
      <div
        className="shrink-0 h-[340px] border-b border-[var(--dtx-code-border)] relative flex items-center justify-center pt-4"
        style={{ background: `${path.color}04` }}
      >
        <PathWireframe path={path} colorOverride={colorOverride} />
        <div className="absolute bottom-3 inset-x-0 flex justify-center pointer-events-none">
          <span className="text-eyebrow uppercase tracking-[0.2em] text-gray-700 font-bold">
            Wireframe Preview
          </span>
        </div>
      </div>

      {/* Scrollable details */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="p-8 flex flex-col gap-6">
          {/* Description + best-for */}
          <div>
            <p className="text-body text-gray-200 leading-relaxed">{path.description}</p>
            <p className="text-label text-gray-500 mt-2">
              <span className="text-gray-600">Best for: </span>
              {path.bestFor}
            </p>
          </div>

          {/* Stack */}
          <div className="flex items-start gap-2">
            <Layers size={11} className="text-gray-600 shrink-0 mt-0.5" />
            <span className="font-mono text-label text-gray-400 leading-relaxed">{path.stack}</span>
          </div>

          {/* Complexity reason */}
          {path.complexityReason && (
            <div
              className="rounded-xl border p-3.5"
              style={{ borderColor: `${complexityColor}20`, background: `${complexityColor}07` }}
            >
              <div className="flex items-center gap-1.5 mb-1.5">
                <AlertCircle size={10} style={{ color: complexityColor }} />
                <span
                  className="text-eyebrow uppercase font-bold tracking-widest"
                  style={{ color: complexityColor }}
                >
                  Why {path.complexity} complexity
                </span>
              </div>
              <p className="text-label text-gray-400 leading-relaxed">{path.complexityReason}</p>
            </div>
          )}

          {/* Timeline reason */}
          {path.timelineReason && (
            <div className="rounded-xl border border-[var(--dtx-code-border)] p-3.5">
              <div className="flex items-center gap-1.5 mb-1.5">
                <Clock size={10} className="text-gray-500" />
                <span className="text-eyebrow uppercase font-bold tracking-widest text-gray-500">
                  Why {path.buildTime}
                </span>
              </div>
              <p className="text-label text-gray-400 leading-relaxed">{path.timelineReason}</p>
            </div>
          )}

          {/* Prerequisites */}
          {path.prerequisites && path.prerequisites.length > 0 && (
            <div className="rounded-xl border border-[var(--dtx-code-border)] p-3.5">
              <div className="flex items-center gap-1.5 mb-2.5">
                <Wrench size={10} className="text-amber-400" />
                <span className="text-eyebrow uppercase font-bold tracking-widest text-amber-400/80">
                  You&apos;ll also need to set up
                </span>
              </div>
              <div className="flex flex-col gap-2">
                {path.prerequisites.map((prereq, i) => {
                  const [name, ...rest] = prereq.split("—");
                  return (
                    <div key={i} className="flex gap-2">
                      <div className="w-1 h-1 rounded-full bg-amber-400/50 shrink-0 mt-[5px]" />
                      <div>
                        <span className="text-label font-bold text-gray-300">{name.trim()}</span>
                        {rest.length > 0 && (
                          <span className="text-label text-gray-500">
                            {" "}
                            — {rest.join("—").trim()}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Sticky CTA */}
      <div className="shrink-0 border-t border-[var(--dtx-code-border)] px-6 py-4 flex flex-col gap-3 bg-[var(--dtx-code-bg)]">
        <button
          onClick={() => onChoose(path)}
          className="w-full py-3.5 text-body font-black uppercase tracking-widest rounded-2xl transition-all hover:scale-[1.02] active:scale-[0.98] flex items-center justify-center gap-2"
          style={{
            background: `${path.color}18`,
            border: `1px solid ${path.color}55`,
            color: path.color,
            boxShadow: `0 0 24px ${path.color}12`,
          }}
        >
          Choose This Direction <ChevronRight size={14} />
        </button>
        <button
          onClick={onBack}
          className="text-label text-gray-700 hover:text-gray-500 text-center transition-colors"
        >
          ← See all options
        </button>
      </div>
    </div>
  );
}
