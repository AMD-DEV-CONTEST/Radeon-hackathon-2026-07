"use client";

export type NetworkPolicyMode = "offline" | "cloaked" | "online";

export const NETWORK_POLICY_STORAGE_KEY = "determinex.networkPolicy";

export const NETWORK_POLICY_COPY: Record<
  NetworkPolicyMode,
  {
    label: string;
    shortLabel: string;
    summary: string;
    detail: string;
    badge: string;
  }
> = {
  offline: {
    label: "Offline / Local Only",
    shortLabel: "Offline",
    summary: "No internet use from the IDE.",
    detail:
      "Use local files, local tools, and local models only. API providers, web lookups, and connector calls should stay blocked.",
    badge: "Local only",
  },
  cloaked: {
    label: "Cloaked Internet",
    shortLabel: "Cloaked",
    summary: "Internet is allowed only through configured privacy gates.",
    detail:
      "Provider calls may run through Project Cloak, key vault, and explicit workspace boundaries. This is the default for normal IDE work.",
    badge: "Cloak gated",
  },
  online: {
    label: "Online / User Approved",
    shortLabel: "Online",
    summary: "The user allows internet-backed IDE features.",
    detail:
      "Cloud providers, docs, connectors, package metadata, and API-backed helpers may use the network when the active tool requests it.",
    badge: "Internet allowed",
  },
};

export function readStoredNetworkPolicy(): NetworkPolicyMode {
  if (typeof window === "undefined") return "cloaked";
  const stored = window.localStorage.getItem(NETWORK_POLICY_STORAGE_KEY);
  if (stored === "offline" || stored === "cloaked" || stored === "online") return stored;
  return "cloaked";
}

export function storeNetworkPolicy(mode: NetworkPolicyMode) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(NETWORK_POLICY_STORAGE_KEY, mode);
}

export const SETUP_COMPLETED_STORAGE_KEY = "determinex.setupCompleted";
export const SETUP_RERUN_EVENT = "determinex:setup-rerun";
// Fired once SetupWizard actually finishes -- lets other mount-time-gated UI
// (e.g. WorkspaceOnboarding) that ran its own "has setup completed?" check
// before the wizard was done re-check now, instead of only on next reload.
export const SETUP_COMPLETED_EVENT = "determinex:setup-completed";

export function hasCompletedSetup(): boolean {
  if (typeof window === "undefined") return true;
  return window.localStorage.getItem(SETUP_COMPLETED_STORAGE_KEY) === "true";
}

export function markSetupCompleted() {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SETUP_COMPLETED_STORAGE_KEY, "true");
  window.dispatchEvent(new Event(SETUP_COMPLETED_EVENT));
}

export function resetSetupCompleted() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(SETUP_COMPLETED_STORAGE_KEY);
}

export function requestSetupRerun() {
  if (typeof window === "undefined") return;
  resetSetupCompleted();
  window.dispatchEvent(new Event(SETUP_RERUN_EVENT));
}
