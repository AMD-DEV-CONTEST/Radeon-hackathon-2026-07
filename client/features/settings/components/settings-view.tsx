"use client";

import { AnimatePresence, motion } from "framer-motion";

import { EmptyState } from "@/components/feedback/empty-state";
import { QueryErrorState } from "@/components/feedback/query-error-state";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { AccountSettings, InterviewSettingsPanel } from "@/features/settings/components/account-settings";
import { AiSettings } from "@/features/settings/components/ai-settings";
import { ApiKeySettings } from "@/features/settings/components/api-key-settings";
import { AppearanceSettings } from "@/features/settings/components/appearance-settings";
import { CameraSettings } from "@/features/settings/components/camera-settings";
import { DangerZone } from "@/features/settings/components/danger-zone";
import { MicrophoneSettings } from "@/features/settings/components/microphone-settings";
import { NotificationSettings } from "@/features/settings/components/notification-settings";
import { ProfileSettings } from "@/features/settings/components/profile-settings";
import { SecuritySettings } from "@/features/settings/components/security-settings";
import { SettingsHeader } from "@/features/settings/components/settings-header";
import { SettingsSidebar } from "@/features/settings/components/settings-sidebar";
import { SettingsSkeleton } from "@/features/settings/components/settings-skeleton";
import { useSettings } from "@/features/settings/hooks/use-settings";
import { useSettingsStore } from "@/features/settings/store/settings.store";
import { normalizeApiError } from "@/services/api/errors";

export function SettingsView() {
  const { data, isLoading, isError, error, refetch, isFetching } = useSettings();
  const activeSection = useSettingsStore((state) => state.activeSection);
  const statusMessage = useSettingsStore((state) => state.statusMessage);

  return (
    <DashboardLayout
      breadcrumbs={[
        { label: "Interview Management" },
        { label: "Active Sessions", current: true },
      ]}
    >
      {isLoading ? <SettingsSkeleton /> : null}

      {!isLoading && isError ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <QueryErrorState
            title="Unable to load settings"
            message={normalizeApiError(error).message}
            onRetry={() => {
              void refetch();
            }}
          />
        </div>
      ) : null}

      {!isLoading && !isError && !data ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="Settings unavailable"
            description="Sign in and complete onboarding to manage account preferences."
          />
        </div>
      ) : null}

      {!isLoading && !isError && data ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3 }}
          className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6"
        >
          <SettingsHeader />

          {isFetching ? (
            <p className="text-xs text-muted-foreground">Syncing settings...</p>
          ) : null}

          <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
            <SettingsSidebar storage={data.storage} />

            <div className="min-w-0 space-y-4">
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeSection}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.22 }}
                >
                  {activeSection === "profile" ? (
                    <ProfileSettings profile={data.profile} />
                  ) : null}
                  {activeSection === "account" ? (
                    <AccountSettings
                      profile={data.profile}
                      storage={data.storage}
                    />
                  ) : null}
                  {activeSection === "notifications" ? (
                    <NotificationSettings notifications={data.notifications} />
                  ) : null}
                  {activeSection === "appearance" ? (
                    <AppearanceSettings appearance={data.appearance} />
                  ) : null}
                  {activeSection === "interview" ? (
                    <InterviewSettingsPanel interview={data.interview} />
                  ) : null}
                  {activeSection === "ai" ? <AiSettings ai={data.ai} /> : null}
                  {activeSection === "apiKeys" ? (
                    <ApiKeySettings apiKeys={data.apiKeys} />
                  ) : null}
                  {activeSection === "security" ? (
                    <SecuritySettings
                      twoFactorEnabled={data.security.twoFactorEnabled}
                      sessions={data.sessions}
                    />
                  ) : null}
                  {activeSection === "devices" ? (
                    <div className="space-y-4">
                      <MicrophoneSettings devices={data.devices} />
                      <CameraSettings devices={data.devices} />
                    </div>
                  ) : null}
                  {activeSection === "danger" ? <DangerZone /> : null}
                </motion.div>
              </AnimatePresence>

              <p className="sr-only" role="status" aria-live="polite">
                {statusMessage}
              </p>
              {statusMessage ? (
                <p className="text-xs text-muted-foreground">{statusMessage}</p>
              ) : null}
            </div>
          </div>
        </motion.div>
      ) : null}
    </DashboardLayout>
  );
}
