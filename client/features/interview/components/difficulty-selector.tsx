"use client";

import type { InterviewDifficulty } from "@/features/interview/types/interview.types";
import { cn } from "@/lib/utils";

const DIFFICULTY_OPTIONS: ReadonlyArray<{
  value: InterviewDifficulty;
  label: string;
}> = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
  { value: "extreme", label: "Extreme" },
];

interface DifficultySelectorProps {
  value: InterviewDifficulty;
  disabled?: boolean;
  onChange: (value: InterviewDifficulty) => void;
}

export function DifficultySelector({
  value,
  disabled = false,
  onChange,
}: DifficultySelectorProps) {
  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
        Difficulty
      </legend>
      <div
        className="grid grid-cols-2 gap-2 sm:grid-cols-4"
        role="radiogroup"
        aria-label="Interview difficulty"
      >
        {DIFFICULTY_OPTIONS.map((option) => {
          const selected = option.value === value;

          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              onClick={() => onChange(option.value)}
              className={cn(
                "h-10 rounded-lg border px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
                selected
                  ? "border-primary/50 bg-primary/15 text-white"
                  : "border-border/70 bg-[#0f1018] text-muted-foreground hover:border-primary/30 hover:text-white",
                disabled && "cursor-not-allowed opacity-60"
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
