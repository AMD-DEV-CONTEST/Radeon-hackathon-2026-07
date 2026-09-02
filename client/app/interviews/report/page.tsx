import type { Metadata } from "next";
import { Suspense } from "react";

import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { ReportSkeleton } from "@/features/report/components/report-skeleton";
import { ReportView } from "@/features/report/components/report-view";

export const metadata: Metadata = {
  title: "Interview Report — AgentVox",
  description:
    "AI interview report with competency matrix, performance pulse, strengths, and hiring recommendation.",
};

export default function InterviewReportPage() {
  return (
    <Suspense
      fallback={
        <DashboardLayout
          breadcrumbs={[
            { label: "Interview Management" },
            { label: "Active Sessions", current: true },
          ]}
        >
          <ReportSkeleton />
        </DashboardLayout>
      }
    >
      <ReportView />
    </Suspense>
  );
}
