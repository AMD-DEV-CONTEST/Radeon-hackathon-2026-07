import type { Metadata } from "next";
import { Suspense } from "react";

import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { PlanningSkeleton } from "@/features/interview/components/planning-skeleton";
import { PlanningView } from "@/features/interview/components/planning-view";

export const metadata: Metadata = {
  title: "Interview Planning — AgentVox",
  description:
    "Configure interview orchestration, multi-agent planning, and session readiness.",
};

export default function InterviewPlanningPage() {
  return (
    <Suspense
      fallback={
        <DashboardLayout
          breadcrumbs={[
            { label: "Interview Management" },
            { label: "Active Sessions", current: true },
          ]}
        >
          <PlanningSkeleton />
        </DashboardLayout>
      }
    >
      <PlanningView />
    </Suspense>
  );
}
