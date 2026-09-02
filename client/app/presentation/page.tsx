import type { Metadata } from "next";
import { Suspense } from "react";

import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { PresentationSkeleton } from "@/features/presentation/components/presentation-skeleton";
import { PresentationView } from "@/features/presentation/components/presentation-view";

export const metadata: Metadata = {
  title: "Presentation Dashboard — AgentVox",
  description:
    "Executive interview presentation with competency radar, AI insights, hiring recommendation, and export actions.",
};

export default function PresentationDashboardPage() {
  return (
    <Suspense
      fallback={
        <DashboardLayout
          breadcrumbs={[
            { label: "Interview Management" },
            { label: "Active Sessions", current: true },
          ]}
        >
          <PresentationSkeleton />
        </DashboardLayout>
      }
    >
      <PresentationView />
    </Suspense>
  );
}
