import type {
  DataQuality,
  PresentationSeverity,
  ViewText,
} from "./viewText";

export interface ActionSummary {
  readonly id: string;
  readonly eventId: string;
  readonly heading: ViewText;
  readonly facts: readonly ViewText[];
  readonly aiUnderstanding: ViewText | null;
  readonly risk: {
    readonly severity: PresentationSeverity;
    readonly rawSeverity: string | null;
    readonly explanation: ViewText | null;
  };
  readonly suggestedAction: ViewText | null;
  readonly humanDecision: ViewText | null;
  readonly decision: {
    readonly id: string;
    readonly status: string;
    readonly requiresHumanReview: boolean;
  } | null;
  readonly task: {
    readonly id: string;
    readonly status: string;
    readonly owner: ViewText | null;
  } | null;
  readonly evidenceStatus: string | null;
  readonly timeline: readonly {
    readonly sequence: number;
    readonly timestamp: string | null;
    readonly action: string;
    readonly entityType: string;
    readonly entityId: string;
    readonly status: string;
  }[];
  readonly quality: DataQuality;
}
