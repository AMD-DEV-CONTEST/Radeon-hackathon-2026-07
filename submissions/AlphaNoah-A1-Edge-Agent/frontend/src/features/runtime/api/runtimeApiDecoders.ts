import { RuntimeApiError } from "./runtimeApiErrors";
import type {
  RuntimeAnalysisDto,
  RuntimeApiErrorDto,
  RuntimeDigitalEmployeeProjectionDto,
  RuntimeEventDetailDto,
  RuntimeEventProjectionDto,
  RuntimeProjectionSeverityDto,
  RuntimeTaskDto,
  RuntimeTimelineEntryDto,
  RuntimeWorkspaceProjectionDto,
} from "./runtimeApiDtos";

type JsonRecord = Record<string, unknown>;

const eventIdPattern = /^event_[a-f0-9]{32}$/;
const projectionSeverities =
  new Set<RuntimeProjectionSeverityDto>([
    "UNKNOWN",
    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL",
  ]);

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
  if (typeof value !== "string") {
    throw contractError(`${path}.${key} must be a string`);
  }

  return value;
}

function readNullableString(
  record: JsonRecord,
  key: string,
  path: string,
): string | null {
  const value = record[key];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string") {
    throw contractError(`${path}.${key} must be a string or null`);
  }

  return value;
}

function readBoolean(
  record: JsonRecord,
  key: string,
  path: string,
): boolean {
  const value = record[key];
  if (typeof value !== "boolean") {
    throw contractError(`${path}.${key} must be a boolean`);
  }

  return value;
}

function readNumber(
  record: JsonRecord,
  key: string,
  path: string,
): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw contractError(`${path}.${key} must be a finite number`);
  }

  return value;
}

function readStringArray(
  record: JsonRecord,
  key: string,
  path: string,
): readonly string[] {
  const value = record[key];
  if (
    !Array.isArray(value) ||
    value.some((entry) => typeof entry !== "string")
  ) {
    throw contractError(`${path}.${key} must be a string array`);
  }

  return value as readonly string[];
}

function readArray(
  record: JsonRecord,
  key: string,
  path: string,
): readonly unknown[] {
  const value = record[key];
  if (!Array.isArray(value)) {
    throw contractError(`${path}.${key} must be an array`);
  }

  return value;
}

function readNonEmptyString(
  record: JsonRecord,
  key: string,
  path: string,
): string {
  const value = readString(record, key, path);
  if (value.length === 0) {
    throw contractError(`${path}.${key} must not be empty`);
  }

  return value;
}

function readEventId(
  record: JsonRecord,
  key: string,
  path: string,
): string {
  const value = readString(record, key, path);
  if (!eventIdPattern.test(value)) {
    throw contractError(`${path}.${key} must be a Runtime Event ID`);
  }

  return value;
}

function contractError(message: string): RuntimeApiError {
  return new RuntimeApiError({
    code: "INVALID_RESPONSE",
    message,
  });
}

function decodeAnalysis(
  value: unknown,
  path: string,
): RuntimeAnalysisDto {
  const record = readRecord(value, path);
  return {
    detected_issue: readString(record, "detected_issue", path),
    decision_type: readString(record, "decision_type", path),
    reasoning_summary: readString(record, "reasoning_summary", path),
    evidence: readStringArray(record, "evidence", path),
    model_or_rule: readString(record, "model_or_rule", path),
    confidence: readNumber(record, "confidence", path),
    requires_human_review: readBoolean(
      record,
      "requires_human_review",
      path,
    ),
    severity: readString(record, "severity", path),
  };
}

export function decodeRuntimeEventDetail(
  value: unknown,
): RuntimeEventDetailDto {
  const record = readRecord(value, "event");
  const analysisValue = record.analysis;
  const decisionValue = record.decision;

  let decision: RuntimeEventDetailDto["decision"] = null;
  if (decisionValue !== null) {
    const decisionRecord = readRecord(decisionValue, "event.decision");
    decision = {
      decision_id: readString(
        decisionRecord,
        "decision_id",
        "event.decision",
      ),
      status: readString(
        decisionRecord,
        "status",
        "event.decision",
      ),
      requires_human_review: readBoolean(
        decisionRecord,
        "requires_human_review",
        "event.decision",
      ),
    };
  }

  return {
    event_id: readString(record, "event_id", "event"),
    status: readString(record, "status", "event"),
    skill_id: readNullableString(record, "skill_id", "event"),
    skill_version: readNullableString(
      record,
      "skill_version",
      "event",
    ),
    analysis:
      analysisValue === null
        ? null
        : decodeAnalysis(analysisValue, "event.analysis"),
    decision,
  };
}

export function decodeRuntimeTask(value: unknown): RuntimeTaskDto {
  const record = readRecord(value, "task_response");
  const taskValue = record.task;
  let task: RuntimeTaskDto["task"] = null;

  if (taskValue !== null) {
    const taskRecord = readRecord(taskValue, "task_response.task");
    task = {
      task_id: readString(
        taskRecord,
        "task_id",
        "task_response.task",
      ),
      status: readString(
        taskRecord,
        "status",
        "task_response.task",
      ),
      owner: readString(
        taskRecord,
        "owner",
        "task_response.task",
      ),
    };
  }

  return {
    event_id: readString(
      record,
      "event_id",
      "task_response",
    ),
    task,
  };
}

