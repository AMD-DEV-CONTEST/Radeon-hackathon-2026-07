import type { Metadata } from "next";
import { Suspense } from "react";

import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { InterviewRoomSkeleton } from "@/features/interview/components/interview-room-skeleton";
import { InterviewRoomView } from "@/features/interview/components/interview-room-view";

export const metadata: Metadata = {
  title: "Interview Room — AgentVox",
  description:
    "Live AI interview room with real-time transcription, scoring, and multi-agent orchestration.",
};

interface InterviewRoomByIdPageProps {
  params: Promise<{
    interviewId: string;
  }>;
}

export default async function InterviewRoomByIdPage({
  params,
}: InterviewRoomByIdPageProps) {
  const { interviewId } = await params;

  return (
    <Suspense
      fallback={
        <DashboardLayout
          breadcrumbs={[
            { label: "Interview Management" },
            { label: "Active Sessions", current: true },
          ]}
        >
          <InterviewRoomSkeleton />
        </DashboardLayout>
      }
    >
      <InterviewRoomView interviewId={interviewId} />
    </Suspense>
  );
}
