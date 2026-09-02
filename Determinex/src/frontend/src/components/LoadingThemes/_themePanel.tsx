"use client";
import React from "react";

export interface RolePalette {
  oracle: string;
  architect: string;
  builder: string;
  compiler: string;
}

export interface ThemePanelProps {
  label: string;
  elapsedSeconds?: number;
  primary: string;
  dim: string;
  /** Optional palette for the four role nodes. Falls back to primary tint. */
  rolePalette?: Partial<RolePalette>;
  /** Optional small sub-label shown under the main label. */
  subLabel?: string;
  /** Optional accent character used between role chips ("->" by default). */
  arrow?: string;
  /** Shape of the role chip ("square", "diamond", "ring", default "ring"). */
  chipShape?: "square" | "diamond" | "ring";
}

const ROLES = ["Oracle", "Architect", "Builder", "Compiler"] as const;

export function ThemeOverlay({
  label,
  elapsedSeconds,
  primary,
  dim,
  rolePalette,
  subLabel,
  arrow = "->",
  chipShape = "ring",
}: ThemePanelProps) {
  const palette: RolePalette = {
    oracle: rolePalette?.oracle ?? primary,
    architect: rolePalette?.architect ?? primary,
    builder: rolePalette?.builder ?? primary,
    compiler: rolePalette?.compiler ?? primary,
  };
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
      <div className="flex flex-col items-center gap-2">
        <div className="relative">
          <div
            className="w-8 h-8 border-2 rounded-full animate-spin"
            style={{ borderColor: primary, borderTopColor: "transparent" }}
          />
          {elapsedSeconds !== undefined && elapsedSeconds > 0 && (
            <div className="absolute inset-0 flex items-center justify-center">
              <span
                className="text-meta font-mono font-bold tabular-nums leading-none"
                style={{ color: primary }}
              >
                {elapsedSeconds}s
              </span>
            </div>
          )}
        </div>
        <p
          className="text-body font-mono tracking-widest uppercase font-bold"
          style={{ color: primary, textShadow: `0 0 12px ${primary}55` }}
        >
          {label}
        </p>
        {subLabel && (
          <p className="text-label font-mono tracking-wide" style={{ color: dim }}>
            {subLabel}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3 mt-2">
        {ROLES.map((role, i, arr) => {
          const color = palette[role.toLowerCase() as keyof RolePalette];
          const isActive = i === 0;
          const shape =
            chipShape === "square"
              ? "rounded-none"
              : chipShape === "diamond"
                ? "rounded-none rotate-45"
                : "rounded-full";
          return (
            <React.Fragment key={role}>
              <div className="flex flex-col items-center gap-1">
                <div
                  className={`w-5 h-5 flex items-center justify-center ${shape}`}
                  style={{
                    background: `${color}${isActive ? "30" : "10"}`,
                    border: `1px solid ${color}${isActive ? "90" : "30"}`,
                    boxShadow: isActive ? `0 0 8px ${color}60` : "none",
                  }}
                >
                  <div
                    className={`w-1.5 h-1.5 ${chipShape === "diamond" ? "-rotate-45" : "rounded-full"}`}
                    style={{ background: color, opacity: isActive ? 1 : 0.3 }}
                  />
                </div>
                <span
                  className={`text-eyebrow font-mono uppercase tracking-wider ${chipShape === "diamond" ? "" : ""}`}
                  style={{ color, opacity: isActive ? 1 : 0.35 }}
                >
                  {role}
                </span>
                {isActive && elapsedSeconds !== undefined && elapsedSeconds > 0 && (
                  <span
                    className="text-meta font-mono font-bold tabular-nums"
                    style={{ color, opacity: 0.9 }}
                  >
                    {elapsedSeconds}s
                  </span>
                )}
              </div>
              {i < arr.length - 1 && (
                <span className="text-meta mb-4" style={{ color: dim }}>
                  {arrow}
                </span>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}

export function SmallPanel({ label, primary }: { label: string; primary: string }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
      <div
        className="w-5 h-5 border-2 rounded-full animate-spin"
        style={{ borderColor: primary, borderTopColor: "transparent" }}
      />
      <p className="text-meta font-mono tracking-widest uppercase" style={{ color: primary }}>
        {label}
      </p>
    </div>
  );
}
