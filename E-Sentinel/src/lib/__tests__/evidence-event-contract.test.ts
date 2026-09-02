import { readFileSync } from "node:fs";
import { join } from "node:path";
import { toDatabaseRow } from "../governance/event-store";
import { validateEvidenceEvent } from "../governance/evidence-event";

jest.mock("@/lib/supabase", () => ({ supabaseAdmin: null }));

describe("EvidenceEvent v1 contract", () => {
  const canonicalEvent = {
    specversion: "1.0",
    id: "event-001",
    source: "mock/commerce",
    type: "commerce.conversation.message.received.v1",
    time: "2026-07-23T00:00:00.000Z",
    tenant_id: "tenant-a",
    team_id: "team-a",
    subject: "conversation/123",
    traceparent: "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    datacontenttype: "application/json",
    schema_ref: "schemas/events/evidence-event-v1.json",
    data: { message_id: "msg-001" },
  };

  it("keeps the checked-in JSON Schema aligned with the canonical envelope", () => {
    const schema = JSON.parse(readFileSync(
      join(process.cwd(), "schemas/events/evidence-event-v1.json"),
      "utf8",
    )) as { $schema: string; required: string[]; properties: Record<string, unknown> };

    expect(schema.$schema).toBe("https://json-schema.org/draft/2020-12/schema");
    expect(schema.required).toEqual(expect.arrayContaining([
      "specversion", "id", "source", "type", "time", "tenant_id", "data",
    ]));
    expect(schema.properties.specversion).toEqual({ const: "1.0" });
  });

  it("normalizes canonical events and builds a source-scoped idempotency key", () => {
    const event = validateEvidenceEvent(canonicalEvent);
    const row = toDatabaseRow(event);

    expect(event.id).toBe("event-001");
    expect(event.event_id).toBe("event-001");
    expect(event.type).toBe(canonicalEvent.type);
    expect(event.idempotency_key).toBe("mock/commerce:event-001");
    expect(row).toMatchObject({
      idempotency_key: "mock/commerce:event-001",
      subject: "conversation/123",
      traceparent: canonicalEvent.traceparent,
      schema_ref: "schemas/events/evidence-event-v1.json",
      data: { message_id: "msg-001" },
    });
  });

  it("rejects malformed trace context and unsupported schema references", () => {
    expect(() => validateEvidenceEvent({ ...canonicalEvent, traceparent: "invalid" }))
      .toThrow("traceparent");
    expect(() => validateEvidenceEvent({ ...canonicalEvent, schema_ref: "schemas/events/v2.json" }))
      .toThrow("schema_ref");
  });

  it("continues to accept the legacy quality-loop field names", () => {
    const event = validateEvidenceEvent({
      event_id: "legacy-001",
      tenant_id: "tenant-a",
      source: "qa-system",
      event_type: "quality.evaluation.completed",
      occurred_at: "2026-07-23T00:00:00.000Z",
      actor: { id: "qa-system", type: "system" },
      payload: { report_id: "report-001" },
    });

    expect(event.data).toEqual({ report_id: "report-001" });
    expect(event.type).toBe("quality.evaluation.completed");
  });
});
