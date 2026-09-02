"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Loader2, Save } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUpdateSettings } from "@/features/settings/hooks/use-settings";
import {
  interviewSettingsSchema,
  type InterviewSettingsFormValues,
} from "@/features/settings/schemas/settings.schema";
import { useSettingsStore } from "@/features/settings/store/settings.store";
import type {
  InterviewPreferenceSettings,
  StorageUsage,
  UserProfileSettings,
} from "@/features/settings/types/settings.types";

interface AccountSettingsProps {
  profile: UserProfileSettings;
  storage: StorageUsage;
}

interface InterviewSettingsPanelProps {
  interview: InterviewPreferenceSettings;
}

export function AccountSettings({ profile, storage }: AccountSettingsProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="space-y-4"
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5 sm:p-6">
          <div>
            <h2 className="text-lg font-semibold text-white">Account</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Core account identity and workspace allocation.
            </p>
          </div>
          <dl className="grid gap-3 sm:grid-cols-2 text-sm">
            <div className="rounded-xl border border-white/5 bg-[#0f1018] p-3">
              <dt className="text-muted-foreground">Account Email</dt>
              <dd className="mt-1 font-medium text-white">{profile.email}</dd>
            </div>
            <div className="rounded-xl border border-white/5 bg-[#0f1018] p-3">
              <dt className="text-muted-foreground">Phone</dt>
              <dd className="mt-1 font-medium text-white">{profile.phone}</dd>
            </div>
            <div className="rounded-xl border border-white/5 bg-[#0f1018] p-3">
              <dt className="text-muted-foreground">Preferred Role</dt>
              <dd className="mt-1 font-medium text-white">
                {profile.preferredRole}
              </dd>
            </div>
            <div className="rounded-xl border border-white/5 bg-[#0f1018] p-3">
              <dt className="text-muted-foreground">Storage</dt>
              <dd className="mt-1 font-medium text-white">
                {storage.usedGb}GB / {storage.totalGb}GB ({storage.percent}%)
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </motion.div>
  );
}

export function InterviewSettingsPanel({
  interview,
}: InterviewSettingsPanelProps) {
  const updateSettings = useUpdateSettings();
  const setStatusMessage = useSettingsStore((state) => state.setStatusMessage);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<InterviewSettingsFormValues>({
    resolver: zodResolver(interviewSettingsSchema),
    defaultValues: interview,
  });

  useEffect(() => {
    reset(interview);
  }, [interview, reset]);

  const onSubmit = handleSubmit(async (values) => {
    await updateSettings.mutateAsync({ interview: values });
    setStatusMessage("Interview preferences saved");
  });

  const busy = isSubmitting || updateSettings.isPending;

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-5">
            <h2 className="text-lg font-semibold text-white">
              Interview Preferences
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Control difficulty, pacing, and AI interviewer personality.
            </p>
          </div>

          <form className="grid gap-4 sm:grid-cols-2" onSubmit={onSubmit} noValidate>
            <div className="space-y-2">
              <Label htmlFor="preferredDifficulty">Preferred Difficulty</Label>
              <select
                id="preferredDifficulty"
                className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                {...register("preferredDifficulty")}
              >
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
                <option value="adaptive">Adaptive</option>
              </select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="interviewDurationMinutes">
                Interview Duration (minutes)
              </Label>
              <Input
                id="interviewDurationMinutes"
                type="number"
                {...register("interviewDurationMinutes", { valueAsNumber: true })}
              />
              {errors.interviewDurationMinutes ? (
                <p className="text-xs text-destructive">
                  {errors.interviewDurationMinutes.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="questionCount">Question Count</Label>
              <Input
                id="questionCount"
                type="number"
                {...register("questionCount", { valueAsNumber: true })}
              />
              {errors.questionCount ? (
                <p className="text-xs text-destructive">
                  {errors.questionCount.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="voiceSpeed">Voice Speed</Label>
              <Input
                id="voiceSpeed"
                type="number"
                step="0.1"
                {...register("voiceSpeed", { valueAsNumber: true })}
              />
              {errors.voiceSpeed ? (
                <p className="text-xs text-destructive">
                  {errors.voiceSpeed.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="aiPersonality">AI Personality</Label>
              <select
                id="aiPersonality"
                className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                {...register("aiPersonality")}
              >
                <option value="coach">Coach</option>
                <option value="strict">Strict</option>
                <option value="neutral">Neutral</option>
                <option value="friendly">Friendly</option>
              </select>
            </div>

            <div className="flex justify-end gap-2 sm:col-span-2">
              <Button
                type="button"
                variant="ghost"
                disabled={!isDirty || busy}
                onClick={() => reset(interview)}
              >
                Cancel
              </Button>
              <Button type="submit" className="glow-purple" disabled={!isDirty || busy}>
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Save className="h-4 w-4" aria-hidden="true" />
                )}
                Save Changes
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </motion.div>
  );
}
