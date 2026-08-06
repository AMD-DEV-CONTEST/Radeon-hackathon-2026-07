import { z } from "zod";
import { ErrorCodeSchema } from "./enums.js";

export const DomainErrorSchema = z.object({
  code: ErrorCodeSchema,
  message: z.string().min(1),
  details: z.record(z.unknown()).optional()
});

export type DomainError = z.infer<typeof DomainErrorSchema>;

export function domainError(
  code: z.infer<typeof ErrorCodeSchema>,
  message: string,
  details?: Record<string, unknown>
): DomainError {
  return details ? { code, message, details } : { code, message };
}
