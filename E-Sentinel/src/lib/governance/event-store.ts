import { supabaseAdmin } from "@/lib/supabase";
import { validateEvidenceEvent, type ValidatedEvidenceEvent } from "./evidence-event";

export type IngestResult =
  | { status: "accepted"; event_id: string }
  | { status: "duplicate"; event_id: string };

export async function ingestEvidenceEvent(input: unknown): Promise<IngestResult> {
  const event = validateEvidenceEvent(input);
  if (!supabaseAdmin) throw new Error("Supabase not configured");

  const row = toDatabaseRow(event);
  const { error } = await supabaseAdmin
    .from("evidence_events")
    .insert(row);

  if (!error) return { status: "accepted", event_id: event.event_id };
  if (error.code === "23505") return { status: "duplicate", event_id: event.event_id };
  throw new Error(`Evidence event insert failed: ${error.message}`);
}

export function toDatabaseRow(event: ValidatedEvidenceEvent): Record<string, unknown> {
  return {
    specversion: event.specversion,
    event_id: event.event_id,
    idempotency_key: event.idempotency_key,
    schema_version: event.schema_version,
    tenant_id: event.tenant_id,
    team_id: event.team_id || null,
    source: event.source,
    event_type: event.event_type,
    occurred_at: event.occurred_at,
    subject: event.subject,
    traceparent: event.traceparent,
    datacontenttype: event.datacontenttype,
    schema_ref: event.schema_ref,
    actor_id: event.actor.id,
    actor_type: event.actor.type,
    actor_name: event.actor.name || null,
    correlation_id: event.correlation_id,
    payload_ref: event.payload_ref || null,
    data: event.data,
    payload: event.payload,
  };
}
