import type { Metadata } from "next";
import { Suspense } from "react";

import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { DossierSkeleton } from "@/features/candidate/components/dossier-skeleton";
import { DossierView } from "@/features/candidate/components/dossier-view";

export const metadata: Metadata = {
  title: "Candidate Dossier — AgentVox",
  description:
    "AI-powered candidate dossier with competency matrix, strengths, gaps, and interview roadmap.",
};

export default function CandidateDossierPage() {
  return (
    <Suspense
      fallback={
        <DashboardLayout
          breadcrumbs={[
            { label: "Interview Management" },
            { label: "Active Sessions", current: true },
          ]}
        >
          <DossierSkeleton />
        </DashboardLayout>
      }
    >
      <DossierView />
    </Suspense>
  );
}
