"use client";

import { motion } from "framer-motion";
import { TriangleAlert } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/features/settings/components/confirm-dialog";
import {
  useDeleteAccount,
  useResetPreferences,
} from "@/features/settings/hooks/use-settings";
import { useSettingsStore } from "@/features/settings/store/settings.store";

export function DangerZone() {
  const resetPreferences = useResetPreferences();
  const deleteAccount = useDeleteAccount();
  const setStatusMessage = useSettingsStore((state) => state.setStatusMessage);
  const [resetOpen, setResetOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <Card className="rounded-2xl border border-destructive/30 bg-destructive/5 py-0 ring-0 backdrop-blur-xl">
        <CardContent className="space-y-4 p-5 sm:p-6">
          <div className="flex items-center gap-2">
            <TriangleAlert className="h-4 w-4 text-destructive" aria-hidden="true" />
            <div>
              <h2 className="text-lg font-semibold text-white">Danger Zone</h2>
              <p className="text-sm text-muted-foreground">
                Irreversible account and preference actions.
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row">
            <Button
              type="button"
              variant="outline"
              className="border-amber-400/40 text-amber-200 hover:bg-amber-500/10"
              onClick={() => setResetOpen(true)}
            >
              Reset Preferences
            </Button>
            <Button
              type="button"
              className="bg-destructive text-white hover:bg-destructive/90"
              onClick={() => setDeleteOpen(true)}
            >
              Delete Account
            </Button>
          </div>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={resetOpen}
        title="Reset preferences?"
        description="Interview, AI, notification, and appearance settings will return to defaults."
        confirmLabel="Reset Preferences"
        destructive
        busy={resetPreferences.isPending}
        onCancel={() => setResetOpen(false)}
        onConfirm={async () => {
          await resetPreferences.mutateAsync();
          setResetOpen(false);
          setStatusMessage("Preferences reset to defaults");
        }}
      />

      <ConfirmDialog
        open={deleteOpen}
        title="Delete account?"
        description="This permanently deletes your AgentVox account and associated data."
        confirmLabel="Delete Account"
        destructive
        busy={deleteAccount.isPending}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={async () => {
          await deleteAccount.mutateAsync();
          setDeleteOpen(false);
          setStatusMessage("Account deletion requested (mock)");
        }}
      />
    </motion.div>
  );
}
