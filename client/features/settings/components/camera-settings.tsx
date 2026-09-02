"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Camera, Loader2, Save } from "lucide-react";
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

interface CameraSettingsProps {
  devices: DeviceSettings;
}

export function CameraSettings({ devices }: CameraSettingsProps) {
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

  const selectedCamera = watch("cameraId");
  const cameras = devices.devices.filter((device) => device.kind === "camera");

  const onSubmit = handleSubmit(async (values) => {
    await updateSettings.mutateAsync({
      devices: { cameraId: values.cameraId },
    });
    setStatusMessage("Camera settings saved");
  });

  const busy = isSubmitting || updateSettings.isPending;

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.05 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-5 flex items-center gap-2">
            <Camera className="h-4 w-4 text-primary" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-semibold text-white">Camera</h2>
              <p className="text-sm text-muted-foreground">
                Choose and validate your interview camera feed.
              </p>
            </div>
          </div>

          <form className="space-y-4" onSubmit={onSubmit} noValidate>
            <div className="space-y-2">
              <Label htmlFor="cameraId">Camera Selection</Label>
              <select
                id="cameraId"
                className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                {...register("cameraId")}
              >
                {cameras.map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.label}
                  </option>
                ))}
              </select>
              {errors.cameraId ? (
                <p className="text-xs text-destructive">
                  {errors.cameraId.message}
                </p>
              ) : null}
            </div>

            <div
              className="relative flex aspect-video items-center justify-center overflow-hidden rounded-xl border border-white/10 bg-gradient-to-br from-[#1a1430] to-[#0f1018]"
              role="img"
              aria-label="Camera preview feed"
            >
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(139,92,246,0.25),transparent_45%)]" />
              <div className="relative text-center">
                <div className="mx-auto mb-2 h-16 w-16 rounded-full border border-primary/40 bg-primary/20" />
                <p className="text-sm font-medium text-white">Live Preview Ready</p>
                <p className="text-xs text-muted-foreground">
                  Selected:{" "}
                  {cameras.find((camera) => camera.id === selectedCamera)?.label ??
                    "None"}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={testing}
                onClick={() => {
                  setTesting(true);
                  setStatusMessage(`Testing camera ${selectedCamera} (mock)`);
                  window.setTimeout(() => setTesting(false), 1200);
                }}
              >
                {testing ? "Testing..." : "Test Camera"}
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
