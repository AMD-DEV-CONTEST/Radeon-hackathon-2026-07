import type { DataQuality, ViewText } from "./viewText";

export type HealthState =
  | "healthy"
  | "degraded"
  | "unavailable"
  | "unknown";

export interface HealthComponentView {
  readonly id: string;
  readonly label: ViewText;
  readonly value: ViewText;
  readonly state: HealthState;
}

export interface HealthView {
  readonly state: HealthState;
  readonly label: ViewText;
  readonly components: readonly HealthComponentView[];
  readonly observedAt: string | null;
  readonly quality: DataQuality;
}
