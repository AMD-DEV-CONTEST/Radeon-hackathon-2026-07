import { beforeAll, describe, expect, it } from "vitest";
import { applyTrustedArgumentPolicy } from "./argument-policy.js";
import {
  OpenAiCompatibleToolProvider,
  type ModelRouteInput
} from "./provider.js";

beforeAll(() => {
  // Provider unit tests mock OpenAI tool_calls; disable envelope mode here.
  process.env.PRIVATEPLATE_STRUCTURED_OUTPUTS = "0";
});

const dictionary = {
  members: [
    { id: "mem-admin", displayName: "管理员", roleLabel: "admin", aliases: [] },
    { id: "mem-father", displayName: "父亲", roleLabel: "father", aliases: [] },
    { id: "mem-mother", displayName: "母亲", roleLabel: "mother", aliases: [] }
  ],
  foods: [
    { id: "food-tofu", name: "豆腐", aliases: ["豆腐"] },
    { id: "food-chicken-leg", name: "鸡腿", aliases: ["鸡腿"] }
  ],
  templates: [
    { id: "tpl-cabbage-tofu-braise", name: "白菜豆腐煲", aliases: [] },
    { id: "tpl-leftover-rice", name: "昨日米饭", aliases: [] }
  ],
  planTags: [],
  caregiverRecipientLabels: ["保姆", "阿姨"]
};

function finalRouteInput(
  mode: "ACTION_ALLOWED" | "FINAL_ONLY" = "FINAL_ONLY"
): ModelRouteInput {
  return {
    userText: "请给出刚生成的午餐计划。",
    conversationHistory: [],
    currentTurn: {
      goal: "compose_meal",
      mode,
      modeReason: mode === "FINAL_ONLY" ? "plan_ready" : "test",
      decisionIndex: 0,
      modelRequestCount: 0,
      maxModelRequests: 4,
      toolResults: [
        {
          step: 0,
          goal: "compose_meal",
          tool: "finalize_meal_plan",
          ok: true,
          data: {
            status: "ok",
            plan: {
              status: "valid",
              menu: [{ templateId: "tpl-leftover-rice", name: "昨日米饭" }]
            }
          }
        }
      ],
      answerValidationFailure: null
    },
    activePlan: {
      id: "plan-1",
      version: 1,
      mealType: "lunch",
      dinerIds: ["mem-admin"],
      menu: [{ templateId: "tpl-leftover-rice", name: "昨日米饭" }],
      rejectedFoodIds: [],
      rejectedTemplateIds: [],
      pinnedTemplateIds: [],
      requestedPriorityFoodIds: [],
      preferLowEffort: false
    },
    pendingClarification: null,
    availableActions:
      mode === "FINAL_ONLY"
        ? { domainTools: [], controlDecisions: ["finish_turn", "ask_user"] }
        : { domainTools: ["preview_inventory_change"], controlDecisions: ["finish_turn"] },
    taskState: {
      objective: "compose_meal",
      status: "completed",
      workflowStage: "plan_ready",
      unresolvedSlots: [],
      knownSlots: {},
      focusedTemplateId: null,
      lastDomainFailureCode: null,
      hasPendingAction: false,
      pendingActionType: null,
      candidateSetId: "cset-1",
      serviceDate: "2026-08-03",
      hasActivePlan: true
    },
    state: {
      phase: "PRESENTING_PLAN",
      dinerIds: ["mem-admin"],
      activePlanId: "plan-1",
      activePlanVersion: 1,
      rejectedFoodIds: [],
      rejectedTemplateIds: []
    },
    dinerIdsLocked: true,
    memberDirectory: dictionary.members,
    fixtureDirectory: {
      foods: dictionary.foods,
      templates: dictionary.templates,
      planTags: dictionary.planTags,
      caregiverRecipientLabels: dictionary.caregiverRecipientLabels
    }
  };
}

