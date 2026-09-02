"use client";
import React, { useEffect, useState } from "react";

/**
 * PolicyBlockOverlay — the gate-stop animation.
 *
 * Pops over the UI when the user attempts an action that hits one of Determinex's
 * policy or authority gates (mutation without approval, training without
 * eligibility, promotion without a verifier, claim without a fixture, etc.).
 *
 * Design intent: playful but precise. A wagging finger glyph and an
 * "Ah-ah-ah." callout get the user's attention; the body cites the *exact*
 * named gate and the concrete rung required to pass. This makes a block
 * informative, not just annoying.
 *
 * Voice is Determinex-native. The component does not name or imitate any
 * copyrighted character — the finger-wag and "Ah-ah-ah" are generic
 * exclamations of friendly disapproval.
 */

export type PolicyGate =
  | "AUTHORITY_REQUIRED"
  | "VERIFIER_REQUIRED"
  | "CONCRETE_FIXTURE_REQUIRED"
  | "TRAINING_ELIGIBILITY_FALSE"
  | "RELEASE_SUPPORTED_ZERO"
  | "SOURCE_MUTATION_LOCKED"
  | "REAL_USER_REPO_MUTATION_NOT_AUTHORIZED"
  | "PROOF_REQUIRED"
  | "BROAD_CLAIMS_FORBIDDEN"
  | "LANGUAGE_NOT_SUPPORTED"
  | "PLATFORM_NOT_SUPPORTED"
  | "UNIVERSAL_SUPPORT_NOT_CLAIMED"
  | "PATH_TRAVERSAL_BLOCKED"
  | "UNKNOWN_GATE";

interface GateContent {
  callout: string;
  body: string;
  rungs: string[];
}

/**
 * Determinex-native messages keyed by gate name. Each picks a different policy
 * rung from the actual deficiency-decomposition audit vocabulary. None of
 * these strings name a copyrighted character or line; the "Ah-ah-ah." is
 * a generic interjection.
 */
const GATE_CONTENT: Record<PolicyGate, GateContent> = {
  AUTHORITY_REQUIRED: {
    callout: "Ah-ah-ah. That needs authority that hasn't been granted.",
    body: "Authority gates remain false-by-default until an operator promotes them through a named lock.",
    rungs: [
      "pass through an explicit authority gate",
      "record the operator approval",
      "re-attempt with the new authority",
    ],
  },
  VERIFIER_REQUIRED: {
    callout: "Ah-ah-ah. The verifier hasn't seen this yet.",
    body: "No-success-without-verifier is in force. The action needs a deterministic check before it can proceed.",
    rungs: [
      "select a verifier for this cell",
      "run the verifier locally",
      "produce evidence the verifier passed",
    ],
  },
  CONCRETE_FIXTURE_REQUIRED: {
    callout: "Ah-ah-ah. No fixture, no promotion.",
    body: "Unknown/novel cases route to CONCRETE_FIXTURE_REQUIRED. The action needs a concrete, deterministic fixture before it can advance.",
    rungs: [
      "define an exact fixture",
      "declare its deterministic expected behavior",
      "attach it to the request",
    ],
  },
  TRAINING_ELIGIBILITY_FALSE: {
    callout: "Ah-ah-ah. Training rows are not eligible here.",
    body: "Training eligibility is false. Evidence is not training-grade until an explicit eligibility gate flips.",
    rungs: [
      "check the training eligibility guard",
      "satisfy the eligibility criteria",
      "do not write training rows",
    ],
  },
  RELEASE_SUPPORTED_ZERO: {
    callout: "Ah-ah-ah. Zero cells are release-supported.",
    body: "release_supported_cells == 0. The action implies release support that has not been certified at any cell.",
    rungs: [
      "complete packaging + fresh-install proof",
      "run the per-cell release certification gate",
      "claim only the certified cells, not the family",
    ],
  },
  SOURCE_MUTATION_LOCKED: {
    callout: "Ah-ah-ah. Source mutation is locked.",
    body: "source_mutation_authorized is false. Determinex will not mutate source without an explicit per-cell authority gate.",
    rungs: [
      "request source mutation authority",
      "satisfy the approval signature binding",
      "re-attempt with the granted gate",
    ],
  },
  REAL_USER_REPO_MUTATION_NOT_AUTHORIZED: {
    callout: "Ah-ah-ah. Real-user repo mutation is not authorized.",
    body: "real_user_source_mutation_authorized is false. Real-user repos require their own authority gate.",
    rungs: [
      "pass the real-user mutation authority lock",
      "obtain operator approval",
      "re-attempt with the granted gate",
    ],
  },
  PROOF_REQUIRED: {
    callout: "Ah-ah-ah. No proof, no path.",
    body: "Proof-before-mutation is in force. The action must carry proof artifacts before it can take effect.",
    rungs: ["produce a proof record", "verify it against the gate", "attach it to the request"],
  },
  BROAD_CLAIMS_FORBIDDEN: {
    callout: "Ah-ah-ah. Broad claims are not granted.",
    body: "broad_claims_granted is false. Determinex will not assert universal coverage.",
    rungs: [
      "scope the claim to a specific cell",
      "cite the exact evidence",
      "leave unsupported cells visible as such",
    ],
  },
  LANGUAGE_NOT_SUPPORTED: {
    callout: "Ah-ah-ah. This language isn't on the supported map.",
    body: "Detection is not support. The language is recognized but no verifier portfolio entry yet exists.",
    rungs: [
      "check the detector matrix for the nearest supported cell",
      "wait for verifier portfolio expansion",
      "route through the unknown/novel intake",
    ],
  },
  PLATFORM_NOT_SUPPORTED: {
    callout: "Ah-ah-ah. This platform isn't on the supported map.",
    body: "The platform/runtime lacks a verifier portfolio entry or is hardware/provider gated.",
    rungs: [
      "check the platform/runtime coverage matrix",
      "satisfy the hardware/provider gate",
      "or route to an unsupported-request block",
    ],
  },
  UNIVERSAL_SUPPORT_NOT_CLAIMED: {
    callout: "Ah-ah-ah. Universal support is not claimed.",
    body: "Determinex does not claim all languages, all codebases, or all platforms. The action implies a claim Determinex will not make.",
    rungs: [
      "scope the action to a known supported cell",
      "or accept the block as 'roadmap, not claim'",
    ],
  },
  PATH_TRAVERSAL_BLOCKED: {
    callout: "Ah-ah-ah. That write tried to leave the sandbox.",
    body: "The AEGIS FS jail caught a generated write whose resolved path landed outside the workspace root and refused it before anything touched disk.",
    rungs: [
      "check files_affected for the offending path",
      "keep generated writes inside the session sandbox",
      "re-attempt with a path that resolves under the workspace",
    ],
  },
  UNKNOWN_GATE: {
    callout: "Ah-ah-ah. That gate's still closed.",
    body: "A policy gate stopped this action. The exact named gate could not be resolved at block time.",
    rungs: [
      "check the deficiency decomposition audit for the named gate",
      "satisfy its rungs",
      "re-attempt",
    ],
  },
};

