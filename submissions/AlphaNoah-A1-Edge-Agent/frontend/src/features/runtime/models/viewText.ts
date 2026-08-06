export type ViewText =
  | {
      readonly kind: "literal";
      readonly value: string;
    }
  | {
      readonly kind: "message";
      readonly id: string;
    };

export type PresentationSeverity =
  | "info"
  | "attention"
  | "warning"
  | "critical";

export type DataAvailability =
  | "available"
  | "partial"
  | "unavailable";

export interface DataQuality {
  readonly availability: DataAvailability;
  readonly unknownFields: readonly string[];
  readonly contractWarnings: readonly string[];
}

export const availableDataQuality: DataQuality = {
  availability: "available",
  unknownFields: [],
  contractWarnings: [],
};

export function literalText(value: string): ViewText {
  return { kind: "literal", value };
}

export function messageText(id: string): ViewText {
  return { kind: "message", id };
}
