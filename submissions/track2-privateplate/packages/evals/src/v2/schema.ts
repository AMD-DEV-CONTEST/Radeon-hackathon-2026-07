import { z } from "zod";

export const V2_TOOL_NAMES = [
  "get_day_context",
  "get_inventory",
  "find_dish_candidates",
  "finalize_meal_plan",
  "retrieve_local_knowledge",
  "preview_inventory_change",
  "preview_member_memory_change",
  "preview_caregiver_task",
  "preview_meal_completion"
] as const;

export const V2_GOALS = [
  "inspect_context",
  "inspect_inventory",
  "compose_meal",
  "revise_meal",
  "retrieve_guidance",
  "preview_inventory",
  "update_inventory",
  "preview_member_memory",
  "update_member_memory",
  "preview_handoff",
  "send_handoff",
  "preview_meal_completion",
  "complete_meal"
] as const;

const GoalSchema = z.enum(V2_GOALS);
const ToolSchema = z.enum(V2_TOOL_NAMES);

const DatabaseStateSchema = z
  .object({
    householdId: z.string().nullable().optional(),
    inventory: z.record(z.number()).optional(),
    memoryFactIds: z.array(z.string()).optional(),
    completedMealCount: z.number().int().nonnegative().optional(),
    caregiverTaskCount: z.number().int().nonnegative().optional(),
    pendingActionCount: z.number().int().nonnegative().optional()
  })
  .strict();

const PlanStateSchema = z
  .object({
    activePlanId: z.string().nullable().optional(),
    activePlanVersion: z.number().int().nonnegative().nullable().optional(),
    selectedTemplateIds: z.array(z.string()).optional(),
    status: z
      .enum(["draft", "valid", "superseded", "completed", "infeasible"])
      .nullable()
      .optional(),
    candidateSetId: z.string().nullable().optional()
  })
  .strict();

const LedgerStateSchema = z
  .object({
    inventoryVersion: z.number().int().nonnegative().optional(),
    intakeVersion: z.number().int().nonnegative().optional(),
    inventoryEntryCount: z.number().int().nonnegative().optional(),
    completedMealCount: z.number().int().nonnegative().optional()
  })
  .strict();

const PendingActionStateSchema = z
  .object({
    id: z.string().nullable().optional(),
    actionType: z.string().nullable().optional(),
    status: z
      .enum(["pending", "committed", "cancelled", "expired"])
      .nullable()
      .optional(),
    confirmationRequired: z.boolean().optional()
  })
  .strict();

const CheckpointStateSchema = z
  .object({
    exists: z.boolean().optional(),
    workflowStage: z.string().nullable().optional(),
    taskStatus: z
      .enum(["active", "waiting_user", "waiting_confirmation", "completed", "blocked"])
      .nullable()
      .optional(),
    taskWorkflowStage: z.string().nullable().optional(),
    candidateSetId: z.string().nullable().optional(),
    pendingActionType: z.string().nullable().optional(),
    containsSecret: z.boolean().optional()
  })
  .strict();

export const StateSnapshotSchema = z
  .object({
    database: DatabaseStateSchema.default({}),
    plan: PlanStateSchema.default({}),
    ledger: LedgerStateSchema.default({}),
    pendingAction: PendingActionStateSchema.default({}),
    checkpoint: CheckpointStateSchema.default({})
  })
  .strict()
  .default({});

const InitialStateSchema = z
  .object({
    database: z
      .object({
        mode: z.enum(["memory", "sqlite_file"]),
        fixture: z.string(),
        reopenBetweenSessions: z.boolean()
      })
      .strict(),
    session: z
      .object({
        id: z.string(),
        checkpoint: z.enum(["none", "resume"])
      })
      .strict(),
    state: StateSnapshotSchema
  })
  .strict();

const UserTurnSchema = z
  .object({
    sessionId: z.string().default("session-1"),
    text: z.string().min(1),
    confirmation: z.enum(["none", "confirm", "cancel"]).default("none"),
    checkpointAfter: z.boolean().default(false)
  })
  .strict();

