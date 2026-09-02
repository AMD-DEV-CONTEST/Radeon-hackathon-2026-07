"use client";

import { motion } from "framer-motion";
import { Settings2 } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DifficultySelector } from "@/features/interview/components/difficulty-selector";
import type {
  InterviewConfiguration as InterviewConfigurationData,
  InterviewType,
} from "@/features/interview/types/interview.types";
import { cn } from "@/lib/utils";

const INTERVIEW_TYPES: ReadonlyArray<{ value: InterviewType; label: string }> =
  [
    { value: "technical", label: "Technical" },
    { value: "behavioral", label: "Behavioral" },
    { value: "mixed", label: "Mixed" },
  ];

interface InterviewConfigurationProps {
  value: InterviewConfigurationData;
  disabled?: boolean;
  onChange: (value: InterviewConfigurationData) => void;
}

export function InterviewConfiguration({
  value,
  disabled = false,
  onChange,
}: InterviewConfigurationProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.06 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-5 p-5">
          <div className="flex items-center gap-2">
            <Settings2 className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Interview Configuration
            </h2>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="interview-role">Interview Role</Label>
              <Input
                id="interview-role"
                value={value.role}
                disabled={disabled}
                onChange={(event) =>
                  onChange({ ...value, role: event.target.value })
                }
                placeholder="e.g. Principal Engineer"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="interview-duration">Interview Duration (min)</Label>
              <Input
                id="interview-duration"
                type="number"
                min={15}
                max={180}
                value={value.durationMinutes}
                disabled={disabled}
                onChange={(event) =>
                  onChange({
                    ...value,
                    durationMinutes: Number(event.target.value) || 0,
                  })
                }
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="question-count">Question Count</Label>
              <Input
                id="question-count"
                type="number"
                min={4}
                max={30}
                value={value.questionCount}
                disabled={disabled}
                onChange={(event) =>
                  onChange({
                    ...value,
                    questionCount: Number(event.target.value) || 0,
                  })
                }
              />
            </div>
          </div>

          <DifficultySelector
            value={value.difficulty}
            disabled={disabled}
            onChange={(difficulty) => onChange({ ...value, difficulty })}
          />

          <fieldset className="space-y-2" disabled={disabled}>
            <legend className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
              Interview Type
            </legend>
            <div
              className="grid grid-cols-3 gap-2"
              role="radiogroup"
              aria-label="Interview type"
            >
              {INTERVIEW_TYPES.map((option) => {
                const selected = option.value === value.interviewType;

                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    disabled={disabled}
                    onClick={() =>
                      onChange({ ...value, interviewType: option.value })
                    }
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
        </CardContent>
      </Card>
    </motion.div>
  );
}
