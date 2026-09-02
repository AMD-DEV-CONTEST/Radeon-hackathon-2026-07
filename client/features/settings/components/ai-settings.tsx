"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Bot, Loader2, Save } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUpdateSettings } from "@/features/settings/hooks/use-settings";
import {
  aiSettingsSchema,
  type AiSettingsFormValues,
} from "@/features/settings/schemas/settings.schema";
import { useSettingsStore } from "@/features/settings/store/settings.store";
import type { AiSettings as AiSettingsData } from "@/features/settings/types/settings.types";

interface AiSettingsProps {
  ai: AiSettingsData;
}

export function AiSettings({ ai }: AiSettingsProps) {
  const updateSettings = useUpdateSettings();
  const setStatusMessage = useSettingsStore((state) => state.setStatusMessage);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<AiSettingsFormValues>({
    resolver: zodResolver(aiSettingsSchema),
    defaultValues: ai,
  });

  useEffect(() => {
    reset(ai);
  }, [ai, reset]);

  const creativity = watch("creativity");
  const temperature = watch("temperature");

  const onSubmit = handleSubmit(async (values) => {
    await updateSettings.mutateAsync({ ai: values });
    setStatusMessage("AI settings saved");
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
          <div className="mb-5 flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-semibold text-white">AI Settings</h2>
              <p className="text-sm text-muted-foreground">
                Tune model selection and response behavior.
              </p>
            </div>
          </div>

          <form className="grid gap-4 sm:grid-cols-2" onSubmit={onSubmit} noValidate>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="preferredModel">Preferred AI Model</Label>
              <select
                id="preferredModel"
                className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                {...register("preferredModel")}
              >
                <option value="vox-1">Vox-1</option>
                <option value="vox-1-pro">Vox-1 Pro</option>
                <option value="vox-lite">Vox Lite</option>
              </select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="creativity">Creativity ({creativity})</Label>
              <Input
                id="creativity"
                type="range"
                min={0}
                max={100}
                {...register("creativity", { valueAsNumber: true })}
              />
              {errors.creativity ? (
                <p className="text-xs text-destructive">
                  {errors.creativity.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="temperature">Temperature ({temperature})</Label>
              <Input
                id="temperature"
                type="number"
                step="0.1"
                min={0}
                max={2}
                {...register("temperature", { valueAsNumber: true })}
              />
              {errors.temperature ? (
                <p className="text-xs text-destructive">
                  {errors.temperature.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="responseStyle">Response Style</Label>
              <select
                id="responseStyle"
                className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                {...register("responseStyle")}
              >
                <option value="concise">Concise</option>
                <option value="balanced">Balanced</option>
                <option value="detailed">Detailed</option>
              </select>
            </div>

            <div className="flex justify-end gap-2 sm:col-span-2">
              <Button
                type="button"
                variant="ghost"
                disabled={!isDirty || busy}
                onClick={() => reset(ai)}
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
