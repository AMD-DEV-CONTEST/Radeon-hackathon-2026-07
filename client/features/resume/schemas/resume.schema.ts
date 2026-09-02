import { z } from "zod";

import {
  RESUME_ACCEPTED_EXTENSIONS,
  RESUME_ACCEPTED_MIME_TYPES,
  RESUME_MAX_FILE_SIZE_BYTES,
} from "@/features/resume/types/resume.types";

function hasAcceptedExtension(fileName: string): boolean {
  const lowerName = fileName.toLowerCase();
  return RESUME_ACCEPTED_EXTENSIONS.some((extension) =>
    lowerName.endsWith(extension)
  );
}

function hasAcceptedMimeType(mimeType: string): boolean {
  return (RESUME_ACCEPTED_MIME_TYPES as ReadonlyArray<string>).includes(
    mimeType
  );
}

export const resumeFileSchema = z
  .custom<File>((value) => value instanceof File, {
    message: "Please select a resume file",
  })
  .refine((file) => file.size > 0, {
    message: "The selected file is empty",
  })
  .refine((file) => file.size <= RESUME_MAX_FILE_SIZE_BYTES, {
    message: "File must be 10MB or smaller",
  })
  .refine(
    (file) =>
      hasAcceptedExtension(file.name) || hasAcceptedMimeType(file.type),
    {
      message: "Only PDF and DOCX files are supported",
    }
  );

export const resumeUploadSchema = z.object({
  fullName: z
    .string()
    .trim()
    .min(1, "Full name is required")
    .max(120, "Full name must be 120 characters or fewer"),
  email: z
    .string()
    .trim()
    .min(1, "Email is required")
    .email("Enter a valid email address"),
  targetRole: z
    .string()
    .trim()
    .min(1, "Target role is required")
    .max(120, "Target role must be 120 characters or fewer"),
  yearsOfExperience: z
    .union([z.string(), z.number()])
    .transform((value, ctx) => {
      if (value === "" || value === null || value === undefined) {
        ctx.addIssue({
          code: "custom",
          message: "Years of experience is required",
        });
        return z.NEVER;
      }

      const parsed = typeof value === "number" ? value : Number(value);

      if (!Number.isFinite(parsed)) {
        ctx.addIssue({
          code: "custom",
          message: "Enter a valid number of years",
        });
        return z.NEVER;
      }

      if (parsed < 0) {
        ctx.addIssue({
          code: "custom",
          message: "Years of experience cannot be negative",
        });
        return z.NEVER;
      }

      if (parsed > 60) {
        ctx.addIssue({
          code: "custom",
          message: "Years of experience must be 60 or fewer",
        });
        return z.NEVER;
      }

      return parsed;
    }),
  file: resumeFileSchema,
});

export type ResumeUploadFormValues = z.input<typeof resumeUploadSchema>;
export type ResumeUploadPayloadValues = z.output<typeof resumeUploadSchema>;

export function validateResumeFile(file: File): string | null {
  const result = resumeFileSchema.safeParse(file);
  if (result.success) {
    return null;
  }

  return result.error.issues[0]?.message ?? "Invalid resume file";
}
