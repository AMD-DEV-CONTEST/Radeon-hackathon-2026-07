import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "./service/privateplate-domain.js";

describe("agent checkpoint persistence", () => {
  let domain: PrivatePlateDomain | undefined;
  let temporaryDirectory: string;
  let databasePath: string;

  beforeEach(() => {
    temporaryDirectory = mkdtempSync(join(tmpdir(), "privateplate-checkpoint-"));
    databasePath = join(temporaryDirectory, "privateplate.sqlite");
  });

  afterEach(() => {
    domain?.close();
    rmSync(temporaryDirectory, { recursive: true, force: true });
  });

  it("keeps plans and checkpoints when a file database is reopened", async () => {
    domain = await PrivatePlateDomain.create(databasePath);
    const householdId = domain.householdId;
    const initial = domain.composeMeal({ sessionId: "session-persisted" });
    if (initial.status !== "valid") throw new Error("expected valid plan");

    const persistedState = {
      phase: "PRESENTING_PLAN",
      activePlanId: initial.plan.id,
      pendingActionId: null,
      dinerIds: initial.plan.dinerIds
    };
    domain.saveAgentCheckpoint("session-persisted", persistedState);
    domain.saveAgentCheckpoint("session-other", {
      phase: "IDLE",
      activePlanId: null
    });

    domain.close();
    domain = undefined;
    domain = await PrivatePlateDomain.create(databasePath);

    expect(domain.householdId).toBe(householdId);
    expect(domain.getActivePlan("session-persisted")?.id).toBe(initial.plan.id);
    expect(
      domain.loadAgentCheckpoint<typeof persistedState>("session-persisted")?.state
    ).toEqual(persistedState);

    const householdCount = domain.db
      .prepare(`SELECT COUNT(*) AS count FROM households`)
      .get() as { count: number };
    expect(Number(householdCount.count)).toBe(1);
    expect(domain.getMembers().length).toBeGreaterThan(0);

    expect(domain.deleteAgentCheckpoint("session-persisted")).toBe(true);
    expect(domain.loadAgentCheckpoint("session-persisted")).toBeNull();
    expect(domain.loadAgentCheckpoint("session-other")).not.toBeNull();
    expect(domain.getActivePlan("session-persisted")?.id).toBe(initial.plan.id);
    expect(domain.getMembers().length).toBeGreaterThan(0);
  });

  it("refuses to persist a plaintext confirmation token", async () => {
    domain = await PrivatePlateDomain.create(databasePath);

    expect(() =>
      domain!.saveAgentCheckpoint("session-unsafe", {
        phase: "AWAITING_CONFIRMATION",
        uiOnly: {
          confirmationToken: "plaintext-secret"
        }
      })
    ).toThrow("must not contain a plaintext confirmation token");

    expect(domain.loadAgentCheckpoint("session-unsafe")).toBeNull();
  });
});
