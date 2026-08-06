import { afterEach, describe, expect, it } from "vitest";
import { PrivatePlateDomain } from "@privateplate/domain";
import {
  ScriptedProductProvider,
  type AgentModelProvider
} from "@privateplate/agent-runtime";
import { AgentSessionManager } from "./session-manager.js";

describe("AgentSessionManager", () => {
  let domain: PrivatePlateDomain | null = null;

  afterEach(() => {
    domain?.close();
    domain = null;
  });

  it("isolates two browser sessions and restores checkpoints", async () => {
    domain = await PrivatePlateDomain.create(":memory:");
    const provider = new ScriptedProductProvider();
    const firstManager = new AgentSessionManager(domain, provider);

    await firstManager.run(
      "browser-a",
      "今天只有爸爸和妈妈吃晚饭。",
      ["mem-father", "mem-mother"]
    );
    await firstManager.run(
      "browser-b",
      "中午我们三个人吃什么？不要鸡腿。"
    );

    expect(firstManager.getState("browser-a").dinerIds).toEqual([
      "mem-father",
      "mem-mother"
    ]);
    expect(firstManager.getState("browser-b").dinerIds).toHaveLength(3);

    const restoredManager = new AgentSessionManager(
      domain,
      new ScriptedProductProvider()
    );
    expect(restoredManager.getState("browser-a")).toMatchObject({
      dinerIds: ["mem-father", "mem-mother"],
      activePlanVersion: 1
    });

    await restoredManager.clear("browser-a");
    expect(domain.loadAgentCheckpoint("browser-a")).toBeNull();
    expect(domain.loadAgentCheckpoint("browser-b")).not.toBeNull();
    expect(restoredManager.getState("browser-a").activePlanId).toBeNull();
  });

  it("seeds diners from UI chips but lets conversation revise them", async () => {
    domain = await PrivatePlateDomain.create(":memory:");
    const provider = new ScriptedProductProvider();
    const manager = new AgentSessionManager(domain, provider);

    await manager.run(
      "revise-diners",
      "安排今晚的晚餐。",
      ["mem-admin", "mem-father", "mem-mother"]
    );
    expect(manager.getState("revise-diners").dinerIds).toEqual([
      "mem-admin",
      "mem-father",
      "mem-mother"
    ]);

    // Chips still show three people; conversation asks for parents only.
    // Without locking tool args, the model/scripted diners must win.
    await manager.run(
      "revise-diners",
      "纠正一下，改成爸爸和妈妈两个人；刚才的计划不能沿用，请按新成员重做。",
      ["mem-admin", "mem-father", "mem-mother"]
    );

    const state = manager.getState("revise-diners");
    expect(state.dinerIds).toEqual(["mem-father", "mem-mother"]);
    const plan = state.activePlanId
      ? domain.getPlanById(state.activePlanId)
      : null;
    expect(plan?.dinerIds).toEqual(["mem-father", "mem-mother"]);
  });

  it("prevents queued work from reviving a session while it is being cleared", async () => {
    domain = await PrivatePlateDomain.create(":memory:");
    let releaseProvider!: () => void;
    const providerGate = new Promise<void>((resolve) => {
      releaseProvider = resolve;
    });
    const provider: AgentModelProvider = {
      mode: "local_vllm",
      model: "clear-race-test",
      route: async (input) => {
        if (input.currentTurn.toolResults.length > 0) {
          return {
            kind: "final" as const,
            goal: "inspect_context" as const,
            message: "上下文已读取。",
            reasonCode: null,
            model: "clear-race-test",
            privacy_violation: false,
            format_retry_count: 0,
            format_retry_reasons: [] as string[]
          };
        }
        await providerGate;
        const effective = {
          dinerIds: ["mem-admin", "mem-father", "mem-mother"]
        };
        return {
          kind: "tool" as const,
          goal: "inspect_context" as const,
          tool: "get_day_context" as const,
          model: "clear-race-test",
          arguments: effective,
          raw_model_arguments: effective,
          normalized_model_arguments: effective,
          effective_arguments: effective,
          policy: {
            status: "ok" as const,
            effective,
            privacy_violation: false,
            reasons: [] as string[]
          },
          privacy_violation: false,
          format_retry_count: 0,
          format_retry_reasons: [] as string[]
        };
      }
    };
    const manager = new AgentSessionManager(domain, provider);

    const running = manager.run("clear-race", "查看家庭库存和成员");
    const clearing = manager.clear("clear-race");
    await expect(
      manager.run("clear-race", "查看家庭库存和成员")
    ).rejects.toThrow(/正在清理/);

    releaseProvider();
    await running;
    await clearing;
    expect(domain.loadAgentCheckpoint("clear-race")).toBeNull();

    const fresh = await manager.run("clear-race", "查看家庭库存和成员");
    expect(fresh.phase).not.toBe("ERROR");
    expect(domain.loadAgentCheckpoint("clear-race")).not.toBeNull();
  });
});
