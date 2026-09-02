"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Loader2, Mic, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useUpdateSettings } from "@/features/settings/hooks/use-settings";
import {
  deviceSettingsSchema,
  type DeviceSettingsFormValues,
} from "@/features/settings/schemas/settings.schema";
import { useSettingsStore } from "@/features/settings/store/settings.store";
import type { DeviceSettings } from "@/features/settings/types/settings.types";

interface MicrophoneSettingsProps {
  devices: DeviceSettings;
}

export function MicrophoneSettings({ devices }: MicrophoneSettingsProps) {
  const updateSettings = useUpdateSettings();
  const setStatusMessage = useSettingsStore((state) => state.setStatusMessage);
  const [testing, setTesting] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<DeviceSettingsFormValues>({
    resolver: zodResolver(deviceSettingsSchema),
    defaultValues: {
      microphoneId: devices.microphoneId,
      cameraId: devices.cameraId,
      speakerId: devices.speakerId,
    },
  });

  useEffect(() => {
    reset({
      microphoneId: devices.microphoneId,
      cameraId: devices.cameraId,
      speakerId: devices.speakerId,
    });
  }, [devices, reset]);

  const selectedMic = watch("microphoneId");
  const microphones = devices.devices.filter((device) => device.kind === "microphone");
  const speakers = devices.devices.filter((device) => device.kind === "speaker");

  const onSubmit = handleSubmit(async (values) => {
    await updateSettings.mutateAsync({
      devices: {
        microphoneId: values.microphoneId,
        speakerId: values.speakerId,
      },
    });
    setStatusMessage("Microphone settings saved");
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
            <Mic className="h-4 w-4 text-primary" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-semibold text-white">Microphone</h2>
              <p className="text-sm text-muted-foreground">
                Select input and speaker devices for interviews.
              </p>
            </div>
          </div>

          <form className="space-y-4" onSubmit={onSubmit} noValidate>
            <div className="space-y-2">
              <Label htmlFor="microphoneId">Microphone Selection</Label>
              <select
                id="microphoneId"
                className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                {...register("microphoneId")}
              >
                {microphones.map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.label}
                  </option>
                ))}
              </select>
              {errors.microphoneId ? (
                <p className="text-xs text-destructive">
                  {errors.microphoneId.message}
                </p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="speakerId">Speaker Selection</Label>
              <select
                id="speakerId"
                className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                {...register("speakerId")}
              >
                {speakers.map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={testing}
                onClick={() => {
                  setTesting(true);
                  setStatusMessage(
                    `Testing microphone ${selectedMic} (mock tone)`
                  );
                  window.setTimeout(() => setTesting(false), 1200);
                }}
              >
                {testing ? "Testing..." : "Test Microphone"}
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
