"use client";

import { CameraOff, MicOff, WifiOff } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/feedback/empty-state";
import { QueryErrorState } from "@/components/feedback/query-error-state";
import { Button, buttonVariants } from "@/components/ui/button";
import type { InterviewRoomPhase } from "@/features/interview/types/interview.types";
import { cn } from "@/lib/utils";

interface RoomErrorStatesProps {
  phase: InterviewRoomPhase;
  interviewId?: string;
  onRetryConnection?: () => void;
  onBackToPlanning?: () => void;
}

export function RoomErrorStates({
  phase,
  interviewId,
  onRetryConnection,
  onBackToPlanning,
}: RoomErrorStatesProps) {
  if (phase === "connection_lost") {
    return (
      <div className="mx-auto max-w-xl px-4 py-10">
        <QueryErrorState
          title="Connection lost"
          message="The live interview socket disconnected. Check your network and retry to rejoin the session."
          onRetry={onRetryConnection}
        />
      </div>
    );
  }

  if (phase === "microphone_denied") {
    return (
      <div className="mx-auto max-w-xl px-4 py-10">
        <EmptyState
          title="Microphone permission denied"
          description="Allow microphone access in your browser settings to continue the voice interview."
          icon={MicOff}
        />
        {onRetryConnection ? (
          <div className="mt-4 flex justify-center">
            <Button type="button" variant="outline" onClick={onRetryConnection}>
              Retry Permission Check
            </Button>
          </div>
        ) : null}
      </div>
    );
  }

  if (phase === "camera_denied") {
    return (
      <div className="mx-auto max-w-xl px-4 py-10">
        <EmptyState
          title="Camera permission denied"
          description="Camera access is blocked. You can continue with audio only or enable camera permissions."
          icon={CameraOff}
        />
        {onRetryConnection ? (
          <div className="mt-4 flex justify-center">
            <Button type="button" variant="outline" onClick={onRetryConnection}>
              Continue Without Camera
            </Button>
          </div>
        ) : null}
      </div>
    );
  }

  if (phase === "cancelled") {
    return (
      <div className="mx-auto max-w-xl px-4 py-10">
        <EmptyState
          title="Interview cancelled"
          description="This interview session was cancelled and cannot continue."
          icon={WifiOff}
        />
        {onBackToPlanning ? (
          <div className="mt-4 flex justify-center">
            <Button type="button" onClick={onBackToPlanning}>
              Back to Planning
            </Button>
          </div>
        ) : null}
      </div>
    );
  }

  if (phase === "ended") {
    return (
      <div className="mx-auto max-w-xl px-4 py-10">
        <EmptyState
          title="Interview finished"
          description="This session has been closed. Review the report when it becomes available."
          icon={WifiOff}
        />
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {interviewId ? (
            <Link
              href={`/interviews/report?interviewId=${interviewId}`}
              className={cn(buttonVariants({ size: "default" }), "glow-purple")}
            >
              View Report
            </Link>
          ) : null}
          {onBackToPlanning ? (
            <Button type="button" variant="outline" onClick={onBackToPlanning}>
              Back to Planning
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  return null;
}