describe("trusted argument policy v2", () => {
  it("accepts legal finalize selection", () => {
    const result = applyTrustedArgumentPolicy({
      tool: "finalize_meal_plan",
      userText: "规划午餐",
      dinerIdsLocked: false,
      state: {
        dinerIds: ["mem-admin", "mem-father", "mem-mother"],
        activePlanId: null,
        activePlanVersion: null,
        activePlanTemplateIds: [],
        focusedTemplateId: null,
        expectedRecipientLabel: null,
        rejectedFoodIds: [],
        rejectedTemplateIds: []
      },
      dictionary,
      rawArgs: {
        dinerIds: ["mem-admin", "mem-father", "mem-mother"],
        mealType: "lunch",
        candidateSetId: "cset-1",
        selectedDishes: [
          {
            templateId: "tpl-cabbage-tofu-braise",
            relativePortion: "standard"
          }
        ],
        mealPortionScale: 1.0,
        selectionReason: "优先豆腐"
      }
    });
    expect(result.status).toBe("ok");
  });

  it("rejects unknown template ids", () => {
    const result = applyTrustedArgumentPolicy({
      tool: "finalize_meal_plan",
      userText: "规划午餐",
      dinerIdsLocked: false,
      state: {
        dinerIds: ["mem-admin"],
        activePlanId: null,
        activePlanVersion: null,
        activePlanTemplateIds: [],
        focusedTemplateId: null,
        expectedRecipientLabel: null,
        rejectedFoodIds: [],
        rejectedTemplateIds: []
      },
      dictionary,
      rawArgs: {
        dinerIds: ["mem-admin"],
        mealType: "lunch",
        candidateSetId: "cset-1",
        selectedDishes: [
          { templateId: "tpl-unknown", relativePortion: "standard" }
        ],
        mealPortionScale: 1.0,
        selectionReason: "x"
      }
    });
    expect(result.status).toBe("needs_clarification");
  });

  it("accepts day context diners", () => {
    const result = applyTrustedArgumentPolicy({
      tool: "get_day_context",
      userText: "看看今天额度",
      dinerIdsLocked: true,
      state: {
        dinerIds: ["mem-admin"],
        activePlanId: null,
        activePlanVersion: null,
        activePlanTemplateIds: [],
        focusedTemplateId: null,
        expectedRecipientLabel: null,
        rejectedFoodIds: [],
        rejectedTemplateIds: []
      },
      dictionary,
      rawArgs: { dinerIds: ["mem-admin", "mem-father"] }
    });
    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.effective.dinerIds).toEqual(["mem-admin"]);
    }
  });
});

