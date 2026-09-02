import type { ActionSummary } from "./actionSummary";
import type { EventView } from "./eventView";
import type { HealthView } from "./healthView";
import type { PulseNotice } from "./pulseNotice";
import type {
  DataQuality,
  PresentationSeverity,
  ViewText,
} from "./viewText";

export interface WorkspaceContextSignal {
  readonly id: string;
  readonly label: ViewText;
  readonly tone: PresentationSeverity | "success";
}

export interface CommandSuggestion {
  readonly id: string;
  readonly label: ViewText;
}

export interface WorkspaceSnapshot {
  readonly source: "mock" | "http";
  readonly site: {
    readonly id: string | null;
    readonly name: ViewText;
    readonly area: ViewText | null;
    readonly observationLabel: ViewText | null;
  };
  readonly health: HealthView;
  readonly contextSignals: readonly WorkspaceContextSignal[];
  readonly activeNotices: readonly PulseNotice[];
  readonly events: readonly EventView[];
  /**
   * Action summaries are ID-linked projections, not a Runtime relationship.
   * Keeping the collection preserves selection across multiple events.
   */
  readonly actionSummaries: readonly ActionSummary[];
  readonly currentFocus: ActionSummary | null;
  readonly commandSuggestions: readonly CommandSuggestion[];
  readonly observedAt: string | null;
  readonly quality: DataQuality;
}
