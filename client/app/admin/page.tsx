import type { Metadata } from "next";

import { AdminView } from "@/features/admin/components/admin-view";

export const metadata: Metadata = {
  title: "Admin Dashboard — AgentVox",
  description:
    "Platform admin dashboard for interviews, AI agents, system health, and analytics.",
};

export default function AdminDashboardPage() {
  return <AdminView />;
}
