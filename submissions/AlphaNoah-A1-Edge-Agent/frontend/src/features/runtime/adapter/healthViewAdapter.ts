import type {
  HealthState,
  HealthView,
  ViewText,
} from "../models";

export interface HealthAdapterInput {
  readonly state: HealthState;
  readonly label: ViewText;
  readonly components: HealthView["components"];
  readonly observedAt: string | null;
  readonly unknownFields?: readonly string[];
}

export function adaptHealthView(
  input: HealthAdapterInput,
): HealthView {
  const unknownFields = input.unknownFields ?? [];
  return {
    state: input.state,
    label: input.label,
    components: input.components,
    observedAt: input.observedAt,
    quality: {
      availability:
        input.state === "unavailable"
          ? "unavailable"
          : unknownFields.length > 0
            ? "partial"
            : "available",
      unknownFields,
      contractWarnings: [],
    },
  };
}
