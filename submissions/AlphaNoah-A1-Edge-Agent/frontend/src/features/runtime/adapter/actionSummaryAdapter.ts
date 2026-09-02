import type {
  ActionSummary,
  ViewText,
} from "../models";
import { mapSeverity } from "./statusMapping";

export interface ActionSummaryAdapterInput {
  readonly id: string;
  readonly eventId: string;
  readonly heading: ViewText;
  readonly facts: readonly ViewText[];
  readonly aiUnderstanding: ViewText | null;
  readonly rawSeverity: string | null;
  readonly riskExplanation: ViewText | null;
  readonly suggestedAction: ViewText | null;
  readonly humanDecision: ViewText | null;
  readonly decision: ActionSummary["decision"];
  readonly task: ActionSummary["task"];
  readonly evidenceStatus: string | null;
  readonly timeline: ActionSummary["timeline"];
  readonly unknownFields?: readonly string[];
}

export function adaptActionSummary(
  input: ActionSummaryAdapterInput,
): ActionSummary {
  const severity = mapSeverity(input.rawSeverity);
  const warnings = severity.contractWarning
    ? [severity.contractWarning]
    : [];
  const unknownFields = input.unknownFields ?? [];

  return {
    id: input.id,
    eventId: input.eventId,
    heading: input.heading,
    facts: input.facts,
    aiUnderstanding: input.aiUnderstanding,
    risk: {
      severity: severity.severity,
      rawSeverity: severity.rawSeverity,
      explanation: input.riskExplanation,
    },
    suggestedAction: input.suggestedAction,
    humanDecision: input.humanDecision,
    decision: input.decision,
    task: input.task,
    evidenceStatus: input.evidenceStatus,
    timeline: [...input.timeline].sort(
      (left, right) => left.sequence - right.sequence,
    ),
    quality: {
      availability:
        unknownFields.length > 0 || warnings.length > 0
          ? "partial"
          : "available",
      unknownFields,
      contractWarnings: warnings,
    },
  };
}
