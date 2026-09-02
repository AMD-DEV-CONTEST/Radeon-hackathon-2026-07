"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useRef } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { QueryErrorState } from "@/components/feedback/query-error-state";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Button } from "@/components/ui/button";
import { ImprovementCard } from "@/features/report/components/improvement-card";
import { InterviewSummary } from "@/features/report/components/interview-summary";
import { OverallScoreCard } from "@/features/report/components/overall-score-card";
import { ReportActions } from "@/features/report/components/report-actions";
import { ReportHeader } from "@/features/report/components/report-header";
import { ReportRadarChart } from "@/features/report/components/radar-chart";
import { ReportSkeleton } from "@/features/report/components/report-skeleton";
import { ScoreBreakdownCard } from "@/features/report/components/score-breakdown-card";
import { StrengthsCard } from "@/features/report/components/strengths-card";
import { TimelineCard } from "@/features/report/components/timeline-card";
import { TranscriptSummary } from "@/features/report/components/transcript-summary";
import {
  getGenerateReportErrorMessage,
  getReportErrorMessage,
  getReportInterviewErrorMessage,
  isNotFoundError,
  isReportNotReadyError,
  useGenerateReport,
  useReport,
  useReportInterview,
} from "@/features/report/hooks/use-report";

export function ReportView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const reportIdParam = searchParams.get("id")?.trim() || "";
  const interviewIdParam = searchParams.get("interviewId")?.trim() || "";
  const lookupId = reportIdParam || interviewIdParam;

  const transcriptRef = useRef<HTMLDivElement>(null);

  const reportQuery = useReport(lookupId);
  const interviewQuery = useReportInterview(
    interviewIdParam || reportQuery.data?.interviewId || undefined
  );
  const generateMutation = useGenerateReport();

  const isLoading =
    Boolean(lookupId) &&
    (reportQuery.isLoading ||
      (Boolean(interviewIdParam) && interviewQuery.isLoading));

  const reportNotReady =
    reportQuery.isError && isReportNotReadyError(reportQuery.error);
  const reportMissing =
    reportQuery.isError &&
    (isNotFoundError(reportQuery.error) || reportNotReady);

  const interviewIdForGenerate =
    interviewIdParam ||
    interviewQuery.data?.id ||
    reportQuery.data?.interviewId ||
    "";

  async function handleGenerate() {
    if (!interviewIdForGenerate) {
      return;
    }

    const result = await generateMutation.mutateAsync({
      interviewId: interviewIdForGenerate,
    });

    if (result.reportId) {
      router.replace(`/interviews/report?id=${result.reportId}`);
      await reportQuery.refetch();
      return;
    }

    await reportQuery.refetch();
  }

  return (
    <DashboardLayout
      breadcrumbs={[
        { label: "Interview Management" },
        { label: "Active Sessions", current: true },
      ]}
    >
      {!lookupId ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="Report not selected"
            description="Open a report from the dashboard or finish an interview to view AI evaluation results."
          />
        </div>
      ) : null}

      {lookupId && isLoading ? <ReportSkeleton /> : null}

      {lookupId && !isLoading && interviewQuery.isError && !reportQuery.data ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          {isNotFoundError(interviewQuery.error) ? (
            <EmptyState
              title="Interview not found"
              description={getReportInterviewErrorMessage(interviewQuery.error)}
            />
          ) : (
            <QueryErrorState
              title="Unable to load interview"
              message={getReportInterviewErrorMessage(interviewQuery.error)}
              onRetry={() => {
                void interviewQuery.refetch();
              }}
            />
          )}
        </div>
      ) : null}

      {lookupId &&
      !isLoading &&
      reportQuery.isError &&
      !reportQuery.data &&
      !interviewQuery.isError ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          {reportMissing ? (
            <div className="space-y-4">
              <EmptyState
                title={
                  reportNotReady ? "Report not ready" : "No interview report found"
                }
                description={
                  reportNotReady
                    ? getReportErrorMessage(reportQuery.error)
                    : "Complete an interview session to generate an AI evaluation report."
                }
              />
              {interviewIdForGenerate ? (
                <div className="flex flex-col items-center gap-3">
                  <Button
                    type="button"
                    className="glow-purple"
                    disabled={generateMutation.isPending}
                    onClick={() => {
                      void handleGenerate().catch(() => undefined);
                    }}
                  >
                    {generateMutation.isPending
                      ? "Generating report..."
                      : "Generate Report"}
                  </Button>
                  {generateMutation.isError ? (
                    <QueryErrorState
                      title="Generation failed"
                      message={getGenerateReportErrorMessage(
                        generateMutation.error
                      )}
                      onRetry={() => {
                        void handleGenerate().catch(() => undefined);
                      }}
                    />
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : (
            <QueryErrorState
              title="Unable to load interview report"
              message={getReportErrorMessage(reportQuery.error)}
              onRetry={() => {
                void reportQuery.refetch();
              }}
            />
          )}
        </div>
      ) : null}

      {lookupId && !isLoading && !reportQuery.isError && !reportQuery.data ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="No interview report found"
            description="Complete an interview session to generate an AI evaluation report."
          />
        </div>
      ) : null}

      {lookupId && !isLoading && reportQuery.data ? (
        <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
          <ReportHeader report={reportQuery.data} />

          {reportQuery.isFetching ? (
            <p className="text-xs text-muted-foreground">Refreshing report...</p>
          ) : null}

          <section
            className="grid gap-4 xl:grid-cols-3"
            aria-label="Candidate overview and core metrics"
          >
            <OverallScoreCard report={reportQuery.data} />
            <ReportRadarChart data={reportQuery.data.competencyMatrix} />
            <ScoreBreakdownCard scores={reportQuery.data.scores} />
          </section>

          <section
            className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]"
            aria-label="Performance timeline and AI summary"
          >
            <TimelineCard
              pulse={reportQuery.data.interviewPulse}
              events={reportQuery.data.timeline}
              durationMinutes={reportQuery.data.durationMinutes}
            />
            <InterviewSummary summary={reportQuery.data.summary} />
          </section>

          <section
            className="grid gap-4 lg:grid-cols-2"
            aria-label="Strengths and improvement areas"
          >
            <StrengthsCard strengths={reportQuery.data.strengths} />
            <ImprovementCard improvements={reportQuery.data.improvements} />
          </section>

          <div
            ref={transcriptRef}
            tabIndex={-1}
            className="outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-[#09090b]"
          >
            <TranscriptSummary
              highlights={reportQuery.data.transcriptHighlights}
            />
          </div>

          <ReportActions
            reportId={reportQuery.data.id}
            interviewId={reportQuery.data.interviewId}
            onViewTranscript={() => {
              transcriptRef.current?.focus();
              transcriptRef.current?.scrollIntoView({
                behavior: "smooth",
                block: "start",
              });
            }}
          />
        </div>
      ) : null}
    </DashboardLayout>
  );
}
