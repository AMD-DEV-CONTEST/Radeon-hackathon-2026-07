"use client";

import { useState, useCallback } from "react";
import { ShieldCheck, ShieldOff, Lock, Loader2 } from "lucide-react";
import { toggleVanguardTelemetry } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// VANGUARD TOGGLE
// Self-contained opt-in control for AES-256-GCM local telemetry logging.
//
// Design principles:
//  • Default OFF — user must actively consent; no data is ever captured silently.
//  • Optimistic UI — the toggle state flips immediately on click, then is
//    confirmed (or rolled back) once the backend responds. This avoids the
//    jarring flicker of waiting for an IPC round-trip before showing feedback.
//  • Error recovery — if the IPC call fails the toggle snaps back to its
//    previous state and shows an inline error. No silent failures.
// ─────────────────────────────────────────────────────────────────────────────

interface VanguardToggleProps {
  /** Optional callback fired after a successful state change. */
  onStateChange?: (enabled: boolean) => void;
  /** Allow the consumer to set a custom label. */
  className?: string;
}

export function VanguardToggle({ onStateChange, className = "" }: VanguardToggleProps) {
  const [enabled, setEnabled] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleToggle = useCallback(async () => {
    if (pending) return;

    const desired = !enabled;
    // Optimistic update — flip immediately for snappy feel.
    setEnabled(desired);
    setError(null);
    setPending(true);

    try {
      const confirmed = await toggleVanguardTelemetry(desired);
      // Use the backend-confirmed value in case it diverges (e.g. race).
      setEnabled(confirmed);
      onStateChange?.(confirmed);
    } catch (err) {
      // Roll back to previous state on failure.
      setEnabled(!desired);
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Backend error: ${msg}`);
    } finally {
      setPending(false);
    }
  }, [enabled, pending, onStateChange]);

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      <button
        id="vanguard-telemetry-toggle"
        aria-pressed={enabled}
        aria-label="Toggle Vanguard encrypted telemetry logging"
        onClick={handleToggle}
        disabled={pending}
        className="group flex items-center gap-3 w-full px-4 py-3 rounded-xl border transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-black disabled:opacity-60"
        style={{
          borderColor: enabled ? "rgba(34,197,94,0.45)" : "rgba(75,85,99,0.5)",
          background: enabled ? "rgba(34,197,94,0.07)" : "rgba(17,24,39,0.6)",
          boxShadow: enabled
            ? "0 0 18px rgba(34,197,94,0.15), inset 0 0 12px rgba(34,197,94,0.05)"
            : "none",
        }}
      >
        {/* Icon */}
        <div
          className="shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-300"
          style={{
            background: enabled ? "rgba(34,197,94,0.15)" : "rgba(75,85,99,0.15)",
          }}
        >
          {pending ? (
            <Loader2 size={15} className="animate-spin text-gray-400" />
          ) : enabled ? (
            <ShieldCheck
              size={15}
              className="text-green-400"
              style={{ filter: "drop-shadow(0 0 6px rgba(34,197,94,0.8))" }}
            />
          ) : (
            <ShieldOff size={15} className="text-gray-500" />
          )}
        </div>

        {/* Label block */}
        <div className="flex-1 text-left">
          <p
            className="text-meta font-black tracking-widest uppercase font-mono transition-colors duration-300"
            style={{ color: enabled ? "var(--dtx-ok)" : "var(--dtx-code-muted)" }}
          >
            Vanguard Telemetry
          </p>
          <p className="text-meta text-gray-500 font-mono mt-0.5 leading-relaxed">
            {enabled
              ? "Local AES-256-GCM · Data never leaves device"
              : "Off — no training data captured"}
          </p>
        </div>

        {/* Lock icon + pill toggle */}
        <div className="flex items-center gap-2 shrink-0">
          <Lock
            size={10}
            className="transition-colors duration-300"
            style={{ color: enabled ? "var(--dtx-ok)" : "var(--dtx-code-border)" }}
          />
          {/* Pill */}
          <div
            className="relative w-9 h-5 rounded-full transition-all duration-300"
            style={{
              background: enabled ? "var(--dtx-ok)" : "var(--dtx-code-raised)",
              border: `1px solid ${enabled ? "rgba(34,197,94,0.6)" : "rgba(75,85,99,0.4)"}`,
            }}
          >
            <div
              className="absolute top-0.5 w-4 h-4 rounded-full shadow-md transition-all duration-300"
              style={{
                left: enabled ? "calc(100% - 1.1rem)" : "2px",
                background: enabled ? "var(--dtx-ok)" : "var(--dtx-code-border)",
                boxShadow: enabled ? "0 0 8px rgba(34,197,94,0.7)" : "none",
              }}
            />
          </div>
        </div>
      </button>

      {/* Error feedback */}
      {error && (
        <p className="text-meta text-red-400/80 font-mono px-1 leading-relaxed">⚠ {error}</p>
      )}

      {/* Consent notice — only visible when enabled */}
      {enabled && !error && (
        <p className="text-meta text-green-500/40 font-mono px-1 leading-relaxed">
          Encrypted pairs are written to{" "}
          <span className="text-green-500/60">.determinex_staging/outbox/</span>. Your vault key
          lives at <span className="text-green-500/60">.determinex_staging/vault/vault.key</span>.
        </p>
      )}
    </div>
  );
}
