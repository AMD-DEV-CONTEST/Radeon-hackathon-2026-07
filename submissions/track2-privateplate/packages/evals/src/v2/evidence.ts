import { z } from "zod";

const Sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);
const CommitShaSchema = z.string().regex(/^[0-9a-f]{40,64}$/);
const LoopbackUrlSchema = z
  .string()
  .url()
  .refine(
    (value) => /^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?(?:\/|$)/i.test(value),
    "endpoint must use loopback"
  );

const TraceValueSchema = z.record(z.unknown()).nullable();

const SourceBindingSchema = z.discriminatedUnion("mode", [
  z
    .object({
      mode: z.literal("clean_commit"),
      commitSha: CommitShaSchema
    })
    .strict(),
  z
    .object({
      mode: z.literal("full_tree_hash"),
      sha256: Sha256Schema,
      baseCommitSha: CommitShaSchema
    })
    .strict(),
  z
    .object({
      mode: z.literal("full_patch_hash"),
      sha256: Sha256Schema,
      baseCommitSha: CommitShaSchema
    })
    .strict()
]);

export const RealModelEvidenceSchema = z
  .object({
    schemaVersion: z.literal("2.0"),
    scenarioId: z.string().min(1),
    git: z
      .object({
        sha: CommitShaSchema,
        dirty: z.boolean()
      })
      .strict(),
    sourceBinding: SourceBindingSchema,
    hashes: z
      .object({
        runner: Sha256Schema,
        scorer: Sha256Schema,
        fixture: Sha256Schema,
        toolSchema: Sha256Schema
      })
      .strict(),
    provider: z
      .object({
        mode: z.literal("local_vllm"),
        model: z.string().min(1),
        modelRevision: z.string().optional(),
        chatEndpoint: LoopbackUrlSchema,
        ragEndpoint: LoopbackUrlSchema
      })
      .strict(),
    environment: z
      .object({
        vllm: z.string().min(1),
        rocm: z.string().min(1),
        gpu: z.string().min(1)
      })
      .strict(),
    trace: z
      .object({
        rawNormalizedEffectivePersisted: z
          .array(
            z
              .object({
                tool: z.string().min(1),
                responseId: z.string().min(1),
                nativeToolCalls: z.array(z.record(z.unknown())),
                raw: TraceValueSchema,
                normalized: TraceValueSchema,
                effective: TraceValueSchema,
                persisted: TraceValueSchema
              })
              .strict()
          ),
        failureAttempts: z.array(
          z
            .object({
              attempt: z.number().int().nonnegative(),
              responseId: z.string().optional(),
              reason: z.string().min(1),
              rawResponse: z.record(z.unknown()).nullable()
            })
            .strict()
        )
      })
      .strict(),
    createdAt: z.string().datetime()
  })
  .strict()
  .superRefine((value, context) => {
    if (
      value.sourceBinding.mode === "clean_commit" &&
      (value.git.dirty || value.sourceBinding.commitSha !== value.git.sha)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["sourceBinding"],
        message: "clean_commit requires a clean worktree and the exact git SHA"
      });
    }
    if (
      value.sourceBinding.mode !== "clean_commit" &&
      value.sourceBinding.baseCommitSha !== value.git.sha
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["sourceBinding", "baseCommitSha"],
        message: "full tree/patch binding must identify the recorded git SHA"
      });
    }
  });

export type RealModelEvidence = z.infer<typeof RealModelEvidenceSchema>;

export function parseRealModelEvidence(value: unknown): RealModelEvidence {
  return RealModelEvidenceSchema.parse(value);
}
