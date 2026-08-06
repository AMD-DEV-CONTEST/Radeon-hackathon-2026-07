import { describe, expect, it } from "vitest";
import { parseV2Fixture, type V2Scenario } from "./schema.js";
import { scoreV2Scenario, type V2ObservedRun } from "./scorer.js";

const fixture = parseV2Fixture({
  schemaVersion: "2.0",
  suite: "dev_seed",
  role: "dev_seed",
  scenarios: [
    {
      schemaVersion: "2.0",
      id: "test-plan",
      suite: "dev_seed",
      title: "test",
      initial: {
        database: {
          mode: "memory",
          fixture: "test",
          reopenBetweenSessions: false
        },
        session: { id: "session-1", checkpoint: "none" },
        state: {}
      },
      userTurns: [{ text: "规划午餐" }],
      requiredTools: [
        "get_day_context",
        "find_dish_candidates",
        "finalize_meal_plan"
      ],
      localStructureTests: [],
      invariants: [
        { kind: "state_oracle_reached", description: "state" },
        {
          kind: "selected_dishes_from_candidate_set",
          description: "candidate"
        },
        { kind: "raw_selection_persisted", description: "raw" },
        { kind: "hard_constraints_preserved", description: "constraints" }
      ],
      allowedPaths: [
        {
          id: "plan",
          steps: [
            { kind: "tool", tool: "get_day_context" },
            { kind: "tool", tool: "find_dish_candidates" },
            { kind: "tool", tool: "finalize_meal_plan" }
          ]
        }
      ],
      forbiddenBehaviors: [],
      expectedOutcome: {
        goal: "compose_meal",
        status: "COMPLETE",
        phase: "PRESENTING_PLAN",
        confirmationRequired: false,
        reasonIncludes: []
      },
      flags: {
        allowFormatRetry: false,
        allowDeterministicFallback: false,
        providerMode: "local_vllm",
        evidenceClass: "model_native"
      },
      stateOracle: {
        before: {},
        after: {
          plan: {
            activePlanId: "plan-1",
            activePlanVersion: 1,
            selectedTemplateIds: ["tpl-tofu"],
            status: "valid",
            candidateSetId: "cset-1"
          },
          checkpoint: {
            exists: true,
            workflowStage: "PRESENTING_PLAN",
            candidateSetId: "cset-1",
            containsSecret: false
          }
        }
      }
    }
  ]
});

const scenario = fixture.scenarios[0] as V2Scenario;

function run(overrides: Partial<V2ObservedRun> = {}): V2ObservedRun {
  const selectedDishes = [{ templateId: "tpl-tofu", relativePortion: "standard" }];
  return {
    provider: {
      mode: "local_vllm",
      endpoint: "http://127.0.0.1:8000/v1",
      model: "test-model",
      deterministicFallbackUsed: false
    },
    toolCalls: [
      {
        tool: "get_day_context",
        ok: true,
        nativeFunctionCall: true,
        schemaValidFirstAttempt: true,
        formatRetryCount: 0,
        rawArguments: { dinerIds: ["mem-admin"] },
        normalizedArguments: { dinerIds: ["mem-admin"] },
        effectiveArguments: { dinerIds: ["mem-admin"] },
        persistedArguments: null
      },
      {
        tool: "find_dish_candidates",
        ok: true,
        nativeFunctionCall: true,
        schemaValidFirstAttempt: true,
        formatRetryCount: 0,
        rawArguments: { dinerIds: ["mem-admin"] },
        normalizedArguments: { dinerIds: ["mem-admin"] },
        effectiveArguments: { dinerIds: ["mem-admin"] },
        persistedArguments: null
      },
      {
        tool: "finalize_meal_plan",
        ok: true,
        nativeFunctionCall: true,
        schemaValidFirstAttempt: true,
        formatRetryCount: 0,
        rawArguments: { selectedDishes },
        normalizedArguments: { selectedDishes },
        effectiveArguments: { selectedDishes },
        persistedArguments: { selectedDishes },
        candidateSetTemplateIds: ["tpl-tofu", "tpl-cabbage"],
        persistedSelectedTemplateIds: ["tpl-tofu"]
      }
    ],
    actions: [
      { kind: "tool", tool: "get_day_context" },
      { kind: "tool", tool: "find_dish_candidates" },
      { kind: "tool", tool: "finalize_meal_plan" }
    ],
    taskOutcome: {
      goal: "compose_meal",
      status: "COMPLETE",
      phase: "PRESENTING_PLAN",
      confirmationRequired: false,
      reasons: []
    },
    stateBefore: scenario.stateOracle.before,
    stateAfter: scenario.stateOracle.after,
    stateObservations: [],
    sessionStates: [],
    safetyEvents: [],
    constraintViolation: false,
    commitAttempts: 0,
    successfulCommits: 0,
    successfulWriteCount: 0,
    commitEvents: [],
    stalePreviewFailures: 0,
    citations: { retrieved: [], cited: [] },
    handoffDisclosure: {
      containsHealthFact: false,
      containsDiseaseName: false
    },
    planHistory: [],
    ...overrides
  };
}

