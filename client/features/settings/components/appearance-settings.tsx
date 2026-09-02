"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Loader2, Save } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useUpdateSettings } from "@/features/settings/hooks/use-settings";
import {
  appearanceSettingsSchema,
  type AppearanceSettingsFormValues,
} from "@/features/settings/schemas/settings.schema";
import { useSettingsStore } from "@/features/settings/store/settings.store";
import type { AppearanceSettings as AppearanceSettingsData } from "@/features/settings/types/settings.types";

interface AppearanceSettingsProps {
  appearance: AppearanceSettingsData;
}

export function AppearanceSettings({ appearance }: AppearanceSettingsProps) {
  const updateSettings = useUpdateSettings();
  const setStatusMessage = useSettingsStore((state) => state.setStatusMessage);

  const {
    register,
    handleSubmit,
    reset,
    formState: { isDirty, isSubmitting },
  } = useForm<AppearanceSettingsFormValues>({
    resolver: zodResolver(appearanceSettingsSchema),
    defaultValues: appearance,
  });

  useEffect(() => {
    reset(appearance);
  }, [appearance, reset]);

  const onSubmit = handleSubmit(async (values) => {
    await updateSettings.mutateAsync({ appearance: values });
    setStatusMessage("Appearance settings saved");
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
            <h2 className="text-lg font-semibold text-white">Appearance</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Theme, accent color, and typography density.
            </p>
          </div>

          <form className="grid gap-4 sm:grid-cols-3" onSubmit={onSubmit}>
            <div className="space-y-2">
              <Label htmlFor="theme">Theme</Label>
              <select
                id="theme"
                className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                {...register("theme")}
              >
                <option value="dark">Dark</option>
                <option value="light">Light</option>
                <option value="system">System</option>
              </select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="accentColor">Accent Color</Label>
              <select
                id="accentColor"
                className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                {...register("accentColor")}
              >
                <option value="purple">Purple</option>
                <option value="blue">Blue</option>
                <option value="cyan">Cyan</option>
                <option value="rose">Rose</option>
              </select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="fontSize">Font Size</Label>
              <select
                id="fontSize"
                className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                {...register("fontSize")}
              >
                <option value="sm">Small</option>
                <option value="md">Medium</option>
                <option value="lg">Large</option>
              </select>
            </div>

            <div className="flex justify-end gap-2 sm:col-span-3">
              <Button
                type="button"
                variant="ghost"
                disabled={!isDirty || busy}
                onClick={() => reset(appearance)}
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
