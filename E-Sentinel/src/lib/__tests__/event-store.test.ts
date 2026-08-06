import { supabaseAdmin } from "@/lib/supabase";
import { ingestEvidenceEvent } from "../governance/event-store";

jest.mock("@/lib/supabase", () => ({
  supabaseAdmin: { from: jest.fn() },
}));

const mockFrom = supabaseAdmin!.from as unknown as jest.Mock;
const mockInsert = jest.fn();

const event = {
  specversion: "1.0" as const,
  id: "event-001",
  source: "mock/commerce",
  type: "commerce.event.v1",
  time: "2026-07-23T00:00:00.000Z",
  tenant_id: "tenant-a",
  datacontenttype: "application/json",
  schema_ref: "schemas/events/evidence-event-v1.json",
  data: { value: 1 },
};

describe("EvidenceEventStore", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFrom.mockReturnValue({ insert: mockInsert });
  });

  it("accepts a newly persisted canonical event", async () => {
    mockInsert.mockResolvedValue({ error: null });

    await expect(ingestEvidenceEvent(event)).resolves.toEqual({
      status: "accepted",
      event_id: "event-001",
    });
    expect(mockFrom).toHaveBeenCalledWith("evidence_events");
    expect(mockInsert).toHaveBeenCalledWith(expect.objectContaining({
      idempotency_key: "mock/commerce:event-001",
      source: "mock/commerce",
    }));
  });

  it("turns a source-scoped unique conflict into an idempotent duplicate", async () => {
    mockInsert.mockResolvedValue({
      error: { code: "23505", message: "duplicate key" },
    });

    await expect(ingestEvidenceEvent(event)).resolves.toEqual({
      status: "duplicate",
      event_id: "event-001",
    });
  });
});
