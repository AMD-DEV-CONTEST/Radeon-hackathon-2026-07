import type { RuntimeEventStatus } from "./eventView";
import type {
  DataQuality,
  PresentationSeverity,
  ViewText,
} from "./viewText";

export type PulseNoticeKind =
  | "informational"
  | "attention"
  | "approval_required"
  | "critical";

export interface PulseNotice {
  readonly id: string;
  readonly eventId: string;
  readonly kind: PulseNoticeKind;
  readonly stateLabel: ViewText;
  readonly severity: PresentationSeverity;
  readonly priority: number;
  readonly title: ViewText;
  readonly summary: ViewText;
  readonly facts: ViewText | null;
  readonly analysis: ViewText | null;
  readonly nextAction: ViewText | null;
  readonly requiresHumanAction: boolean;
  readonly createdAt: string | null;
  readonly runtimeStatus: RuntimeEventStatus | "UNKNOWN";
  readonly rawRuntimeStatus: string;
  readonly sourceNotificationStatus: string | null;
  readonly quality: DataQuality;
}
