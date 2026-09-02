"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Eye, EyeOff, KeyRound, Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUpdateSettings } from "@/features/settings/hooks/use-settings";
import {
  apiKeySettingsSchema,
  type ApiKeySettingsFormValues,
} from "@/features/settings/schemas/settings.schema";
import { useSettingsStore } from "@/features/settings/store/settings.store";
import type { ApiKeySettings as ApiKeySettingsData } from "@/features/settings/types/settings.types";

interface ApiKeySettingsProps {
  apiKeys: ApiKeySettingsData;
}

export function ApiKeySettings({ apiKeys }: ApiKeySettingsProps) {
  const updateSettings = useUpdateSettings();
  const setStatusMessage = useSettingsStore((state) => state.setStatusMessage);
  const [visible, setVisible] = useState({
    openaiKey: false,
    amdKey: false,
    deepgramKey: false,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<ApiKeySettingsFormValues>({
    resolver: zodResolver(apiKeySettingsSchema),
    defaultValues: apiKeys,
  });

  useEffect(() => {
    reset(apiKeys);
  }, [apiKeys, reset]);

  const onSubmit = handleSubmit(async (values) => {
    await updateSettings.mutateAsync({ apiKeys: values });
    setStatusMessage("API keys saved");
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
            <KeyRound className="h-4 w-4 text-primary" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-semibold text-white">API Keys</h2>
              <p className="text-sm text-muted-foreground">
                Keys are stored securely and displayed masked by default.
              </p>
            </div>
          </div>

          <form className="space-y-4" onSubmit={onSubmit} noValidate>
            {(
              [
                ["openaiKey", "OpenAI Key"],
                ["amdKey", "AMD API Key"],
                ["deepgramKey", "Deepgram Key"],
              ] as const
            ).map(([field, label]) => (
              <div key={field} className="space-y-2">
                <Label htmlFor={field}>{label}</Label>
                <div className="relative">
                  <Input
                    id={field}
                    type={visible[field] ? "text" : "password"}
                    className="pr-10 font-mono"
                    autoComplete="off"
                    {...register(field)}
                  />
                  <button
                    type="button"
                    className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground hover:text-white"
                    aria-label={
                      visible[field] ? `Hide ${label}` : `Show ${label}`
                    }
                    onClick={() =>
                      setVisible((previous) => ({
                        ...previous,
                        [field]: !previous[field],
                      }))
                    }
                  >
                    {visible[field] ? (
                      <EyeOff className="h-4 w-4" aria-hidden="true" />
                    ) : (
                      <Eye className="h-4 w-4" aria-hidden="true" />
                    )}
                  </button>
                </div>
                {errors[field] ? (
                  <p className="text-xs text-destructive">
                    {errors[field]?.message}
                  </p>
                ) : null}
              </div>
            ))}

            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                disabled={!isDirty || busy}
                onClick={() => reset(apiKeys)}
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
