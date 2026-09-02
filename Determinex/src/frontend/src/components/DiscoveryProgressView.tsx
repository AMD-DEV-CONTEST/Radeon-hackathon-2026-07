"use client";

import React from "react";
import { Clock, Layers, Wrench, MessageSquare } from "lucide-react";
import { PathInfo } from "@/components/ConceptLab";
import { PathWireframe } from "@/components/PathWireframe";

// The five things Oracle always asks, in order
const ORACLE_CHECKLIST = [
  { key: "platform", label: "Platform", hint: "Web / iOS / Android / desktop / CLI / API-only" },
  { key: "actions", label: "Core Actions", hint: "What users actually DO in this app" },
  { key: "stack", label: "Stack", hint: "Language, framework, or optimization target" },
  {
    key: "constraints",
    label: "Constraints",
    hint: "Auth, real-time, offline, payments, specific APIs",
  },
  { key: "scale", label: "Scale", hint: "Personal tool / team / public product / user count" },
];

interface DiscoveryProgressViewProps {
  path: PathInfo;
  /** How many of the 5 Oracle questions have been answered (0-5) */
  answeredCount: number;
  /** Primary color extracted from user-attached image — tints the wireframe */
  colorOverride?: string;
}

export function DiscoveryProgressView({
  path,
  answeredCount,
  colorOverride,
}: DiscoveryProgressViewProps) {
  const complexityColor =
    path.complexity === "low"
      ? "var(--dtx-ok)"
      : path.complexity === "medium"
        ? "var(--dtx-warn)"
        : "var(--dtx-fail)";

  const progress = Math.min(answeredCount, 5) / 5;

  return (
    <div className="flex flex-col h-full bg-[var(--dtx-code-bg)] text-gray-300 overflow-hidden">
      {/* Header strip */}
      <div className="shrink-0 px-6 py-3 border-b border-[var(--dtx-code-border)] bg-[var(--dtx-code-panel)]/60 flex items-center gap-3">
        <div className="w-2 h-2 rounded-full animate-pulse" style={{ background: path.color }} />
        <div className="flex-1 min-w-0">
          <span className="text-body font-black truncate" style={{ color: path.color }}>
            {path.name}
          </span>
          <span className="text-label text-gray-600 ml-2 font-mono">{path.stack}</span>
        </div>
        <span
          className="text-meta px-2 py-0.5 rounded-full font-bold shrink-0"
          style={{
            color: complexityColor,
            background: `${complexityColor}15`,
            border: `1px solid ${complexityColor}35`,
          }}
        >
          {path.complexity}
        </span>
        <span className="text-meta text-gray-600 flex items-center gap-1 shrink-0 font-mono">
          <Clock size={9} /> {path.buildTime}
        </span>
      </div>

      {/* Wireframe — top half */}
      <div
        className="shrink-0 border-b border-[var(--dtx-code-border)] relative"
        style={{ height: "42%", background: `${path.color}04` }}
      >
        <PathWireframe path={path} colorOverride={colorOverride} />
        <div className="absolute bottom-2 inset-x-0 flex justify-center pointer-events-none">
          <span className="text-eyebrow uppercase tracking-[0.18em] text-gray-700 font-bold">
            Blueprint
          </span>
        </div>
      </div>

      {/* Oracle understanding checklist */}
      <div className="flex-1 min-h-0 overflow-y-auto p-5 flex flex-col gap-4">
        {/* Progress bar */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-1.5">
              <MessageSquare size={10} className="text-cyan-500" />
              <span className="text-eyebrow uppercase font-bold tracking-widest text-cyan-500/80">
                Oracle is building understanding
              </span>
            </div>
            <span className="text-meta font-mono text-gray-600">{answeredCount}/5 answered</span>
          </div>
          <div className="h-1 w-full rounded-full bg-gray-800 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${progress * 100}%`,
                background: `linear-gradient(90deg, ${path.color}80, ${path.color})`,
              }}
            />
          </div>
        </div>

        {/* Checklist */}
        <div className="flex flex-col gap-2">
          {ORACLE_CHECKLIST.map((item, i) => {
            const answered = i < answeredCount;
            const active = i === answeredCount;
            return (
              <div
                key={item.key}
                className="flex items-start gap-3 rounded-xl px-3 py-2.5 transition-all"
                style={{
                  background: answered
                    ? `${path.color}08`
                    : active
                      ? "var(--dtx-code-panel)"
                      : "transparent",
                  border: `1px solid ${answered ? path.color + "25" : active ? "var(--dtx-code-border)" : "transparent"}`,
                }}
              >
                {/* Status dot */}
                <div className="shrink-0 mt-0.5">
                  {answered ? (
                    <div
                      className="w-4 h-4 rounded-full flex items-center justify-center"
                      style={{ background: `${path.color}25`, border: `1px solid ${path.color}60` }}
                    >
                      <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                        <path
                          d="M1.5 4L3 5.5L6.5 2"
                          stroke={path.color}
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </div>
                  ) : active ? (
                    <div className="w-4 h-4 rounded-full border-2 border-cyan-400 border-t-transparent animate-spin" />
                  ) : (
                    <div className="w-4 h-4 rounded-full border border-gray-700" />
                  )}
                </div>
                {/* Label */}
                <div className="flex-1 min-w-0">
                  <div
                    className="text-label font-bold"
                    style={{
                      color: answered
                        ? path.color
                        : active
                          ? "var(--dtx-code-text)"
                          : "var(--dtx-code-border)",
                    }}
                  >
                    {item.label}
                  </div>
                  <div className="text-meta text-gray-600 leading-relaxed">{item.hint}</div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Stack + prerequisites */}
        {path.prerequisites && path.prerequisites.length > 0 && (
          <div className="rounded-xl border border-[var(--dtx-code-border)] p-3.5 mt-1">
            <div className="flex items-center gap-1.5 mb-2">
              <Wrench size={9} className="text-amber-400/70" />
              <span className="text-eyebrow uppercase font-bold tracking-widest text-amber-400/60">
                Services you&apos;ll set up
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              {path.prerequisites.map((prereq, i) => {
                const [name, ...rest] = prereq.split("—");
                return (
                  <div key={i} className="flex gap-2">
                    <div className="w-1 h-1 rounded-full bg-amber-400/40 shrink-0 mt-[5px]" />
                    <span className="text-meta">
                      <span className="text-gray-400 font-semibold">{name.trim()}</span>
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

        {/* Stack note */}
        <div className="flex items-start gap-2 opacity-60">
          <Layers size={9} className="text-gray-600 shrink-0 mt-0.5" />
          <span className="text-meta font-mono text-gray-600">{path.stack}</span>
        </div>
      </div>
    </div>
  );
}
