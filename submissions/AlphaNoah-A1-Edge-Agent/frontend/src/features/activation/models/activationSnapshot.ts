import type {
  ActionSummary,
  DataQuality,
  EventView,
  PulseNotice,
} from "../../runtime";
import type {
  CurrentTaskView,
  WorkRecord,
} from "../../digital-employees";

export type ActivationDisplayState =
  | "activating"
  | "working"
  | "approval_required"
  | "failed"
  | "inactive"
  | "unassigned";

export interface ActivationSnapshot {
  readonly source: "demo-http" | "mock";
  readonly eventId: string;
  readonly activeEmployeeId: string | null;
  readonly activeCapabilityId: null;
  readonly state: Exclude<ActivationDisplayState, "activating">;
  readonly event: EventView;
  readonly notice: PulseNotice;
  readonly action: ActionSummary;
  readonly employeeCurrentWork: CurrentTaskView | null;
  readonly workRecords: readonly WorkRecord[];
  readonly observedAt: string;
  readonly replayed: boolean;
  readonly quality: DataQuality;
}
