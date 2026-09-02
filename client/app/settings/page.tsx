import type { Metadata } from "next";

import { SettingsView } from "@/features/settings/components/settings-view";

export const metadata: Metadata = {
  title: "Command Settings — AgentVox",
  description:
    "Manage profile, interview preferences, devices, AI behavior, API keys, and security.",
};

export default function SettingsPage() {
  return <SettingsView />;
}
