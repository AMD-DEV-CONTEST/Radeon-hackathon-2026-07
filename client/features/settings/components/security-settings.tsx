"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { Globe, Loader2, Save, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ConfirmDialog } from "@/features/settings/components/confirm-dialog";
import {
  useLogoutAllDevices,
  useRevokeSession,
  useUpdateSettings,
} from "@/features/settings/hooks/use-settings";
import {
  securitySettingsSchema,
  type SecuritySettingsFormValues,
} from "@/features/settings/schemas/settings.schema";
import { useSettingsStore } from "@/features/settings/store/settings.store";
import type { ActiveSession } from "@/features/settings/types/settings.types";

interface SecuritySettingsProps {
  twoFactorEnabled: boolean;
  sessions: ReadonlyArray<ActiveSession>;
}

export function SecuritySettings({
  twoFactorEnabled,
  sessions,
}: SecuritySettingsProps) {
  const updateSettings = useUpdateSettings();
  const revokeSession = useRevokeSession();
  const logoutAll = useLogoutAllDevices();
  const setStatusMessage = useSettingsStore((state) => state.setStatusMessage);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [revokeId, setRevokeId] = useState<string | null>(null);

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<SecuritySettingsFormValues>({
    resolver: zodResolver(securitySettingsSchema),
    defaultValues: {
      twoFactorEnabled,
      currentPassword: "",
      newPassword: "",
      confirmPassword: "",
    },
  });

  useEffect(() => {
    reset({
      twoFactorEnabled,
      currentPassword: "",
      newPassword: "",
      confirmPassword: "",
    });
  }, [reset, twoFactorEnabled]);

  const onSubmit = handleSubmit(async (values) => {
    await updateSettings.mutateAsync({
      security: { twoFactorEnabled: values.twoFactorEnabled },
    });
    setStatusMessage("Security settings saved");
    reset({
      twoFactorEnabled: values.twoFactorEnabled,
      currentPassword: "",
      newPassword: "",
      confirmPassword: "",
    });
  });

  const busy = isSubmitting || updateSettings.isPending;

  return (
    <div className="space-y-4">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5 sm:p-6">
            <div className="mb-5">
              <h2 className="text-lg font-semibold text-white">Security</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Password, two-factor authentication, and session controls.
              </p>
            </div>

            <form className="space-y-4" onSubmit={onSubmit} noValidate>
              <Controller
                control={control}
                name="twoFactorEnabled"
                render={({ field }) => (
                  <label className="flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-white/5 bg-[#0f1018] p-3">
                    <span>
                      <span className="block text-sm font-medium text-white">
                        Two Factor Authentication
                      </span>
                      <span className="mt-1 block text-xs text-muted-foreground">
                        Require a second factor at sign-in.
                      </span>
                    </span>
                    <Checkbox
                      checked={field.value}
                      onCheckedChange={(checked) => field.onChange(checked)}
                      aria-label="Two factor authentication"
                    />
                  </label>
                )}
              />

              <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-2">
                  <Label htmlFor="currentPassword">Current Password</Label>
                  <Input
                    id="currentPassword"
                    type="password"
                    autoComplete="current-password"
                    {...register("currentPassword")}
                  />
                  {errors.currentPassword ? (
                    <p className="text-xs text-destructive">
                      {errors.currentPassword.message}
                    </p>
                  ) : null}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="newPassword">New Password</Label>
                  <Input
                    id="newPassword"
                    type="password"
                    autoComplete="new-password"
                    {...register("newPassword")}
                  />
                  {errors.newPassword ? (
                    <p className="text-xs text-destructive">
                      {errors.newPassword.message}
                    </p>
                  ) : null}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="confirmPassword">Confirm Password</Label>
                  <Input
                    id="confirmPassword"
                    type="password"
                    autoComplete="new-password"
                    {...register("confirmPassword")}
                  />
                  {errors.confirmPassword ? (
                    <p className="text-xs text-destructive">
                      {errors.confirmPassword.message}
                    </p>
                  ) : null}
                </div>
              </div>

              <div className="flex flex-wrap justify-between gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setLogoutOpen(true)}
                >
                  Logout All Devices
                </Button>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={!isDirty || busy}
                    onClick={() =>
                      reset({
                        twoFactorEnabled,
                        currentPassword: "",
                        newPassword: "",
                        confirmPassword: "",
                      })
                    }
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    className="glow-purple"
                    disabled={!isDirty || busy}
                  >
                    {busy ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Save className="h-4 w-4" aria-hidden="true" />
                    )}
                    Save Changes
                  </Button>
                </div>
              </div>
            </form>
          </CardContent>
        </Card>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.06 }}
      >
        <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
          <CardContent className="p-5 sm:p-6">
            <div className="mb-4 flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" aria-hidden="true" />
              <h2 className="text-xs font-semibold tracking-[0.14em] text-muted-foreground uppercase">
                Active Sessions
              </h2>
            </div>

            <ul className="space-y-3" aria-label="Active sessions">
              {sessions.map((session) => (
                <li
                  key={session.id}
                  className="flex flex-col gap-3 rounded-xl border border-white/5 bg-[#0f1018] p-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15 text-primary">
                      <Globe className="h-4 w-4" aria-hidden="true" />
                    </div>
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-white">
                          {session.device}
                        </p>
                        {session.isCurrent ? (
                          <Badge className="border-sky-400/30 bg-sky-500/15 text-sky-200 tracking-normal normal-case">
                            Current
                          </Badge>
                        ) : null}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {session.location} • {session.ipAddress} •{" "}
                        {session.lastActive}
                      </p>
                    </div>
                  </div>
                  {!session.isCurrent ? (
                    <Button
                      type="button"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      onClick={() => setRevokeId(session.id)}
                    >
                      Revoke
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </motion.div>

      <ConfirmDialog
        open={logoutOpen}
        title="Logout all devices?"
        description="This will end every active session except the current one."
        confirmLabel="Logout All"
        destructive
        busy={logoutAll.isPending}
        onCancel={() => setLogoutOpen(false)}
        onConfirm={async () => {
          await logoutAll.mutateAsync();
          setLogoutOpen(false);
          setStatusMessage("Logged out of all other devices");
        }}
      />

      <ConfirmDialog
        open={revokeId !== null}
        title="Revoke session?"
        description="The selected device will be signed out immediately."
        confirmLabel="Revoke"
        destructive
        busy={revokeSession.isPending}
        onCancel={() => setRevokeId(null)}
        onConfirm={async () => {
          if (!revokeId) {
            return;
          }
          await revokeSession.mutateAsync(revokeId);
          setRevokeId(null);
          setStatusMessage("Session revoked");
        }}
      />
    </div>
  );
}
