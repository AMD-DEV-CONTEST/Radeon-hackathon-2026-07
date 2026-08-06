import { z } from "zod";
import { PendingActionStatusSchema } from "./enums.js";
import { ShoppingGapItemSchema } from "./planning.js";
import { GramRangeSchema } from "./quantity.js";

export const CAREGIVER_RECIPIENT_LABELS = [
  "家庭保姆",
  "保姆",
  "阿姨"
] as const;

export const CAREGIVER_SERVE_AT_PATTERN =
  /^(?:unspecified|今天 (?:[01]\d|2[0-3]):[0-5]\d|\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d))$/;

export const CaregiverRecipientLabelSchema = z.enum(
  CAREGIVER_RECIPIENT_LABELS
);

export const CaregiverServeAtSchema = z
  .string()
  .regex(CAREGIVER_SERVE_AT_PATTERN)
  .refine(
    (value) =>
      value === "unspecified" ||
      value.startsWith("今天 ") ||
      Number.isFinite(Date.parse(value)),
    "serveAt must be a valid supported time"
  );

export const CaregiverTaskCardSchema = z.object({
  planId: z.string(),
  planVersion: z.number().int().positive(),
  recipientLabel: CaregiverRecipientLabelSchema,
  serveAt: CaregiverServeAtSchema,
  menu: z.array(
    z.object({
      templateId: z.string(),
      displayName: z.string()
    })
  ),
  useFromInventory: z.array(
    z.object({
      foodId: z.string(),
      quantity: GramRangeSchema
    })
  ),
  shoppingItems: z.array(ShoppingGapItemSchema),
  executionNotes: z.array(z.string()),
  disclosurePolicyVersion: z.string()
});

export type CaregiverTaskCard = z.infer<typeof CaregiverTaskCardSchema>;

export const CommitResultSchema = z.object({
  caregiverTaskId: z.string(),
  channel: z.literal("simulated_local_inbox"),
  status: z.literal("queued")
});

export type CommitResult = z.infer<typeof CommitResultSchema>;

export const CommitReceiptSchema = z.object({
  pendingActionId: z.string(),
  idempotencyKey: z.string(),
  payloadHash: z.string(),
  result: CommitResultSchema,
  resultHash: z.string(),
  committedAt: z.string(),
  replayed: z.boolean()
});

export type CommitReceipt = z.infer<typeof CommitReceiptSchema>;

export const ConfirmationRequiredEventSchema = z.object({
  pendingActionId: z.string(),
  confirmationToken: z.string(),
  payloadHash: z.string(),
  expiresAt: z.string()
});

export type ConfirmationRequiredEvent = z.infer<typeof ConfirmationRequiredEventSchema>;

export const ConfirmPendingActionRequestSchema = z.object({
  confirmationToken: z.string().min(1),
  idempotencyKey: z.string().min(1),
  expectedPayloadHash: z.string().min(1)
});

export type ConfirmPendingActionRequest = z.infer<typeof ConfirmPendingActionRequestSchema>;

export const PendingActionSchema = z.object({
  id: z.string(),
  householdId: z.string(),
  actionType: z.literal("caregiver_task_send"),
  payload: CaregiverTaskCardSchema,
  payloadHash: z.string(),
  preview: CaregiverTaskCardSchema,
  confirmationTokenHash: z.string(),
  status: PendingActionStatusSchema,
  expiresAt: z.string(),
  committedAt: z.string().nullable(),
  idempotencyKey: z.string().nullable(),
  commitResult: CommitResultSchema.nullable(),
  commitResultHash: z.string().nullable(),
  createdAt: z.string()
});

export type PendingAction = z.infer<typeof PendingActionSchema>;

export const ConfirmErrorCodeSchema = z.enum([
  "TOKEN_EXPIRED",
  "TOKEN_INVALID",
  "IDEMPOTENCY_CONFLICT",
  "ACTION_ALREADY_COMMITTED",
  "STALE_CONTEXT",
  "PAYLOAD_HASH_MISMATCH",
  "INTERNAL_ERROR"
]);

export type ConfirmErrorCode = z.infer<typeof ConfirmErrorCodeSchema>;
