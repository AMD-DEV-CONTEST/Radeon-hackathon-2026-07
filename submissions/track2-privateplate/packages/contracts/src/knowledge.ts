import { z } from "zod";

export const KnowledgeRiskLevelSchema = z.enum(["low", "medium", "high"]);
export const KnowledgeReviewStatusSchema = z.enum([
  "draft",
  "approved",
  "rejected"
]);

export const KnowledgeCardSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  body: z.string().min(1),
  tags: z.array(z.string()),
  appliesTo: z.array(z.string()),
  exclusions: z.array(z.string()).default([]),
  riskLevel: KnowledgeRiskLevelSchema.default("low"),
  reviewStatus: KnowledgeReviewStatusSchema.default("approved"),
  sourceId: z.string().min(1),
  sourceYear: z.number().int().nullable().default(null),
  licenseId: z.string().min(1),
  cardVersion: z.string().min(1)
});

export type KnowledgeCard = z.infer<typeof KnowledgeCardSchema>;