describe("native provider schema recovery", () => {
  it("retries excludedFoodIds instead of treating it as an empty rejection", async () => {
    const responses = [
      {
        choices: [
          {
            message: {
              tool_calls: [
                {
                  function: {
                    name: "find_dish_candidates",
                    arguments: JSON.stringify({
                      dinerIds: ["mem-admin"],
                      excludedFoodIds: ["food-chicken-leg"],
                      rejectedTemplateIds: []
                    })
                  }
                }
              ]
            }
          }
        ]
      },
      {
        choices: [
          {
            message: {
              tool_calls: [
                {
                  function: {
                    name: "find_dish_candidates",
                    arguments: JSON.stringify({
                      dinerIds: ["mem-admin"],
                      rejectedFoodIds: ["food-chicken-leg"],
                      rejectedTemplateIds: []
                    })
                  }
                }
              ]
            }
          }
        ]
      }
    ];
    const provider = new OpenAiCompatibleToolProvider({
      baseUrl: "http://127.0.0.1:8000/v1",
      model: "test-model",
      fetchImpl: async () =>
        new Response(JSON.stringify(responses.shift()), {
          status: 200,
          headers: { "content-type": "application/json" }
        })
    });

    const result = await provider.route({
      userText: "列出候选，不要鸡腿",
      conversationHistory: [],
      currentTurn: {
        goal: "compose_meal",
        mode: "ACTION_ALLOWED",
        modeReason: "test",
        decisionIndex: 0,
        modelRequestCount: 0,
        maxModelRequests: 4,
        toolResults: [],
        answerValidationFailure: null
      },
      activePlan: null,
      pendingClarification: null,
      availableActions: {
        domainTools: ["find_dish_candidates"],
        controlDecisions: ["finish_turn"]
      },
      taskState: {
        objective: "compose_meal",
        status: "active",
        workflowStage: "day_context",
        unresolvedSlots: [],
        knownSlots: {},
        focusedTemplateId: null,
        lastDomainFailureCode: null,
        hasPendingAction: false,
        pendingActionType: null,
        candidateSetId: null,
        serviceDate: null,
        hasActivePlan: false
      },
      state: {
        phase: "PLANNING",
        dinerIds: ["mem-admin"],
        activePlanId: null,
        activePlanVersion: null,
        rejectedFoodIds: [],
        rejectedTemplateIds: []
      },
      dinerIdsLocked: false,
      memberDirectory: dictionary.members,
      fixtureDirectory: {
        foods: dictionary.foods,
        templates: dictionary.templates,
        planTags: dictionary.planTags,
        caregiverRecipientLabels: dictionary.caregiverRecipientLabels
      }
    } satisfies ModelRouteInput);

    expect(result.kind).toBe("tool");
    if (result.kind === "tool") {
      expect(result.format_retry_count).toBe(1);
      expect(result.effective_arguments.rejectedFoodIds).toEqual([
        "food-chicken-leg"
      ]);
    }
  });
});

describe("FINAL_ONLY content final compatibility", () => {
  it("accepts grounded plain content only as a FINAL_ONLY final", async () => {
    const provider = new OpenAiCompatibleToolProvider({
      baseUrl: "http://127.0.0.1:8000/v1",
      model: "test-model",
      fetchImpl: async () =>
        new Response(
          JSON.stringify({
            choices: [
              {
                finish_reason: "tool_calls",
                message: {
                  tool_calls: [],
                  content: "午餐计划已生成：昨日米饭。确认后才会执行。"
                }
              }
            ]
          }),
          { status: 200, headers: { "content-type": "application/json" } }
        )
    });

    const result = await provider.route(finalRouteInput("FINAL_ONLY"));

    expect(result).toMatchObject({
      kind: "final",
      goal: "compose_meal",
      message: "午餐计划已生成：昨日米饭。确认后才会执行。",
      transport: "content_final"
    });
  });

  it("does not execute or accept plain content in ACTION_ALLOWED", async () => {
    const provider = new OpenAiCompatibleToolProvider({
      baseUrl: "http://127.0.0.1:8000/v1",
      model: "test-model",
      fetchImpl: async () =>
        new Response(
          JSON.stringify({
            choices: [
              {
                message: {
                  tool_calls: [],
                  content: "请把豆腐加入库存。"
                }
              }
            ]
          }),
          { status: 200, headers: { "content-type": "application/json" } }
        )
    });

    const result = await provider.route(finalRouteInput("ACTION_ALLOWED"));

    expect(result.kind).toBe("refuse");
    expect(result).not.toHaveProperty("transport", "content_final");
  });

  it("marks native finish_turn separately from content final", async () => {
    const provider = new OpenAiCompatibleToolProvider({
      baseUrl: "http://127.0.0.1:8000/v1",
      model: "test-model",
      fetchImpl: async () =>
        new Response(
          JSON.stringify({
            choices: [
              {
                message: {
                  tool_calls: [
                    {
                      function: {
                        name: "finish_turn",
                        arguments: JSON.stringify({
                          goal: "compose_meal",
                          message: "午餐计划已生成。"
                        })
                      }
                    }
                  ],
                  content: null
                }
              }
            ]
          }),
          { status: 200, headers: { "content-type": "application/json" } }
        )
    });

    const result = await provider.route(finalRouteInput("FINAL_ONLY"));

    expect(result).toMatchObject({ kind: "final", transport: "native_function" });
  });
});
