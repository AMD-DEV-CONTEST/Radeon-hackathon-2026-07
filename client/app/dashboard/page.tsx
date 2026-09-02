import type { Metadata } from "next";

import { DashboardView } from "@/features/dashboard/components/dashboard-view";

export const metadata: Metadata = {
  title: "Candidate Dashboard — AgentVox",
  description:
    "Candidate workspace with interview stats, performance trends, upcoming sessions, and AI suggestions.",
};

export default function CandidateDashboardPage() {
  return <DashboardView />;
}
