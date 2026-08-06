import {
  DEMO_ACTIVATION_PROJECTION_VERSION,
  type DemoActivationErrorDto,
  type DemoActivationResponseDto,
} from "./activationApiDtos";

export class ActivationContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ActivationContractError";
  }
}

export function decodeActivationResponse(
  value: unknown,
): DemoActivationResponseDto {
  const root = object(value, "activation response");
  if (
    root.projection_version !==
    DEMO_ACTIVATION_PROJECTION_VERSION
  ) {
    throw new ActivationContractError(
      "Unsupported activation projection version.",
    );
  }

  const event = object(root.event, "event");
  const responsibility = object(
    root.responsibility,
    "responsibility",
  );
  const quality = object(root.quality, "quality");
  const analysis =
    root.analysis === null
      ? null
      : decodeAnalysis(object(root.analysis, "analysis"));
  const notification =
    root.notification === null
      ? null
      : decodeNotification(
          object(root.notification, "notification"),
        );
  const humanReview =
    root.human_review === null
      ? null
      : decodeHumanReview(
          object(root.human_review, "human_review"),
        );

  literal(event.event_type, "device_not_shutdown", "event.event_type");
  literal(event.source, "demo_activation", "event.source");
  literal(event.asset_id, "A08-AIRCON", "event.asset_id");
  literal(
    event.location,
    "Restaurant-Private-Room-A08",
    "event.location",
  );

  const matchType = oneOf(
    responsibility.match_type,
    ["asset", "location", "event_type", "unassigned"] as const,
    "responsibility.match_type",
  );
  const availability = oneOf(
    quality.availability,
    ["available", "partial", "unavailable"] as const,
    "quality.availability",
  );

  return {
    projection_version: DEMO_ACTIVATION_PROJECTION_VERSION,
    replayed: boolean(root.replayed, "replayed"),
    event: {
      event_id: nonEmptyString(event.event_id, "event.event_id"),
      event_type: "device_not_shutdown",
      source: "demo_activation",
      timestamp: nonEmptyString(event.timestamp, "event.timestamp"),
      status: nonEmptyString(event.status, "event.status"),
      severity: nonEmptyString(event.severity, "event.severity"),
      asset_id: "A08-AIRCON",
      location: "Restaurant-Private-Room-A08",
      description: nonEmptyString(
        event.description,
        "event.description",
      ),
    },
    responsibility: {
      owner_id: nonEmptyString(
        responsibility.owner_id,
        "responsibility.owner_id",
      ),
      owner_name: nonEmptyString(
        responsibility.owner_name,
        "responsibility.owner_name",
      ),
      match_type: matchType,
      matched_key: string(
        responsibility.matched_key,
        "responsibility.matched_key",
      ),
    },
    analysis,
    notification,
    human_review: humanReview,
    work_records: array(root.work_records, "work_records").map(
      decodeWorkRecord,
    ),
    quality: {
      availability,
      unknown_fields: stringArray(
        quality.unknown_fields,
        "quality.unknown_fields",
      ),
      contract_warnings: stringArray(
        quality.contract_warnings,
        "quality.contract_warnings",
      ),
    },
  };
}

export function decodeActivationError(
  value: unknown,
): DemoActivationErrorDto | null {
  if (!isObject(value)) {
    return null;
  }
  if (
    typeof value.error_code !== "string" ||
    typeof value.message !== "string"
  ) {
    return null;
  }
  if (
    value.event_id !== undefined &&
    typeof value.event_id !== "string"
  ) {
    return null;
  }
  return {
    error_code: value.error_code,
    message: value.message,
    ...(value.event_id ? { event_id: value.event_id } : {}),
  };
}

function decodeAnalysis(value: Record<string, unknown>) {
  const confidence = number(value.confidence, "analysis.confidence");
  if (confidence < 0 || confidence > 1) {
    throw new ActivationContractError(
      "analysis.confidence must be between 0 and 1.",
    );
  }
  return {
    detected_issue: nonEmptyString(
      value.detected_issue,
      "analysis.detected_issue",
    ),
    reasoning_summary: nonEmptyString(
      value.reasoning_summary,
      "analysis.reasoning_summary",
    ),
    confidence,
    requires_human_review: boolean(
      value.requires_human_review,
      "analysis.requires_human_review",
    ),
    knowledge_sources: stringArray(
      value.knowledge_sources,
      "analysis.knowledge_sources",
    ),
  };
}

