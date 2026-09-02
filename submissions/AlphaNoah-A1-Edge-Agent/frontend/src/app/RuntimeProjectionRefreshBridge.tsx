import { useEffect, useRef } from "react";

import { useOptionalActivation } from "../features/activation";
import { useDigitalEmployees } from "../features/digital-employees";
import { usePulse, useWorkspace } from "../features/runtime";

/**
 * Activation is a write command, not a second UI state source.
 *
 * Once the command succeeds, refresh the read-only projections and let those
 * provider-owned snapshots drive Workspace, Pulse, and Digital Employees.
 */
export function RuntimeProjectionRefreshBridge() {
  const activation = useOptionalActivation();
  const workspace = useWorkspace();
  const pulse = usePulse();
  const employees = useDigitalEmployees();
  const lastSnapshotRef = useRef(activation?.snapshot ?? null);
  const snapshot = activation?.snapshot ?? null;

  useEffect(() => {
    if (!snapshot || snapshot === lastSnapshotRef.current) {
      return;
    }

    lastSnapshotRef.current = snapshot;
    workspace.refresh();
    pulse.refresh();
    employees.refresh();
  }, [employees, pulse, snapshot, workspace]);

  return null;
}
