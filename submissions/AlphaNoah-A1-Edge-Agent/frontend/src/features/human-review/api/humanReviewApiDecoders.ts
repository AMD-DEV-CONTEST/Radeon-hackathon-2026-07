import { HumanReviewError } from "../models/humanReview";

type JsonRecord = Record<string, unknown>;

export interface HumanReviewCommandDto {
  readonly event_id: string;
  readonly status: string;
  readonly human_review_id: string;
  readonly outcome: "APPROVED" | "REJECTED";
  readonly decision_id: string;
}

export function decodeHumanReviewCommand(
  value: unknown,
): HumanReviewCommandDto {
  const record = readRecord(value, "human_review");
  const outcome = readString(record, "outcome", "human_review");
  if (outcome !== "APPROVED" && outcome !== "REJECTED") {
    throw contractError(
      "human_review.outcome must be APPROVED or REJECTED",
    );
  }

  return {
    event_id: readString(record, "event_id", "human_review"),
    status: readString(record, "status", "human_review"),
    human_review_id: readString(
      record,
      "human_review_id",
      "human_review",
    ),
    outcome,
    decision_id: readString(
      record,
      "decision_id",
      "human_review",
    ),
  };
}

function readRecord(value: unknown, path: string): JsonRecord {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value)
  ) {
    throw contractError(`${path} must be an object`);
  }
  return value as JsonRecord;
}

function readString(
  record: JsonRecord,
  key: string,
  path: string,
): string {
  const value = record[key];
  if (typeof value !== "string" || value.length === 0) {
    throw contractError(`${path}.${key} must be a non-empty string`);
  }
  return value;
}

function contractError(message: string): HumanReviewError {
  return new HumanReviewError("contract", message);
}
