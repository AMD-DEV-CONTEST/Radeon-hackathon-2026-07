import { CircleAlert, LoaderCircle, Server, ShieldCheck } from "lucide-react";

import type { ApiState } from "../lib/types";

interface RuntimeStatusProps {
  state: ApiState;
  version?: string;
}

export function RuntimeStatus({ state, version }: RuntimeStatusProps) {
  const Icon = state === "ready" ? ShieldCheck : state === "offline" ? CircleAlert : LoaderCircle;
  const label = state === "ready" ? "Local API ready" : state === "offline" ? "Local API offline" : "Checking local API";

  return (
    <div className={`runtime-status runtime-status--${state}`} role="status">
      <Server size={15} aria-hidden="true" />
      <span className="runtime-status__copy">
        <strong>{label}</strong>
        <small>{state === "ready" ? `Local inference${version ? ` / v${version}` : ""}` : "No public fallback"}</small>
      </span>
      <Icon className={state === "checking" ? "spin" : undefined} size={15} aria-hidden="true" />
    </div>
  );
}
