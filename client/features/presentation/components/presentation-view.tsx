"use client";

import { useSearchParams } from "next/navigation";

import { EmptyState } from "@/components/feedback/empty-state";
import { QueryErrorState } from "@/components/feedback/query-error-state";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { AiInsights } from "@/features/presentation/components/ai-insights";
import { CompetencyRadar } from "@/features/presentation/components/competency-radar";
import { ExecutiveSummary } from "@/features/presentation/components/executive-summary";
import { ExportActions } from "@/features/presentation/components/export-actions";
import { HiringDecision } from "@/features/presentation/components/hiring-decision";
import { HiringPipeline } from "@/features/presentation/components/hiring-pipeline";
import { ImprovementPanel } from "@/features/presentation/components/improvement-panel";
import { InterviewHighlights } from "@/features/presentation/components/interview-highlights";
import { InterviewOverview } from "@/features/presentation/components/interview-overview";
import { PresentationHeader } from "@/features/presentation/components/presentation-header";
import { PresentationSkeleton } from "@/features/presentation/components/presentation-skeleton";
import { ScoreOverview } from "@/features/presentation/components/score-overview";
import { StrengthsPanel } from "@/features/presentation/components/strengths-panel";
import { TimelineOverview } from "@/features/presentation/components/timeline-overview";
import {
  getPresentationErrorMessage,
  isNotFoundError,
  usePresentationDashboard,
} from "@/features/presentation/hooks/use-presentation";

export function PresentationView() {
  const searchParams = useSearchParams();
  const candidateId =
    searchParams.get("candidateId")?.trim() ||
    searchParams.get("id")?.trim() ||
    "";

  const { data, isLoading, isError, error, refetch, isFetching } =
    usePresentationDashboard(candidateId);

  return (
    <DashboardLayout
      breadcrumbs={[
        { label: "Interview Management" },
        { label: "Active Sessions", current: true },
      ]}
    >
      {!candidateId ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="Candidate not selected"
            description="Open a presentation from a candidate or report to view the executive dashboard."
          />
        </div>
      ) : null}

      {candidateId && isLoading ? <PresentationSkeleton /> : null}

      {candidateId && !isLoading && isError ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          {isNotFoundError(error) ? (
            <EmptyState
              title="Presentation not found"
              description={getPresentationErrorMessage(error)}
            />
          ) : (
            <QueryErrorState
              title="Unable to load presentation dashboard"
              message={getPresentationErrorMessage(error)}
              onRetry={() => {
                void refetch();
              }}
            />
          )}
        </div>
      ) : null}

      {candidateId && !isLoading && !isError && !data ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="No presentation available"
            description="Complete an interview evaluation to generate an executive presentation dashboard."
          />
        </div>
      ) : null}

      {candidateId && !isLoading && !isError && data ? (
        <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
          <PresentationHeader data={data} />

          {isFetching ? (
            <p className="text-xs text-muted-foreground">
              Refreshing presentation...
            </p>
          ) : null}

          <section
            className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]"
            aria-label="Summary and interview overview"
          >
            <ExecutiveSummary
              summary={data.executiveSummary}
              durationMinutes={data.durationMinutes}
              totalQuestions={data.totalQuestions}
              completionStatus={data.completionStatus}
            />
            <InterviewOverview
              candidate={data.candidate}
              durationMinutes={data.durationMinutes}
              totalQuestions={data.totalQuestions}
              reportId={data.reportId}
            />
          </section>

          <ScoreOverview scores={data.scores} />

          <section
            className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]"
            aria-label="Competency and hiring decision"
          >
            <CompetencyRadar data={data.competencyMatrix} />
            <HiringDecision
              recommendation={data.recommendation}
              explanation={data.recommendationExplanation}
            />
          </section>

          <TimelineOverview
            skillBreakdown={data.skillBreakdown}
            scoreTrend={data.scoreTrend}
            evaluationTimeline={data.evaluationTimeline}
          />

          <AiInsights insights={data.insights} />

          <section
            className="grid gap-4 lg:grid-cols-3"
            aria-label="Highlights, strengths, and improvements"
          >
            <InterviewHighlights highlights={data.highlights} />
            <StrengthsPanel strengths={data.insights.strengths} />
            <ImprovementPanel improvements={data.improvements} />
          </section>

          <HiringPipeline stages={data.pipeline} />

          <ExportActions
            reportId={data.reportId}
            candidateId={data.candidate.id}
          />

          <footer className="border-t border-white/10 pt-4 text-xs text-muted-foreground">
            Last synced:{" "}
            {new Intl.DateTimeFormat("en-US", {
              dateStyle: "medium",
              timeStyle: "short",
            }).format(new Date(data.lastSyncedAt))}
          </footer>
        </div>
      ) : null}
    </DashboardLayout>
  );
}
