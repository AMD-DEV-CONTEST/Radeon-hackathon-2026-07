import { z } from "zod";

const passwordSchema = z
  .string()
  .min(1, "Password is required")
  .min(8, "Password must be at least 8 characters")
  .regex(/[A-Z]/, "Password must include an uppercase letter")
  .regex(/[a-z]/, "Password must include a lowercase letter")
  .regex(/[0-9]/, "Password must include a number")
  .regex(
    /[^A-Za-z0-9]/,
    "Password must include a special character"
  );

export const registerSchema = z
  .object({
    fullName: z
      .string()
      .min(1, "Full name is required")
      .min(3, "Full name must be at least 3 characters"),
    email: z
      .string()
      .min(1, "Email is required")
      .email("Enter a valid email address"),
    password: passwordSchema,
    confirmPassword: z.string().min(1, "Confirm your password"),
    acceptTerms: z.boolean().refine((value) => value === true, {
      message: "You must accept the Terms & Conditions",
    }),
    receiveUpdates: z.boolean(),
  })
  .superRefine((values, ctx) => {
    if (values.password !== values.confirmPassword) {
      ctx.addIssue({
        code: "custom",
        path: ["confirmPassword"],
        message: "Passwords must match",
      });
    }
  });

export type RegisterFormValues = z.infer<typeof registerSchema>;

export interface PasswordStrengthResult {
  score: number;
  label: "Weak" | "Fair" | "Good" | "Strong";
  checks: ReadonlyArray<{ id: string; label: string; passed: boolean }>;
}

export function getPasswordStrength(password: string): PasswordStrengthResult {
  const checks = [
    {
      id: "length",
      label: "At least 8 characters",
      passed: password.length >= 8,
    },
    {
      id: "upper",
      label: "Uppercase letter",
      passed: /[A-Z]/.test(password),
    },
    {
      id: "lower",
      label: "Lowercase letter",
      passed: /[a-z]/.test(password),
    },
    {
      id: "number",
      label: "Number",
      passed: /[0-9]/.test(password),
    },
    {
      id: "special",
      label: "Special character",
      passed: /[^A-Za-z0-9]/.test(password),
    },
  ] as const;

  const score = checks.filter((check) => check.passed).length;
  const label =
    score <= 2 ? "Weak" : score === 3 ? "Fair" : score === 4 ? "Good" : "Strong";

  return { score, label, checks };
}
