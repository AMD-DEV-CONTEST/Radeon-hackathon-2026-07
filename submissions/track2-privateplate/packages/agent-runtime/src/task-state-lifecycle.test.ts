import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import { PrivatePlateAgent } from "./graph.js";
import { ScriptedProductProvider } from "./model/scripted-provider.js";

describe("Agent confirmation lifecycle", () => {
  let domain: PrivatePlateDomain;

  beforeEach(async () => {
    domain = await PrivatePlateDomain.create(":memory:");
  });

  afterEach(() => {
    domain.close();
  });

  it("keeps preview pending across checkpoint restore and commits only once", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "task-state-lifecycle",
      new ScriptedProductProvider()
    );
    const preview = await agent.handleUserMessage(
      "刚买了两盒豆腐，帮我记入库"
    );

    expect(preview.phase).toBe("AWAITING_CONFIRMATION");
    expect(preview.taskOutcome.status).toBe("BLOCKED");
    expect(preview.taskOutcome.reasons).toContain("confirmation_required");
    expect(agent.getTaskState()).toMatchObject({
      status: "waiting_confirmation",
      workflowStage: "awaiting_confirm",
      pendingActionType: "inventory_restock"
    });
    expect(preview.uiOnly?.pendingActionId).toBeTruthy();

    const before = domain
      .getDayContext()
      .inventory.find((item) => item.foodId === "food-tofu")?.quantity.estimateG;
    const checkpoint = JSON.parse(JSON.stringify(agent.exportCheckpoint()));
    const restored = new PrivatePlateAgent(
      domain,
      "task-state-lifecycle",
      new ScriptedProductProvider()
    );
    restored.restoreState(checkpoint);

    expect(restored.getTaskState()).toMatchObject({
      status: "waiting_confirmation",
      workflowStage: "awaiting_confirm",
      pendingActionId: preview.uiOnly?.pendingActionId,
      pendingActionType: "inventory_restock"
    });

    const confirmation = preview.uiOnly!;
    const first = restored.confirmPending({
      pendingActionId: confirmation.pendingActionId,
      confirmationToken: confirmation.confirmationToken,
      idempotencyKey: "task-state-lifecycle-confirm",
      payloadHash: confirmation.payloadHash
    });
    expect(first.ok).toBe(true);
    if (!first.ok) return;
    expect(first.receipt.replayed).toBe(false);
    expect(restored.getTaskState()).toMatchObject({
      status: "completed",
      workflowStage: "completed",
      pendingActionId: null,
      pendingActionType: null
    });

    const afterFirst = domain
      .getDayContext()
      .inventory.find((item) => item.foodId === "food-tofu")?.quantity.estimateG;
    expect(afterFirst).toBeGreaterThan(before ?? 0);

    const replay = restored.confirmPending({
      pendingActionId: confirmation.pendingActionId,
      confirmationToken: confirmation.confirmationToken,
      idempotencyKey: "task-state-lifecycle-confirm",
      payloadHash: confirmation.payloadHash
    });
    expect(replay.ok).toBe(true);
    if (!replay.ok) return;
    expect(replay.receipt.replayed).toBe(true);
    const afterReplay = domain
      .getDayContext()
      .inventory.find((item) => item.foodId === "food-tofu")?.quantity.estimateG;
    expect(afterReplay).toBe(afterFirst);
  });

  it("lets a new RAG goal leave a blocked planning lifecycle", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "task-state-new-goal",
      new ScriptedProductProvider({
        turns: [
          [
            {
              kind: "tool",
              tool: "retrieve_local_knowledge",
              goal: "retrieve_guidance",
              rawArgs: { query: "晚餐准备规则", topK: 3 }
            },
            {
              kind: "final",
              goal: "retrieve_guidance",
              message: "已完成本地规则检索。"
            }
          ]
        ]
      })
    );
    agent.seedLastDomainFailure("NO_FEASIBLE_PLAN");

    const result = await agent.handleUserMessage("查一下晚餐准备规则");

    expect(result.toolTrace).toEqual([
      expect.objectContaining({
        tool: "retrieve_local_knowledge",
        ok: true
      })
    ]);
    expect(result.toolTrace.some((tool) => tool.code === "RISK_GUARD_TRIGGERED")).toBe(
      false
    );
    expect(agent.getTaskState()).toMatchObject({
      objective: "retrieve_guidance",
      status: "completed",
      workflowStage: "completed",
      candidateSetId: null,
      lastDomainFailureCode: null
    });
  });

  it("keeps a pending confirmation when a new read-only goal arrives", async () => {
    const agent = new PrivatePlateAgent(
      domain,
      "task-state-pending-new-goal",
      new ScriptedProductProvider({
        turns: [
          [
            {
              kind: "tool",
              tool: "preview_inventory_change",
              goal: "preview_inventory",
              rawArgs: {
                foodId: "food-tofu",
                quantity: 1,
                unit: "盒"
              }
            },
            {
              kind: "final",
              goal: "preview_inventory",
              message: "已生成库存预览，等待确认。"
            }
          ],
          [
            {
              kind: "tool",
              tool: "retrieve_local_knowledge",
              goal: "retrieve_guidance",
              rawArgs: { query: "晚餐准备规则", topK: 3 }
            },
            {
              kind: "final",
              goal: "retrieve_guidance",
              message: "已完成本地规则检索，库存预览仍等待确认。"
            }
          ]
        ]
      })
    );

    const preview = await agent.handleUserMessage("刚买了一盒豆腐，记入库存");
    const pendingActionId = preview.uiOnly?.pendingActionId;
    expect(pendingActionId).toBeTruthy();
    const before = domain
      .getDayContext()
      .inventory.find((item) => item.foodId === "food-tofu")?.quantity.estimateG;

    const followUp = await agent.handleUserMessage("查一下晚餐准备规则");

    expect(followUp.toolTrace).toEqual([
      expect.objectContaining({
        tool: "retrieve_local_knowledge",
        ok: true
      })
    ]);
    expect(agent.getTaskState()).toMatchObject({
      status: "waiting_confirmation",
      workflowStage: "awaiting_confirm",
      pendingActionId
    });
    const after = domain
      .getDayContext()
      .inventory.find((item) => item.foodId === "food-tofu")?.quantity.estimateG;
    expect(after).toBe(before);
  });
});
