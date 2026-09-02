"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Loader2, Save } from "lucide-react";
import { useEffect } from "react";
import { Controller, useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { useUpdateSettings } from "@/features/settings/hooks/use-settings";
import {
  notificationSettingsSchema,
  type NotificationSettingsFormValues,
} from "@/features/settings/schemas/settings.schema";
import { useSettingsStore } from "@/features/settings/store/settings.store";
import type { NotificationSettings as NotificationSettingsData } from "@/features/settings/types/settings.types";

interface NotificationSettingsProps {
  notifications: NotificationSettingsData;
}

const TOGGLES: ReadonlyArray<{
  key: keyof NotificationSettingsFormValues;
  label: string;
  description: string;
}> = [
  {
    key: "email",
    label: "Email",
    description: "Receive interview and report updates by email.",
  },
  {
    key: "push",
    label: "Push",
    description: "Browser push alerts for live session events.",
  },
  {
    key: "interviewReminder",
    label: "Interview Reminder",
    description: "Reminders before scheduled interviews.",
  },
  {
    key: "weeklySummary",
    label: "Weekly Summary",
    description: "Weekly digest of practice and score trends.",
  },
];

export function NotificationSettings({
  notifications,
}: NotificationSettingsProps) {
  const updateSettings = useUpdateSettings();
  const setStatusMessage = useSettingsStore((state) => state.setStatusMessage);

  const {
    control,
    handleSubmit,
    reset,
    formState: { isDirty, isSubmitting },
  } = useForm<NotificationSettingsFormValues>({
    resolver: zodResolver(notificationSettingsSchema),
    defaultValues: notifications,
  });

  useEffect(() => {
    reset(notifications);
  }, [notifications, reset]);

  const onSubmit = handleSubmit(async (values) => {
    await updateSettings.mutateAsync({ notifications: values });
    setStatusMessage("Notification preferences saved");
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
            <h2 className="text-lg font-semibold text-white">Notifications</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Choose how AgentVox keeps you informed.
            </p>
          </div>

          <form className="space-y-4" onSubmit={onSubmit}>
            {TOGGLES.map((item) => (
              <Controller
                key={item.key}
                control={control}
                name={item.key}
                render={({ field }) => (
                  <label className="flex cursor-pointer items-start justify-between gap-4 rounded-xl border border-white/5 bg-[#0f1018] p-3">
                    <span>
                      <span className="block text-sm font-medium text-white">
                        {item.label}
                      </span>
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {item.description}
                      </span>
                    </span>
                    <Checkbox
                      checked={field.value}
                      onCheckedChange={(checked) => field.onChange(checked)}
                      aria-label={item.label}
                    />
                  </label>
                )}
              />
            ))}

            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                disabled={!isDirty || busy}
                onClick={() => reset(notifications)}
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
