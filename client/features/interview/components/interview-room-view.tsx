"use client";

import { motion } from "framer-motion";
import { useRouter, useSearchParams } from "next/navigation";

import { EmptyState } from "@/components/feedback/empty-state";
import { QueryErrorState } from "@/components/feedback/query-error-state";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { AgentStatusPanel } from "@/features/interview/components/agent-status-panel";
import { CameraPreview } from "@/features/interview/components/camera-preview";
import { ControlBar } from "@/features/interview/components/control-bar";
import { InterviewProgress } from "@/features/interview/components/interview-progress";
import { InterviewRoomSkeleton } from "@/features/interview/components/interview-room-skeleton";
import { LiveScorePanel } from "@/features/interview/components/live-score-panel";
import { QuestionCard } from "@/features/interview/components/question-card";
import { RoomErrorStates } from "@/features/interview/components/room-error-states";
import { TranscriptPanel } from "@/features/interview/components/transcript-panel";
import { useInterview } from "@/features/interview/hooks/use-interview";
import {
  getInterviewRoomErrorMessage,
  getStartInterviewErrorMessage,
  isNotFoundError,
} from "@/features/interview/utils/room-errors";

interface InterviewRoomViewProps {
  interviewId?: string;
}

export function InterviewRoomView({
  interviewId: interviewIdProp,
}: InterviewRoomViewProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const interviewId =
    interviewIdProp?.trim() ||
    searchParams.get("interviewId")?.trim() ||
    "";

  const {
    session,
    phase,
    socket,
    isLoading,
    isError,
    error,
    refetch,
    endMutation,
    startMutation,
    toggleMute,
    toggleCamera,
    setPhase,
  } = useInterview(interviewId);

  const showBlockingState =
    phase === "ended" ||
    phase === "cancelled" ||
    phase === "connection_lost" ||
    phase === "microphone_denied" ||
    phase === "camera_denied";

  return (
    <DashboardLayout
      breadcrumbs={[
        { label: "Interview Management" },
        { label: "Active Sessions", current: true },
      ]}
    >
      {!interviewId ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="Interview not selected"
            description="Start an interview from planning to enter the live room."
          />
        </div>
      ) : null}

      {interviewId && (isLoading || startMutation.isPending) ? (
        <InterviewRoomSkeleton />
      ) : null}

      {interviewId && !isLoading && isError ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          {isNotFoundError(error) ? (
            <EmptyState
              title="Interview not found"
              description={getInterviewRoomErrorMessage(error)}
            />
          ) : (
            <QueryErrorState
              title="Unable to load interview room"
              message={getInterviewRoomErrorMessage(error)}
              onRetry={() => {
                void refetch();
              }}
            />
          )}
        </div>
      ) : null}

      {interviewId && !isLoading && !startMutation.isPending && startMutation.isError ? (
        <div className="mx-auto max-w-3xl px-4 py-4 sm:px-6">
          <QueryErrorState
            title="Unable to start interview"
            message={getStartInterviewErrorMessage(startMutation.error)}
            onRetry={() => {
              void startMutation.mutateAsync();
            }}
          />
        </div>
      ) : null}

      {interviewId &&
      !isLoading &&
      !startMutation.isPending &&
      !isError &&
      showBlockingState ? (
        <RoomErrorStates
          phase={phase}
          interviewId={interviewId}
          onRetryConnection={() => {
            setPhase("live");
            socket.retry();
            void refetch();
          }}
          onBackToPlanning={() => {
            router.push("/interviews/planning");
          }}
        />
      ) : null}

      {interviewId &&
      !isLoading &&
      !startMutation.isPending &&
      !isError &&
      session &&
      !showBlockingState ? (
        <>
          <div className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="space-y-4">
              <QuestionCard
                question={session.question}
                isMuted={session.isMuted}
                isCandidateSpeaking={session.isCandidateSpeaking}
                isAiThinking={session.isAiThinking}
              />

              <CameraPreview
                isOn={session.isCameraOn}
                candidateInitials={session.candidate.avatarInitials}
              />

              <TranscriptPanel />
            </div>

            <div className="space-y-4">
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                <Card className="rounded-2xl border border-white/10 bg-[#12121a]/85 py-0 ring-0 backdrop-blur-xl">
                  <CardContent className="p-5">
                    <div className="flex items-center gap-3">
                      <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-primary/30 bg-primary/15 text-sm font-bold text-primary">
                        {session.candidate.avatarInitials}
                      </div>
                      <div>
                        <h2 className="text-base font-semibold text-white">
                          {session.candidate.fullName}
                        </h2>
                        <p className="text-xs text-muted-foreground">
                          {session.candidate.title}
                        </p>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Badge variant="secondary">
                        {session.candidate.level}
                      </Badge>
                      <Badge variant="outline" className="capitalize">
                        {session.status}
                      </Badge>
                      {session.candidate.skills.map((skill) => (
                        <Badge key={skill} variant="outline">
                          {skill}
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.div>

              <InterviewProgress
                progressPercent={session.progressPercent}
                difficulty={session.question.difficulty}
                estimatedRemainingLabel={session.estimatedRemainingLabel}
              />

              <LiveScorePanel
                metrics={session.metrics}
                series={session.metricSeries}
                speakingSpeedWpm={session.speakingSpeedWpm}
                sentiment={session.sentiment}
                aiNotes={session.aiNotes}
              />

              <AgentStatusPanel agents={session.agents} />
            </div>
          </div>

          <ControlBar
            sessionId={session.id}
            isLive={session.status === "live"}
            isMuted={session.isMuted}
            isCameraOn={session.isCameraOn}
            isScreenShareEnabled={session.isScreenShareEnabled}
            latencyMs={session.latencyMs}
            isConnected={socket.isConnected}
            isEnding={endMutation.isPending}
            onToggleMute={toggleMute}
            onToggleCamera={toggleCamera}
            onSkipQuestion={() => {
              setPhase("live");
            }}
            onStopRecording={() => {
              toggleMute();
            }}
            onEndInterview={() => {
              void endMutation.mutateAsync();
            }}
          />
        </>
      ) : null}
    </DashboardLayout>
  );
}
