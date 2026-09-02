import type { PulseNotice } from "../models";
import type { PulseResourceStatus } from "../pulse/pulseDataSource";
import { useOptionalPulseContext } from "../pulse/PulseProviderContext";
import {
  useOptionalWorkspaceContext,
} from "./WorkspaceProviderContext";

export interface PulseSelection {
  readonly currentNotice: PulseNotice | null;
  readonly notices: readonly PulseNotice[];
  readonly queueLength: number;
  readonly source: "mock" | "http";
  readonly status: PulseResourceStatus;
  readonly error: Error | null;
  refresh(): void;
}

export function usePulse(): PulseSelection {
  const pulse = useOptionalPulseContext();
  const workspace = useOptionalWorkspaceContext();

  if (pulse) {
    const notices = pulse.notice ? [pulse.notice] : [];
    return {
      currentNotice: pulse.notice,
      notices,
      queueLength: notices.length,
      source: pulse.source,
      status: pulse.status,
      error: pulse.error,
      refresh: pulse.refresh,
    };
  }

  if (!workspace) {
    throw new Error(
      "usePulse must be used inside PulseProvider or WorkspaceProvider.",
    );
  }

  const notices = workspace.data?.activeNotices ?? [];
  return {
    currentNotice: notices[0] ?? null,
    notices,
    queueLength: notices.length,
    source: workspace.source,
    status: workspace.status,
    error: workspace.error,
    refresh: workspace.refresh,
  };
}
