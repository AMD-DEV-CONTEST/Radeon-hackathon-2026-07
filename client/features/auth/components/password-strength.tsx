"use client";

import { motion } from "framer-motion";

import {
  getPasswordStrength,
  type PasswordStrengthResult,
} from "@/features/auth/schemas/register.schema";
import { cn } from "@/lib/utils";

interface PasswordStrengthProps {
  password: string;
}

function strengthBarClass(result: PasswordStrengthResult): string {
  if (result.score <= 2) {
    return "bg-destructive";
  }
  if (result.score === 3) {
    return "bg-amber-400";
  }
  if (result.score === 4) {
    return "bg-sky-400";
  }
  return "bg-emerald-400";
}

export function PasswordStrength({ password }: PasswordStrengthProps) {
  const result = getPasswordStrength(password);
  const percent = (result.score / 5) * 100;

  return (
    <div className="space-y-2" aria-live="polite">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="text-muted-foreground">Password strength</span>
        <span
          className={cn(
            "font-semibold",
            result.score <= 2
              ? "text-destructive"
              : result.score === 3
                ? "text-amber-300"
                : result.score === 4
                  ? "text-sky-300"
                  : "text-emerald-300"
          )}
        >
          {password.length === 0 ? "—" : result.label}
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={5}
        aria-valuenow={result.score}
        aria-label="Password strength"
      >
        <motion.div
          className={cn("h-full rounded-full", strengthBarClass(result))}
          initial={false}
          animate={{ width: `${password.length === 0 ? 0 : percent}%` }}
          transition={{ duration: 0.25 }}
        />
      </div>
      <ul className="grid gap-1 sm:grid-cols-2">
        {result.checks.map((check) => (
          <li
            key={check.id}
            className={cn(
              "text-[11px]",
              check.passed ? "text-emerald-300" : "text-muted-foreground"
            )}
          >
            {check.passed ? "✓" : "○"} {check.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
