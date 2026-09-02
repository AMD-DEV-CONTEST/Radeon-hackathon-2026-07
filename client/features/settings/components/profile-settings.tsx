"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import {
  Briefcase,
  Loader2,
  Mail,
  Save,
  Upload,
  UserRound,
} from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUpdateSettings } from "@/features/settings/hooks/use-settings";
import {
  profileSettingsSchema,
  type ProfileSettingsFormValues,
} from "@/features/settings/schemas/settings.schema";
import { useSettingsStore } from "@/features/settings/store/settings.store";
import type { UserProfileSettings } from "@/features/settings/types/settings.types";

interface ProfileSettingsProps {
  profile: UserProfileSettings;
}

export function ProfileSettings({ profile }: ProfileSettingsProps) {
  const updateSettings = useUpdateSettings();
  const setStatusMessage = useSettingsStore((state) => state.setStatusMessage);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<ProfileSettingsFormValues>({
    resolver: zodResolver(profileSettingsSchema),
    defaultValues: profile,
  });

  useEffect(() => {
    reset(profile);
  }, [profile, reset]);

  const onSubmit = handleSubmit(async (values) => {
    await updateSettings.mutateAsync({ profile: values });
    setStatusMessage("Profile settings saved");
  });

  const busy = isSubmitting || updateSettings.isPending;

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      whileHover={{ y: -2 }}
    >
      <Card className="rounded-2xl border border-white/10 bg-[#12121a]/80 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-5">
            <h2 className="text-lg font-semibold text-white">User Profile</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Update your identity details used across interviews and reports.
            </p>
          </div>

          <form className="space-y-5" onSubmit={onSubmit} noValidate>
            <div className="flex items-center gap-4">
              <div className="relative">
                <div
                  className="flex h-20 w-20 items-center justify-center rounded-2xl border border-white/10 bg-[#0f1018] text-xl font-bold text-white"
                  aria-hidden="true"
                >
                  {profile.avatarInitials}
                </div>
                <button
                  type="button"
                  className="absolute -right-1 -bottom-1 flex h-8 w-8 items-center justify-center rounded-full bg-primary text-white shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                  aria-label="Upload avatar"
                  onClick={() => setStatusMessage("Avatar upload ready (mock)")}
                >
                  <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </div>
              <div>
                <p className="text-sm font-medium text-white">{profile.fullName}</p>
                <p className="text-xs text-muted-foreground">{profile.jobTitle}</p>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="fullName">Full Name</Label>
                <div className="relative">
                  <UserRound className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input id="fullName" className="pl-9" {...register("fullName")} />
                </div>
                {errors.fullName ? (
                  <p className="text-xs text-destructive">{errors.fullName.message}</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="jobTitle">Job Title</Label>
                <div className="relative">
                  <Briefcase className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input id="jobTitle" className="pl-9" {...register("jobTitle")} />
                </div>
                {errors.jobTitle ? (
                  <p className="text-xs text-destructive">{errors.jobTitle.message}</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="email">Work Email</Label>
                <div className="relative">
                  <Mail className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input id="email" type="email" className="pl-9" {...register("email")} />
                </div>
                {errors.email ? (
                  <p className="text-xs text-destructive">{errors.email.message}</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="phone">Phone</Label>
                <Input id="phone" {...register("phone")} />
                {errors.phone ? (
                  <p className="text-xs text-destructive">{errors.phone.message}</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="preferredRole">Preferred Role</Label>
                <Input id="preferredRole" {...register("preferredRole")} />
                {errors.preferredRole ? (
                  <p className="text-xs text-destructive">
                    {errors.preferredRole.message}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="experience">Experience</Label>
                <Input id="experience" {...register("experience")} />
                {errors.experience ? (
                  <p className="text-xs text-destructive">
                    {errors.experience.message}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="timezone">Timezone</Label>
                <select
                  id="timezone"
                  className="flex h-10 w-full rounded-lg border border-input bg-transparent px-3 text-sm text-white outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  {...register("timezone")}
                >
                  <option value="Pacific Standard Time (UTC-8)">
                    Pacific Standard Time (UTC-8)
                  </option>
                  <option value="Eastern Standard Time (UTC-5)">
                    Eastern Standard Time (UTC-5)
                  </option>
                  <option value="India Standard Time (UTC+5:30)">
                    India Standard Time (UTC+5:30)
                  </option>
                  <option value="Greenwich Mean Time (UTC+0)">
                    Greenwich Mean Time (UTC+0)
                  </option>
                </select>
                {errors.timezone ? (
                  <p className="text-xs text-destructive">
                    {errors.timezone.message}
                  </p>
                ) : null}
              </div>
            </div>

            <div className="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                disabled={!isDirty || busy}
                onClick={() => reset(profile)}
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
