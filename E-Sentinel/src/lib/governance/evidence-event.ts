import { createCorrelationId } from "@/lib/correlation";

export const EVIDENCE_EVENT_VERSION = "1.0" as const;
export const EVIDENCE_EVENT_SCHEMA_REF = "schemas/events/evidence-event-v1.json" as const;
export const EVIDENCE_EVENT_CONTENT_TYPE = "application/json" as const;

export interface EvidenceActor {
  id: string;
  type: "user" | "service" | "system";
  name?: string;
}

export interface EvidenceEventInput {
  // Canonical CloudEvents-style fields.
  specversion?: typeof EVIDENCE_EVENT_VERSION;
  id?: string;
  tenant_id: string;
  team_id?: string | null;
  source: string;
  type?: string;
  time?: string;
  subject?: string | null;
  traceparent?: string | null;
  datacontenttype?: string;
  schema_ref?: string;
  data?: Record<string, unknown>;
  actor?: EvidenceActor;

  // Legacy aliases kept for existing internal producers.
  event_id?: string;
  event_type?: string;
  occurred_at?: string;
  correlation_id?: string;
  payload_ref?: string | null;
  payload?: Record<string, unknown>;
  schema_version?: typeof EVIDENCE_EVENT_VERSION;
}

export interface ValidatedEvidenceEvent extends EvidenceEventInput {
  specversion: typeof EVIDENCE_EVENT_VERSION;
  id: string;
  type: string;
  time: string;
  subject: string | null;
  traceparent: string | null;
  datacontenttype: typeof EVIDENCE_EVENT_CONTENT_TYPE;
  schema_ref: typeof EVIDENCE_EVENT_SCHEMA_REF;
  data: Record<string, unknown>;
  idempotency_key: string;
  actor: EvidenceActor;
  correlation_id: string;
  // Normalized legacy aliases.
  event_id: string;
  event_type: string;
  occurred_at: string;
  schema_version: typeof EVIDENCE_EVENT_VERSION;
  payload: Record<string, unknown>;
}

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const TRACEPARENT_PATTERN = /^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function requiredText(value: unknown, field: string, maxLength = 128): string {
  if (typeof value !== "string" || !value.trim() || value.length > maxLength) {
    throw new Error(`${field} must be a non-empty string of at most ${maxLength} characters`);
  }
  return value.trim();
}

export function validateEvidenceEvent(input: unknown): ValidatedEvidenceEvent {
  if (!isRecord(input)) throw new Error("event must be an object");

  const isLegacyInput = input.event_id !== undefined || input.event_type !== undefined
    || input.occurred_at !== undefined || input.payload !== undefined;
  const isCanonicalInput = !isLegacyInput;
  const eventId = requiredText(input.id ?? input.event_id, input.id !== undefined ? "id" : "event_id");
  const tenantId = requiredText(input.tenant_id, "tenant_id");
  if (!ID_PATTERN.test(eventId)) throw new Error("id contains unsupported characters");

  const eventType = requiredText(input.type ?? input.event_type, input.type !== undefined ? "type" : "event_type");
  const occurredAt = requiredText(input.time ?? input.occurred_at, input.time !== undefined ? "time" : "occurred_at", 64);
  if (Number.isNaN(Date.parse(occurredAt))) throw new Error("time must be an ISO date");
  if (input.specversion !== undefined && input.specversion !== EVIDENCE_EVENT_VERSION) {
    throw new Error(`specversion must be ${EVIDENCE_EVENT_VERSION}`);
  }
  if (isCanonicalInput && input.specversion === undefined) {
    throw new Error("specversion must be provided");
  }
  if (input.schema_version !== undefined && input.schema_version !== EVIDENCE_EVENT_VERSION) {
    throw new Error(`schema_version must be ${EVIDENCE_EVENT_VERSION}`);
  }

  const rawTraceparent = input.traceparent == null ? null : requiredText(input.traceparent, "traceparent", 55);
  if (rawTraceparent && !TRACEPARENT_PATTERN.test(rawTraceparent)) {
    throw new Error("traceparent must be a W3C traceparent value");
  }

  if (input.actor === null || (isLegacyInput && input.actor === undefined)) {
    throw new Error("actor must be an object");
  }

  const actor = input.actor === undefined
    ? { id: requiredText(input.source, "source"), type: "service" as const }
    : input.actor;
  if (!isRecord(actor)) throw new Error("actor must be an object");
  const actorType = actor.type;
  if (actorType !== "user" && actorType !== "service" && actorType !== "system") {
    throw new Error("actor.type must be user, service, or system");
  }

  const rawData = input.data ?? input.payload;
  if (isCanonicalInput && input.data === undefined) throw new Error("data must be an object");
  if (rawData != null && !isRecord(rawData)) {
    throw new Error(`${input.data !== undefined ? "data" : "payload"} must be an object`);
  }
  const data = rawData || {};
  const subject = input.subject == null ? null : requiredText(input.subject, "subject", 256);
  const source = requiredText(input.source, "source");
  const schemaRef = input.schema_ref == null
    ? EVIDENCE_EVENT_SCHEMA_REF
    : requiredText(input.schema_ref, "schema_ref", 512);
  if (schemaRef !== EVIDENCE_EVENT_SCHEMA_REF) {
    throw new Error(`schema_ref must be ${EVIDENCE_EVENT_SCHEMA_REF}`);
  }
  if (isCanonicalInput && input.datacontenttype !== EVIDENCE_EVENT_CONTENT_TYPE) {
    throw new Error(`datacontenttype must be ${EVIDENCE_EVENT_CONTENT_TYPE}`);
  }
  if (isCanonicalInput && input.schema_ref !== EVIDENCE_EVENT_SCHEMA_REF) {
    throw new Error(`schema_ref must be ${EVIDENCE_EVENT_SCHEMA_REF}`);
  }
  const correlationId = input.correlation_id == null
    ? createCorrelationId("evt")
    : requiredText(input.correlation_id, "correlation_id");

  return {
    specversion: EVIDENCE_EVENT_VERSION,
    id: eventId,
    event_id: eventId,
    tenant_id: tenantId,
    team_id: input.team_id == null ? null : requiredText(input.team_id, "team_id"),
    source,
    type: eventType,
    event_type: eventType,
    time: new Date(occurredAt).toISOString(),
    occurred_at: new Date(occurredAt).toISOString(),
    subject,
    traceparent: rawTraceparent,
    datacontenttype: EVIDENCE_EVENT_CONTENT_TYPE,
    schema_ref: schemaRef,
    data,
    actor: {
      id: requiredText(actor.id, "actor.id"),
      type: actorType,
      ...(typeof actor.name === "string" && actor.name.trim() ? { name: actor.name.trim().slice(0, 128) } : {}),
    },
    idempotency_key: `${source}:${eventId}`,
    correlation_id: correlationId,
    payload_ref: input.payload_ref == null ? null : requiredText(input.payload_ref, "payload_ref", 512),
    payload: data,
    schema_version: EVIDENCE_EVENT_VERSION,
  };
}