function decodeNotification(value: Record<string, unknown>) {
  return {
    notification_id: nonEmptyString(
      value.notification_id,
      "notification.notification_id",
    ),
    status: oneOf(
      value.status,
      ["CREATED", "DELIVERED", "FAILED"] as const,
      "notification.status",
    ),
    created_at: nonEmptyString(
      value.created_at,
      "notification.created_at",
    ),
  };
}

function decodeHumanReview(value: Record<string, unknown>) {
  const allowedActions = array(
    value.allowed_actions,
    "human_review.allowed_actions",
  ).map((action, index) =>
    oneOf(
      action,
      ["approve", "reject"] as const,
      `human_review.allowed_actions[${index}]`,
    ),
  );
  return {
    decision_id: nonEmptyString(
      value.decision_id,
      "human_review.decision_id",
    ),
    status: nonEmptyString(value.status, "human_review.status"),
    required: boolean(value.required, "human_review.required"),
    allowed_actions: allowedActions,
  };
}

function decodeWorkRecord(value: unknown, index: number) {
  const record = object(value, `work_records[${index}]`);
  if (record.task_id !== null) {
    throw new ActivationContractError(
      `work_records[${index}].task_id must be null at the activation boundary.`,
    );
  }
  const sequence = number(
    record.sequence,
    `work_records[${index}].sequence`,
  );
  if (!Number.isInteger(sequence) || sequence < 0) {
    throw new ActivationContractError(
      `work_records[${index}].sequence is invalid.`,
    );
  }
  return {
    id: nonEmptyString(record.id, `work_records[${index}].id`),
    sequence,
    occurred_at: nonEmptyString(
      record.occurred_at,
      `work_records[${index}].occurred_at`,
    ),
    kind: oneOf(
      record.kind,
      [
        "event_received",
        "responsibility_matched",
        "analysis",
        "knowledge_lookup",
        "human_review",
      ] as const,
      `work_records[${index}].kind`,
    ),
    title: nonEmptyString(
      record.title,
      `work_records[${index}].title`,
    ),
    event_id: nonEmptyString(
      record.event_id,
      `work_records[${index}].event_id`,
    ),
    task_id: null,
  };
}

function object(
  value: unknown,
  path: string,
): Record<string, unknown> {
  if (!isObject(value)) {
    throw new ActivationContractError(`${path} must be an object.`);
  }
  return value;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function array(value: unknown, path: string): readonly unknown[] {
  if (!Array.isArray(value)) {
    throw new ActivationContractError(`${path} must be an array.`);
  }
  return value;
}

function string(value: unknown, path: string): string {
  if (typeof value !== "string") {
    throw new ActivationContractError(`${path} must be a string.`);
  }
  return value;
}

function nonEmptyString(value: unknown, path: string): string {
  const result = string(value, path);
  if (!result.trim()) {
    throw new ActivationContractError(`${path} must not be empty.`);
  }
  return result;
}

function stringArray(value: unknown, path: string): readonly string[] {
  return array(value, path).map((item, index) =>
    string(item, `${path}[${index}]`),
  );
}

function boolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    throw new ActivationContractError(`${path} must be a boolean.`);
  }
  return value;
}

function number(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new ActivationContractError(`${path} must be a number.`);
  }
  return value;
}

function literal<T extends string>(
  value: unknown,
  expected: T,
  path: string,
): T {
  if (value !== expected) {
    throw new ActivationContractError(
      `${path} does not match the activation contract.`,
    );
  }
  return expected;
}

function oneOf<const T extends readonly string[]>(
  value: unknown,
  expected: T,
  path: string,
): T[number] {
  if (
    typeof value !== "string" ||
    !expected.includes(value as T[number])
  ) {
    throw new ActivationContractError(`${path} is invalid.`);
  }
  return value as T[number];
}
