"use client";
import React, { useEffect } from "react";
import { PolicyBlockOverlay, usePolicyBlock } from "./PolicyBlockOverlay";
import { subscribePolicyBlock } from "@/lib/policy-block-bus";

/**
 * Mounts the policy-gate-block overlay once, app-wide. Any code path that
 * calls emitPolicyBlock() (lib/policy-block-bus.ts) — currently the
 * AEGIS FS jail's SecurityPanic|PathTraversalBlocked telemetry event, see
 * useMoaTelemetry.ts — pops this overlay regardless of which panel triggered it.
 */
export function PolicyBlockProvider({ children }: { children: React.ReactNode }) {
  const { state, show, hide } = usePolicyBlock();

  useEffect(() => {
    return subscribePolicyBlock((gate, requestedAction) => show(gate, requestedAction));
  }, [show]);

  return (
    <>
      {children}
      <PolicyBlockOverlay
        visible={state.visible}
        gate={state.gate}
        requestedAction={state.requestedAction}
        onAcknowledge={hide}
      />
    </>
  );
}
