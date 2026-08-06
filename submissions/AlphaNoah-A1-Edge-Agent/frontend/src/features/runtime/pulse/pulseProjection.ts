import {
  literalText,
  messageText,
  type PulseNotice,
} from "../models";

const pulseKeys = new Set(["level", "title", "event_id"]);
const eventIdPattern = /^event_[a-f0-9]{32}$/;
const maxPublicTextLength = 200;

export interface RuntimePulseProjectionDto {
  readonly level: "attention" | "critical";
  readonly title: string;
  readonly event_id: string;
}

export class PulseContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PulseContractError";
  }
}

export function decodePulseProjection(
  value: unknown,
): RuntimePulseProjectionDto | null {
  if (value === null) {
    return null;
  }
  if (
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    throw new PulseContractError(
      "pulse must be an object or null.",
    );
  }

  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  if (
    keys.length !== pulseKeys.size ||
    keys.some((key) => !pulseKeys.has(key))
  ) {
    throw new PulseContractError(
      "pulse must contain only level, title, and event_id.",
    );
  }

  const level = readString(record, "level");
  if (level !== "attention" && level !== "critical") {
    throw new PulseContractError(
      "pulse.level must be attention or critical.",
    );
  }

  const title = readString(record, "title");
  if (
    title.length === 0 ||
    title.length > maxPublicTextLength
  ) {
    throw new PulseContractError(
      "pulse.title must contain between 1 and 200 characters.",
    );
  }

  const eventId = readString(record, "event_id");
  if (!eventIdPattern.test(eventId)) {
    throw new PulseContractError(
      "pulse.event_id must be a Runtime Event ID.",
    );
  }

  return {
    level,
    title,
    event_id: eventId,
  };
}

export function adaptPulseProjection(
  dto: RuntimePulseProjectionDto,
): PulseNotice {
  const isCritical = dto.level === "critical";

  return {
    id: `runtime-pulse-${dto.event_id}`,
    eventId: dto.event_id,
    // Level selection belongs to Notification Outbox Projection. Do not
    // inspect Event severity or status here.
    kind: dto.level,
    stateLabel: messageText(
      isCritical
        ? "severity.critical"
        : "pulse.state.attention",
    ),
    severity: isCritical ? "critical" : "attention",
    priority: isCritical ? 400 : 200,
    title: literalText(dto.title),
    summary: literalText(dto.title),
    facts: null,
    analysis: null,
    nextAction: null,
    requiresHumanAction: true,
    createdAt: null,
    runtimeStatus: "UNKNOWN",
    rawRuntimeStatus: "UNKNOWN",
    sourceNotificationStatus: null,
    quality: {
      availability: "partial",
      unknownFields: [
        "summary",
        "facts",
        "analysis",
        "next_action",
        "created_at",
        "runtime_status",
        "source_notification_status",
      ],
      contractWarnings: [],
    },
  };
}

function readString(
  record: Record<string, unknown>,
  key: string,
): string {
  const value = record[key];
  if (typeof value !== "string") {
    throw new PulseContractError(`pulse.${key} must be a string.`);
  }
  return value;
}
