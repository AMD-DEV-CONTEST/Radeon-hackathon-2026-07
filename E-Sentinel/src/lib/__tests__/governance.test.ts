import {
  dataScopeForRole,
  isWithinDataScope,
  normalizeRole,
} from "../governance/roles";
import { validateEvidenceEvent } from "../governance/evidence-event";
import { isEnabled, setFlag, getFlag, listFlags } from "../governance/feature-flags";

jest.mock("@/lib/supabase", () => ({ supabaseAdmin: null }));

describe("governance roles", () => {
  it("maps legacy team_lead to operator without changing stored data", () => {
    expect(normalizeRole("team_lead")).toBe("operator");
    expect(dataScopeForRole("operator")).toBe("team");
  });

  it("defaults unknown roles to the least-privileged viewer", () => {
    expect(normalizeRole("unknown-role")).toBe("viewer");
  });

  it("enforces self and team scopes", () => {
    expect(isWithinDataScope(
      { dataScope: "self", userId: "u1", teamId: "t1", tenantId: "tenant-a" },
      { ownerId: "u1", teamId: "t1", tenantId: "tenant-a" },
    )).toBe(true);
    expect(isWithinDataScope(
      { dataScope: "team", userId: "u1", teamId: "t1", tenantId: "tenant-a" },
      { ownerId: "u2", teamId: "t2", tenantId: "tenant-a" },
    )).toBe(false);
  });
});

describe("EvidenceEvent validation", () => {
  const validEvent = {
    event_id: "feishu:evt-001",
    tenant_id: "tenant-a",
    team_id: "team-a",
    source: "feishu",
    event_type: "chat.message.received",
    occurred_at: "2026-07-23T00:00:00.000Z",
    actor: { id: "open_id", type: "user" as const },
    payload: { message_id: "msg-001" },
  };

  it("normalizes dates and generates a correlation id", () => {
    const event = validateEvidenceEvent(validEvent);
    expect(event.schema_version).toBe("1.0");
    expect(event.occurred_at).toBe("2026-07-23T00:00:00.000Z");
    expect(event.correlation_id).toMatch(/^evt_/);
  });

  it("rejects events without tenant or actor", () => {
    expect(() => validateEvidenceEvent({ ...validEvent, tenant_id: "" })).toThrow("tenant_id");
    expect(() => validateEvidenceEvent({ ...validEvent, actor: null })).toThrow("actor");
  });

  it("rejects unsupported schema versions and invalid dates", () => {
    expect(() => validateEvidenceEvent({ ...validEvent, schema_version: "2.0" })).toThrow("schema_version");
    expect(() => validateEvidenceEvent({ ...validEvent, occurred_at: "tomorrow" })).toThrow("ISO date");
  });

  it("keeps the payload as a structured object", () => {
    expect(validateEvidenceEvent({ ...validEvent, payload: undefined }).payload).toEqual({});
    expect(() => validateEvidenceEvent({ ...validEvent, payload: "raw-body" })).toThrow("payload");
  });
});

describe("Feature Flag (QAE-019 basic integration)", () => {
  it("returns built-in defaults for known keys when no config present (system-config fallback)", async () => {
    expect(await isEnabled("diagnosis.create-general-work-order")).toBe(true);
    expect(await isEnabled("events.shadow-mode")).toBe(false);
    expect(await isEnabled("non-existent-flag")).toBe(false);
  });

  it("isEnabled accepts context without error", async () => {
    const result = await isEnabled("events.shadow-mode", { tenantId: "tenant-1", teamId: "team-1" });
    expect(result).toBe(false);
  });

  it("setFlag returns false without supabase (test env)", async () => {
    const result = await setFlag({ key: "test-ff", enabled: true, defaultValue: false });
    expect(result).toBe(false);
  });

  it("getFlag returns null for unknown when no config", async () => {
    const flag = await getFlag("unknown-ff-key");
    expect(flag).toBeNull();
  });

  it("listFlags returns the documented defaults", async () => {
    const flags = await listFlags();
    expect(Array.isArray(flags)).toBe(true);
    expect(flags.some((f) => f.key === "events.shadow-mode")).toBe(true);
    expect(flags.some((f) => f.key === "diagnosis.create-general-work-order")).toBe(true);
  });
});
