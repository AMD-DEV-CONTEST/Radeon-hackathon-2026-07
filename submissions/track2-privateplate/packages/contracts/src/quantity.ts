import { z } from "zod";
import { QuantityConfidenceSchema } from "./enums.js";

const NonnegativeGramsSchema = z.number().finite().nonnegative().nullable();

export const GramRangeSchema = z
  .object({
    estimateG: NonnegativeGramsSchema,
    minG: NonnegativeGramsSchema,
    maxG: NonnegativeGramsSchema,
    confidence: QuantityConfidenceSchema,
    conversionRuleId: z.string().nullable()
  })
  .superRefine((value, ctx) => {
    if (value.minG != null && value.maxG != null && value.minG > value.maxG) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "GramRange requires minG <= maxG"
      });
    }
    if (
      value.estimateG != null &&
      value.minG != null &&
      value.estimateG < value.minG
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "GramRange estimateG must be within minG/maxG"
      });
    }
    if (
      value.estimateG != null &&
      value.maxG != null &&
      value.estimateG > value.maxG
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "GramRange estimateG must be within minG/maxG"
      });
    }
    if (value.confidence === "exact") {
      if (
        value.estimateG == null ||
        value.minG == null ||
        value.maxG == null ||
        value.estimateG !== value.minG ||
        value.minG !== value.maxG
      ) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "exact GramRange requires estimateG = minG = maxG"
        });
      }
    }
    if (value.confidence === "approximate") {
      if (value.minG == null || value.maxG == null || value.minG > value.maxG) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "approximate GramRange requires ordered minG/maxG"
        });
      }
    }
    if (value.confidence === "unknown") {
      // unknown must not pretend to be precise purchasable grams
      if (value.estimateG != null && value.minG != null && value.maxG != null) {
        if (value.estimateG === value.minG && value.minG === value.maxG) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: "unknown GramRange must not present a single exact gram value"
          });
        }
      }
    }
  });

export type GramRange = z.infer<typeof GramRangeSchema>;

export const InventoryQuantitySchema = z.object({
  rawExpression: z.string().min(1),
  normalized: GramRangeSchema
});

export type InventoryQuantity = z.infer<typeof InventoryQuantitySchema>;

export function isExactPurchaseable(range: GramRange): boolean {
  return range.confidence === "exact" && range.estimateG != null;
}

export function canSubtractFromInventory(range: GramRange): boolean {
  return range.confidence === "exact";
}