export function decodeRuntimeTimeline(
  value: unknown,
): readonly RuntimeTimelineEntryDto[] {
  if (!Array.isArray(value)) {
    throw contractError("timeline must be an array");
  }

  return value.map((entry, index) => {
    const path = `timeline[${index}]`;
    const record = readRecord(entry, path);
    return {
      sequence: readNumber(record, "sequence", path),
      timestamp: readString(record, "timestamp", path),
      action: readString(record, "action", path),
      entity_type: readString(record, "entity_type", path),
      entity_id: readString(record, "entity_id", path),
      status: readString(record, "status", path),
    };
  });
}

export function decodeRuntimeApiError(
  value: unknown,
): RuntimeApiErrorDto {
  const record = readRecord(value, "error");
  return {
    error_code: readString(record, "error_code", "error"),
    message: readString(record, "message", "error"),
  };
}

export function decodeRuntimeWorkspaceProjection(
  value: unknown,
): RuntimeWorkspaceProjectionDto {
  const record = readRecord(value, "workspace");
  const version = readString(record, "version", "workspace");
  if (version !== "workspace-v1") {
    throw contractError(
      "workspace.version must equal workspace-v1",
    );
  }

  const eventsValue = readArray(record, "events", "workspace");
  if (eventsValue.length > 100) {
    throw contractError(
      "workspace.events must contain at most 100 items",
    );
  }

  const activeEventValue = record.active_event;
  const pulseValue = record.pulse;
  const employeesValue = readArray(
    record,
    "employees",
    "workspace",
  );

  return {
    version,
    events: eventsValue.map((event, index) =>
      decodeEventProjection(event, `workspace.events[${index}]`),
    ),
    active_event:
      activeEventValue === null
        ? null
        : decodeEventProjection(
            activeEventValue,
            "workspace.active_event",
          ),
    pulse:
      pulseValue === null
        ? null
        : decodePulseProjection(pulseValue),
    employees: employeesValue.map((employee, index) =>
      decodeDigitalEmployeeProjection(
        employee,
        `workspace.employees[${index}]`,
      ),
    ),
  };
}

function decodeEventProjection(
  value: unknown,
  path: string,
): RuntimeEventProjectionDto {
  const record = readRecord(value, path);
  const timestamp = readNonEmptyString(
    record,
    "timestamp",
    path,
  );
  if (timestamp.length > 200) {
    throw contractError(
      `${path}.timestamp must contain at most 200 characters`,
    );
  }

  const rawSeverity = readString(record, "severity", path);
  if (
    !projectionSeverities.has(
      rawSeverity as RuntimeProjectionSeverityDto,
    )
  ) {
    throw contractError(
      `${path}.severity is not a workspace-v1 severity`,
    );
  }

  const responsibilityValue = record.responsibility;
  let responsibility: RuntimeEventProjectionDto["responsibility"] =
    null;
  if (responsibilityValue !== null) {
    const responsibilityRecord = readRecord(
      responsibilityValue,
      `${path}.responsibility`,
    );
    responsibility = {
      id: readNonEmptyString(
        responsibilityRecord,
        "id",
        `${path}.responsibility`,
      ),
      name: readNonEmptyString(
        responsibilityRecord,
        "name",
        `${path}.responsibility`,
      ),
    };
  }

  return {
    id: readEventId(record, "id", path),
    type: readNonEmptyString(record, "type", path),
    status: readNonEmptyString(record, "status", path),
    timestamp,
    severity: rawSeverity as RuntimeProjectionSeverityDto,
    location: readBoundedString(record, "location", path, 200),
    asset_id: readBoundedString(record, "asset_id", path, 200),
    description: readBoundedString(
      record,
      "description",
      path,
      2_000,
    ),
    responsibility,
  };
}

function readBoundedString(
  record: JsonRecord,
  key: string,
  path: string,
  maximumLength: number,
): string {
  const value = readNonEmptyString(record, key, path);
  if (value.length > maximumLength) {
    throw contractError(
      `${path}.${key} must contain at most ${maximumLength} characters`,
    );
  }
  return value;
}

function decodePulseProjection(
  value: unknown,
): RuntimeWorkspaceProjectionDto["pulse"] {
  const path = "workspace.pulse";
  const record = readRecord(value, path);
  const level = readString(record, "level", path);
  if (level !== "attention" && level !== "critical") {
    throw contractError(
      "workspace.pulse.level must be attention or critical",
    );
  }

  return {
    level,
    title: readNonEmptyString(record, "title", path),
    event_id: readEventId(record, "event_id", path),
  };
}

function decodeDigitalEmployeeProjection(
  value: unknown,
  path: string,
): RuntimeDigitalEmployeeProjectionDto {
  const record = readRecord(value, path);
  const status = readString(record, "status", path);
  if (status !== "working" && status !== "unknown") {
    throw contractError(
      `${path}.status must be working or unknown`,
    );
  }

  const currentEventIdValue = record.current_event_id;
  let currentEventId: string | null = null;
  if (currentEventIdValue !== null) {
    currentEventId = readEventId(
      record,
      "current_event_id",
      path,
    );
  }

  const skillsValue = readArray(record, "skills", path);

  return {
    id: readNonEmptyString(record, "id", path),
    name: readNonEmptyString(record, "name", path),
    status,
    current_event_id: currentEventId,
    responsibility: readNonEmptyString(
      record,
      "responsibility",
      path,
    ),
    skills: skillsValue.map((skill, index) => {
      const skillPath = `${path}.skills[${index}]`;
      const skillRecord = readRecord(skill, skillPath);
      return {
        name: readNonEmptyString(
          skillRecord,
          "name",
          skillPath,
        ),
      };
    }),
  };
}