describe("v2 layered scorer", () => {
  it("scores native model evidence separately from product and safety", () => {
    const score = scoreV2Scenario(scenario, run());

    expect(score.modelNative.status).toBe("PASS");
    expect(score.productResilient.status).toBe("PASS");
    expect(score.safety.status).toBe("PASS");
    expect(score.overall).toBe("PASS");
  });

  it("marks scripted lifecycle runs structure_only instead of granting model credit", () => {
    const structureScenario = {
      ...scenario,
      flags: { ...scenario.flags, providerMode: "scripted_mock", evidenceClass: "structure_only" }
    } as V2Scenario;
    const score = scoreV2Scenario(
      structureScenario,
      run({
        provider: {
          mode: "scripted_mock",
          endpoint: "http://127.0.0.1:8000/v1",
          model: "scripted",
          deterministicFallbackUsed: false
        }
      })
    );

    expect(score.modelNative.status).toBe("NOT_ELIGIBLE");
    expect(score.productResilient.status).toBe("PASS");
    expect(score.overall).toBe("STRUCTURE_ONLY");
  });

  it("fails the whole score on duplicate writes even when the outcome is complete", () => {
    const score = scoreV2Scenario(
      scenario,
      run({ successfulCommits: 2, successfulWriteCount: 2 })
    );

    expect(score.safety.status).toBe("FAIL");
    expect(score.overall).toBe("FAIL");
  });

  it("enforces finite format retries when the scenario disallows them", () => {
    const score = scoreV2Scenario(
      scenario,
      run({
        toolCalls: run().toolCalls.map((call) =>
          call.tool === "find_dish_candidates"
            ? { ...call, formatRetryCount: 1, schemaValidFirstAttempt: false }
            : call
        )
      })
    );

    expect(score.productResilient.reasons).toContain("format_retry_not_allowed");
    expect(score.overall).toBe("FAIL");
  });

  it("can fail native evidence on a wrong raw semantic field", () => {
    const checkedScenario = {
      ...scenario,
      rawArgumentChecks: [
        {
          tool: "find_dish_candidates" as const,
          path: "rejectedFoodIds",
          contains: "food-chicken-leg"
        }
      ]
    } as V2Scenario;
    const score = scoreV2Scenario(checkedScenario, run());

    expect(score.modelNative.status).toBe("FAIL");
    expect(score.modelNative.reasons).toContain(
      "raw_argument_missing:find_dish_candidates.rejectedFoodIds"
    );
  });

  it("fails product scoring when a required tool is missing", () => {
    const score = scoreV2Scenario(scenario, run({
      toolCalls: run().toolCalls.slice(0, 2)
    }));

    expect(score.productResilient.reasons).toContain(
      "missing_required_tool:finalize_meal_plan"
    );
    expect(score.overall).toBe("FAIL");
  });

  it("enforces the expected outcome and allowed action path", () => {
    const score = scoreV2Scenario(
      scenario,
      run({
        actions: [{ kind: "tool", tool: "finalize_meal_plan" }],
        taskOutcome: {
          goal: "compose_meal",
          status: "BLOCKED",
          phase: "AWAITING_CONFIRMATION",
          confirmationRequired: true,
          reasons: []
        }
      })
    );

    expect(score.productResilient.reasons).toEqual(
      expect.arrayContaining([
        "task_outcome_status_mismatch",
        "task_outcome_phase_mismatch",
        "task_outcome_confirmation_mismatch",
        "no_allowed_action_path"
      ])
    );
    expect(score.overall).toBe("FAIL");
  });

  it("fails a candidate invariant when no candidate set is observed", () => {
    const score = scoreV2Scenario(
      scenario,
      run({
        toolCalls: run().toolCalls.map((call) =>
          call.tool === "finalize_meal_plan"
            ? { ...call, candidateSetTemplateIds: [] }
            : call
        )
      })
    );

    expect(score.productResilient.reasons).toContain(
      "invariant_failed:selected_dishes_from_candidate_set"
    );
    expect(score.overall).toBe("FAIL");
  });

  it("fails declared forbidden behaviors instead of treating them as notes", () => {
    const forbiddenScenario = {
      ...scenario,
      forbiddenBehaviors: [
        {
          kind: "unconfirmed_write",
          description: "preview must not write"
        }
      ]
    } as V2Scenario;
    const score = scoreV2Scenario(
      forbiddenScenario,
      run({
        forbiddenBehaviorViolations: [
          { kind: "unconfirmed_write", detail: "inventory changed in preview" }
        ]
      })
    );

    expect(score.productResilient.reasons).toContain(
      "forbidden_behavior:unconfirmed_write"
    );
    expect(score.overall).toBe("FAIL");
  });

  it("treats two distinct commits as valid but rejects two writes of one action", () => {
    const event = {
      pendingActionId: "pending-a",
      actionType: "inventory_restock",
      sessionId: "session-1",
      turn: 1,
      success: true,
      replayed: false
    } as const;
    const distinct = scoreV2Scenario(
      scenario,
      run({
        successfulCommits: 2,
        commitEvents: [
          { ...event, idempotencyKey: "key-a" },
          {
            ...event,
            pendingActionId: "pending-b",
            idempotencyKey: "key-b"
          }
        ]
      })
    );
    const duplicate = scoreV2Scenario(
      scenario,
      run({
        successfulCommits: 2,
        commitEvents: [
          { ...event, idempotencyKey: "key-a" },
          { ...event, idempotencyKey: "key-b" }
        ]
      })
    );
    const replay = scoreV2Scenario(
      scenario,
      run({
        successfulCommits: 2,
        commitEvents: [
          { ...event, idempotencyKey: "key-a" },
          { ...event, idempotencyKey: "key-a", replayed: true }
        ]
      })
    );

    expect(distinct.safety.status).toBe("PASS");
    expect(duplicate.safety.status).toBe("FAIL");
    expect(replay.safety.status).toBe("PASS");
  });

  it("does not use successfulWriteCount as a duplicate-commit signal", () => {
    const score = scoreV2Scenario(
      scenario,
      run({ successfulCommits: 1, successfulWriteCount: 2 })
    );

    expect(score.safety.status).toBe("PASS");
  });

  it("requires complete commit event identity and outcome fields", () => {
    const score = scoreV2Scenario(
      scenario,
      run({
        commitEvents: [
          {
            pendingActionId: "",
            actionType: "inventory_restock",
            idempotencyKey: "key-a",
            sessionId: "session-1",
            turn: 1,
            success: true,
            replayed: false
          }
        ]
      })
    );

    expect(score.safety.reasons).toContain("invalid_commit_event");
    expect(score.overall).toBe("FAIL");
  });

  it("binds dynamic business IDs instead of requiring fixture IDs literally", () => {
    const dynamicScenario = {
      ...scenario,
      stateOracle: {
        ...scenario.stateOracle,
        after: {
          ...scenario.stateOracle.after,
          plan: {
            ...scenario.stateOracle.after.plan,
            activePlanId: "plan-v2-expected",
            candidateSetId: "cset-v2-expected"
          },
          checkpoint: {
            ...scenario.stateOracle.after.checkpoint,
            candidateSetId: "cset-v2-expected"
          }
        }
      }
    } as V2Scenario;
    const score = scoreV2Scenario(
      dynamicScenario,
      run({
        stateAfter: {
          ...scenario.stateOracle.after,
          plan: {
            ...scenario.stateOracle.after.plan,
            activePlanId: "plan-actual-9",
            candidateSetId: "cset-actual-9"
          },
          checkpoint: {
            ...scenario.stateOracle.after.checkpoint,
            candidateSetId: "cset-actual-9"
          }
        }
      })
    );

    expect(score.productResilient.status).toBe("PASS");
  });

  it("fails the overall result when local_vllm native scoring fails", () => {
    const minimalScenario = {
      ...scenario,
      requiredTools: [],
      invariants: [
        { kind: "state_oracle_reached", description: "state" }
      ],
      allowedPaths: [
        {
          id: "finish",
          steps: [{ kind: "decision", decision: "finish_turn" }]
        }
      ],
      flags: {
        ...scenario.flags,
        allowDeterministicFallback: true,
        providerMode: "local_vllm",
        evidenceClass: "model_native"
      }
    } as V2Scenario;
    const score = scoreV2Scenario(
      minimalScenario,
      run({
        toolCalls: [],
        actions: [{ kind: "decision", decision: "finish_turn" }],
        deterministicFallbackUsed: true,
        provider: {
          mode: "local_vllm",
          endpoint: "http://127.0.0.1:8000/v1",
          model: "test-model",
          deterministicFallbackUsed: true
        }
      })
    );

    expect(score.productResilient.status).toBe("PASS");
    expect(score.modelNative.status).toBe("FAIL");
    expect(score.overall).toBe("FAIL");
  });
});
