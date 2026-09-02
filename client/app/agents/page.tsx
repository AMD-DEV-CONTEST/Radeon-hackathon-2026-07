import type { Metadata } from "next";
import { Suspense } from "react";

import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { AgentsSkeleton } from "@/features/agents/components/agents-skeleton";
import { AgentsView } from "@/features/agents/components/agents-view";

export const metadata: Metadata = {
  title: "Agent Monitoring — AgentVox",
  description:
    "Real-time multi-agent observability with workflow traces, latency, resources, and execution logs.",
};

export default function AgentMonitoringPage() {
  return (
    <Suspense
      fallback={
        <DashboardLayout
          breadcrumbs={[
            { label: "Interview Management" },
            { label: "Active Sessions", current: true },
          ]}
        >
          <AgentsSkeleton />
        </DashboardLayout>
      }
    >
      <AgentsView />
    </Suspense>
  );
}