const InvariantSchema = z
  .object({
    kind: z.enum([
      "database_unchanged_before_confirmation",
      "database_changed_after_confirmation",
      "selected_dishes_from_candidate_set",
      "raw_selection_persisted",
      "no_duplicate_commit",
      "cross_session_state",
      "hard_constraints_preserved",
      "pending_confirmation_required",
      "old_plan_superseded",
      "old_preview_invalid",
      "rag_source_grounded",
      "minimum_disclosure",
      "no_remote_model",
      "no_deterministic_fallback",
      "state_oracle_reached"
    ]),
    description: z.string().min(1),
    scope: z.string().optional()
  })
  .strict();

const PathStepSchema = z.union([
  z.object({ kind: z.literal("tool"), tool: ToolSchema }).strict(),
  z
    .object({
      kind: z.literal("decision"),
      decision: z.enum(["ask_user", "finish_turn", "refuse_request"])
    })
    .strict()
]);

const AllowedPathSchema = z
  .object({
    id: z.string().min(1),
    steps: z.array(PathStepSchema).min(1)
  })
  .strict();

const RawArgumentCheckSchema = z
  .object({
    tool: ToolSchema,
    path: z.string().min(1),
    equals: z.unknown().optional(),
    contains: z.unknown().optional(),
    textIncludes: z.string().optional(),
    textExcludes: z.string().optional()
  })
  .strict();

const ForbiddenBehaviorSchema = z
  .object({
    kind: z.enum([
      "unconfirmed_write",
      "duplicate_commit",
      "wrong_household",
      "wrong_member",
      "privacy_leak",
      "medical_advice",
      "remote_model",
      "false_write_claim",
      "deterministic_fallback",
      "partial_as_complete",
      "wrong_tool_arguments"
    ]),
    description: z.string().min(1)
  })
  .strict();

const ExpectedOutcomeSchema = z
  .object({
    goal: GoalSchema,
    status: z.enum(["COMPLETE", "PARTIAL", "BLOCKED", "FAILED"]),
    phase: z.string(),
    confirmationRequired: z.boolean(),
    reasonIncludes: z.array(z.string()).default([])
  })
  .strict();

const FlagsSchema = z
  .object({
    allowFormatRetry: z.boolean(),
    allowDeterministicFallback: z.boolean(),
    providerMode: z.enum(["local_vllm", "scripted_mock"]),
    evidenceClass: z.enum(["model_native", "structure_only"])
  })
  .strict();

export const V2ScenarioSchema = z
  .object({
    schemaVersion: z.literal("2.0"),
    id: z.string().min(1),
    suite: z.enum(["dev_seed", "stateful_lifecycle"]),
    title: z.string().min(1),
    initial: InitialStateSchema,
    userTurns: z.array(UserTurnSchema).min(1),
    requiredTools: z.array(ToolSchema).default([]),
    localStructureTests: z.array(z.string()).default([]),
    rawArgumentChecks: z.array(RawArgumentCheckSchema).default([]),
    invariants: z.array(InvariantSchema).min(1),
    allowedPaths: z.array(AllowedPathSchema).min(1),
    forbiddenBehaviors: z.array(ForbiddenBehaviorSchema),
    expectedOutcome: ExpectedOutcomeSchema,
    flags: FlagsSchema,
    stateOracle: z
      .object({
        before: StateSnapshotSchema,
        after: StateSnapshotSchema
      })
      .strict()
  })
  .strict();

export const HiddenManifestSchema = z
  .object({
    version: z.literal("2.0"),
    fixtureSha256: z.string().regex(/^[a-f0-9]{64}$/),
    scenarioIds: z.array(z.string()),
    hiddenCount: z.number().int().nonnegative()
  })
  .strict();

export const V2FixtureSchema = z
  .object({
    schemaVersion: z.literal("2.0"),
    suite: z.enum(["dev_seed", "stateful_lifecycle"]),
    role: z.enum(["dev_seed", "lifecycle_spec"]),
    scenarios: z.array(V2ScenarioSchema).min(1),
    hiddenManifest: HiddenManifestSchema.optional()
  })
  .strict();

export type V2StateSnapshot = z.infer<typeof StateSnapshotSchema>;
export type V2Scenario = z.infer<typeof V2ScenarioSchema>;
export type V2Fixture = z.infer<typeof V2FixtureSchema>;
export type V2HiddenManifest = z.infer<typeof HiddenManifestSchema>;
export type V2ToolName = (typeof V2_TOOL_NAMES)[number];
export type V2Goal = (typeof V2_GOALS)[number];

export function parseV2Fixture(value: unknown): V2Fixture {
  return V2FixtureSchema.parse(value);
}
