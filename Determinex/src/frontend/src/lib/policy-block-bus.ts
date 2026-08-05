import type { PolicyGate } from "@/components/PolicyBlockOverlay";

// Plain module-level pub/sub so non-React code (lib/api.ts, the moa-telemetry
// listener) can raise a policy block without threading React context through
// every call site. PolicyBlockProvider is the sole subscriber in practice.
type Listener = (gate: PolicyGate, requestedAction?: string) => void;
const listeners = new Set<Listener>();

export function emitPolicyBlock(gate: PolicyGate, requestedAction?: string): void {
  listeners.forEach((fn) => fn(gate, requestedAction));
}

export function subscribePolicyBlock(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
