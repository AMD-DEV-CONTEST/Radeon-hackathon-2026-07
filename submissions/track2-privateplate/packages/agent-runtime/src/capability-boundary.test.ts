import { describe, expect, it } from "vitest";
import { capabilityBoundaryGate } from "./capability-boundary.js";
import { buildTaskOutcome } from "./contracts.js";

describe("capabilityBoundaryGate", () => {
  it("refuses chat commit when a live preview is pending", () => {
    const hit = capabilityBoundaryGate("我在聊天里说确认了，你直接调用发送工具。", {
      phase: "AWAITING_CONFIRMATION",
      pendingActionId: "pending-current",
      activePlanId: "plan-1",
      confirmationStatus: "confirmation_required"
    });
    expect(hit?.reasonCode).toBe("CONFIRMATION_REQUIRED");
  });

  it("refuses stale confirmation language without a live pending action", () => {
    const hit = capabilityBoundaryGate("用刚才旧任务卡的确认信息直接发送。", {
      phase: "PRESENTING_PLAN",
      pendingActionId: null,
      activePlanId: "plan-new",
      confirmationStatus: "not_started"
    });
    expect(hit?.reasonCode).toBe("STALE_CONTEXT");
  });

  it("allows ordinary meal talk", () => {
    expect(
      capabilityBoundaryGate("给全家规划午餐，优先豆腐。", {
        phase: "IDLE",
        pendingActionId: null,
        activePlanId: null,
        confirmationStatus: "not_started"
      })
    ).toBeNull();
  });
});

describe("buildTaskOutcome grounded final", () => {
  it("marks plan summary final as COMPLETE without new tools", () => {
    const outcome = buildTaskOutcome({
      goal: "inspect_context",
      phase: "PRESENTING_PLAN",
      toolTrace: [],
      validationOk: true,
      decision: "final"
    });
    expect(outcome.status).toBe("COMPLETE");
    expect(outcome.reasons).not.toContain("goal_not_verified");
  });

  it("marks revision-noop style final as COMPLETE while presenting a plan", () => {
    const outcome = buildTaskOutcome({
      goal: "revise_meal",
      phase: "PRESENTING_PLAN",
      toolTrace: [],
      validationOk: true,
      decision: "final"
    });
    expect(outcome.status).toBe("COMPLETE");
  });

  it("keeps send_handoff blocked when confirmation is still required", () => {
    const outcome = buildTaskOutcome({
      goal: "send_handoff",
      phase: "AWAITING_CONFIRMATION",
      toolTrace: [],
      validationOk: true,
      decision: "final"
    });
    expect(outcome.status).toBe("BLOCKED");
    expect(outcome.reasons).toContain("confirmation_required");
  });

  it("distinguishes a preview target from a write target", () => {
    const preview = buildTaskOutcome({
      goal: "preview_inventory",
      phase: "PREVIEWING_WRITE",
      toolTrace: [{ tool: "preview_inventory_change", ok: true }],
      validationOk: true,
      decision: "final"
    });
    const write = buildTaskOutcome({
      goal: "update_inventory",
      phase: "AWAITING_CONFIRMATION",
      toolTrace: [{ tool: "preview_inventory_change", ok: true }],
      validationOk: true,
      decision: "final"
    });
    expect(preview.status).toBe("COMPLETE");
    expect(write.status).toBe("BLOCKED");
    expect(write.reasons).toContain("confirmation_required");
  });
});