export interface PolicyBlockOverlayProps {
  /** Whether the overlay is rendered. */
  visible: boolean;
  /** The named gate that triggered the block. Defaults to UNKNOWN_GATE. */
  gate?: PolicyGate;
  /** Optional human description of what the user attempted. */
  requestedAction?: string;
  /** Called when the user acknowledges the block (button or Escape). */
  onAcknowledge?: () => void;
  /** If true, the close button is hidden (the block must be dismissed by the gate logic). */
  modal?: boolean;
}

export function PolicyBlockOverlay({
  visible,
  gate = "UNKNOWN_GATE",
  requestedAction,
  onAcknowledge,
  modal = false,
}: PolicyBlockOverlayProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    if (visible) {
      // small delay so the entrance animation runs
      const id = window.setTimeout(() => setMounted(true), 10);
      return () => window.clearTimeout(id);
    }
    setMounted(false);
    return undefined;
  }, [visible]);

  useEffect(() => {
    if (!visible || modal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onAcknowledge?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, modal, onAcknowledge]);

  if (!visible) return null;

  const content = GATE_CONTENT[gate] ?? GATE_CONTENT.UNKNOWN_GATE;

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="policy-block-callout"
      aria-describedby="policy-block-body"
      className="fixed inset-0 z-[100] flex items-center justify-center"
      style={{
        background: "rgba(8,4,4,0.62)",
        backdropFilter: "blur(4px)",
        opacity: mounted ? 1 : 0,
        transition: "opacity 220ms ease-out",
      }}
      onClick={modal ? undefined : onAcknowledge}
    >
      <style>{POLICY_BLOCK_KEYFRAMES}</style>
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative max-w-md w-[92vw] rounded-2xl overflow-hidden"
        style={{
          background: "linear-gradient(180deg, #1a0c08 0%, #100604 100%)",
          border: "1px solid rgba(255,120,80,0.35)",
          boxShadow: "0 30px 80px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,120,80,0.18) inset",
          transform: mounted ? "scale(1) translateY(0)" : "scale(0.92) translateY(8px)",
          opacity: mounted ? 1 : 0,
          transition: "transform 260ms cubic-bezier(0.2, 0.9, 0.3, 1.15), opacity 240ms ease-out",
        }}
      >
        {/* Warning bar */}
        <div
          className="h-1 w-full"
          style={{
            background: "repeating-linear-gradient(45deg, #ffb648 0 10px, #1a0c08 10px 20px)",
            animation: "policy-block-stripe 1.2s linear infinite",
          }}
        />
        <div className="flex items-start gap-4 px-6 pt-5 pb-2">
          <FingerWag />
          <div className="flex-1 min-w-0">
            <p
              id="policy-block-callout"
              className="text-title font-bold tracking-tight"
              style={{ color: "#ffe1c8", textShadow: "0 0 12px rgba(255,160,80,0.35)" }}
            >
              {content.callout}
            </p>
            <p
              className="mt-0.5 text-meta font-mono uppercase tracking-widest"
              style={{ color: "#ff9a58" }}
            >
              gate: {gate}
            </p>
          </div>
        </div>
        <div
          id="policy-block-body"
          className="px-6 pb-4 pt-1 text-body leading-relaxed"
          style={{ color: "#f0d8c0" }}
        >
          {content.body}
          {requestedAction && (
            <p className="mt-3 text-label font-mono" style={{ color: "rgba(240,216,192,0.65)" }}>
              attempted: <span style={{ color: "#ffd0a8" }}>{requestedAction}</span>
            </p>
          )}
        </div>
        <div className="px-6 pb-5">
          <p
            className="text-meta uppercase tracking-widest mb-2"
            style={{ color: "rgba(255,200,160,0.55)" }}
          >
            to satisfy this gate
          </p>
          <ol className="space-y-1 text-body" style={{ color: "#f0d8c0" }}>
            {content.rungs.map((rung, i) => (
              <li key={i} className="flex gap-2">
                <span
                  className="inline-flex items-center justify-center w-4 h-4 rounded-full text-meta font-bold flex-shrink-0 mt-0.5"
                  style={{ background: "rgba(255,160,80,0.20)", color: "#ffb678" }}
                >
                  {i + 1}
                </span>
                <span>{rung}</span>
              </li>
            ))}
          </ol>
        </div>
        {!modal && (
          <div className="flex items-center justify-end gap-2 px-6 pb-5">
            <button
              type="button"
              onClick={onAcknowledge}
              className="px-3 py-1.5 text-body font-medium rounded-md transition-colors"
              style={{
                background: "rgba(255,160,80,0.14)",
                color: "#ffd0a8",
                border: "1px solid rgba(255,160,80,0.40)",
              }}
            >
              Acknowledge (Esc)
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function FingerWag() {
  return (
    <div
      aria-hidden="true"
      className="flex-shrink-0"
      style={{
        width: 44,
        height: 44,
        display: "grid",
        placeItems: "center",
      }}
    >
      <svg
        width="44"
        height="44"
        viewBox="0 0 44 44"
        style={{
          transformOrigin: "22px 38px",
          animation: "policy-finger-wag 0.62s ease-in-out infinite alternate",
        }}
      >
        {/* Stylized index-finger glyph: rounded rectangle + tip. Generic shape. */}
        <rect
          x="17"
          y="6"
          width="10"
          height="32"
          rx="5"
          fill="#ffd0a8"
          stroke="rgba(255,160,80,0.7)"
          strokeWidth="1.5"
        />
        <circle cx="22" cy="9" r="2.5" fill="#ffb678" />
        {/* Joint hints */}
        <line x1="17" y1="20" x2="27" y2="20" stroke="rgba(180,90,40,0.45)" strokeWidth="1" />
        <line x1="17" y1="28" x2="27" y2="28" stroke="rgba(180,90,40,0.45)" strokeWidth="1" />
      </svg>
    </div>
  );
}

const POLICY_BLOCK_KEYFRAMES = `
@keyframes policy-finger-wag {
  0%   { transform: rotate(-22deg); }
  100% { transform: rotate(22deg); }
}
@keyframes policy-block-stripe {
  0%   { background-position: 0 0; }
  100% { background-position: 28px 0; }
}
`;

/**
 * Imperative helper for trigger sites that prefer an event-style API.
 * Wire up a React state + this helper if you don't want to thread the
 * `visible` prop through every gate-checking ancestor.
 */
export function usePolicyBlock() {
  const [state, setState] = useState<{
    visible: boolean;
    gate?: PolicyGate;
    requestedAction?: string;
  }>({ visible: false });
  return {
    state,
    show: (gate: PolicyGate, requestedAction?: string) =>
      setState({ visible: true, gate, requestedAction }),
    hide: () => setState({ visible: false }),
  };
}
