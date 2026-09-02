"use client";

import { motion } from "framer-motion";
import { ArrowLeft, Loader2, Play, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { EmptyState } from "@/components/feedback/empty-state";
import { QueryErrorState } from "@/components/feedback/query-error-state";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Button, buttonVariants } from "@/components/ui/button";
import { AiAgentsPanel } from "@/features/interview/components/ai-agents-panel";
import { EstimatedDuration } from "@/features/interview/components/estimated-duration";
import { InterviewChecklist } from "@/features/interview/components/interview-checklist";
import { InterviewConfiguration } from "@/features/interview/components/interview-configuration";
import { InterviewOverview } from "@/features/interview/components/interview-overview";
import { InterviewSummary } from "@/features/interview/components/interview-summary";
import { PlanningCharts } from "@/features/interview/components/planning-charts";
import { PlanningHeader } from "@/features/interview/components/planning-header";
import { PlanningInsights } from "@/features/interview/components/planning-insights";
import { PlanningSkeleton } from "@/features/interview/components/planning-skeleton";
import { ReadinessCard } from "@/features/interview/components/readiness-card";
import { WorkflowTimeline } from "@/features/interview/components/workflow-timeline";
import { useInterviewPlanning } from "@/features/interview/hooks/use-interview-planning";
import {
  getCandidateMissingMessage,
  getCreateInterviewErrorMessage,
  getPlanningErrorMessage,
  getResumeMissingMessage,
  isNotFoundError,
} from "@/features/interview/utils/planning-errors";
import { cn } from "@/lib/utils";

export function PlanningView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const candidateId = searchParams.get("candidateId")?.trim() || "";
  const resumeId = searchParams.get("resumeId")?.trim() || "";

  const {
    plan,
    configuration,
    setConfiguration,
    isLoading,
    isError,
    error,
    refetch,
    candidateId: resolvedCandidateId,
    resumeId: resolvedResumeId,
    candidateQuery,
    resumeQuery,
    planMutation,
    createMutation,
    regeneratePlan,
  } = useInterviewPlanning({ candidateId, resumeId });

  const checklistReady =
    plan?.checklist.every((item) => item.completed) ?? false;
  const isPlanning = planMutation.isPending;
  const isCreating = createMutation.isPending;
  const isBusy = isPlanning || isCreating;

  const showMissingCandidate = !resolvedCandidateId;
  const candidateMissing =
    candidateQuery.isError && isNotFoundError(candidateQuery.error);
  const resumeMissing =
    Boolean(resolvedResumeId) &&
    resumeQuery.isError &&
    isNotFoundError(resumeQuery.error);

  return (
    <DashboardLayout
      breadcrumbs={[
        { label: "Interview Management" },
        { label: "Active Sessions", current: true },
      ]}
    >
      {showMissingCandidate ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="Candidate missing"
            description="Open a candidate dossier or upload a resume before planning an interview."
          />
        </div>
      ) : null}

      {!showMissingCandidate && isLoading ? <PlanningSkeleton /> : null}

      {!showMissingCandidate && !isLoading && isError ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          {candidateMissing ? (
            <EmptyState
              title="Candidate missing"
              description={getCandidateMissingMessage(error)}
            />
          ) : resumeMissing ? (
            <EmptyState
              title="Resume missing"
              description={getResumeMissingMessage(resumeQuery.error)}
            />
          ) : (
            <QueryErrorState
              title="Unable to load interview planning"
              message={getPlanningErrorMessage(error)}
              onRetry={() => {
                void refetch();
              }}
            />
          )}
        </div>
      ) : null}

      {!showMissingCandidate && !isLoading && !isError && !plan ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="No interview plan available"
            description="Create an interview plan for this candidate to begin orchestration."
          />
        </div>
      ) : null}

      {!showMissingCandidate && !isLoading && !isError && plan ? (
        <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
          <PlanningHeader
            candidateName={plan.candidate.fullName}
            engineStatus={plan.summary.engineStatus}
            planningProgress={plan.summary.planningProgress}
          />

          {planMutation.isError ? (
            <QueryErrorState
              title="Planning failed"
              message={getPlanningErrorMessage(planMutation.error)}
              onRetry={() => {
                void regeneratePlan();
              }}
            />
          ) : null}

          {createMutation.isError ? (
            <QueryErrorState
              title="Interview creation failed"
              message={getCreateInterviewErrorMessage(createMutation.error)}
              onRetry={() => {
                void (async () => {
                  try {
                    const result = await createMutation.mutateAsync({});
                    router.push(`/interviews/room/${result.interviewId}`);
                  } catch {
                    // Error remains in createMutation state.
                  }
                })();
              }}
            />
          ) : null}

          {!resolvedResumeId ? (
            <QueryErrorState
              title="Resume missing"
              message="Upload a resume before generating an interview plan."
            />
          ) : null}

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="space-y-4">
              <InterviewOverview candidate={plan.candidate} />
              <WorkflowTimeline steps={plan.workflow} />
              <InterviewConfiguration
                value={configuration}
                disabled={isBusy}
                onChange={setConfiguration}
              />
              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="outline"
                  className="h-10"
                  disabled={isBusy || !resolvedResumeId}
                  onClick={() => {
                    void regeneratePlan();
                  }}
                >
                  {isPlanning ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <RefreshCw className="h-4 w-4" aria-hidden="true" />
                  )}
                  Regenerate Plan
                </Button>
              </div>
              <AiAgentsPanel agents={plan.agents} />
              <PlanningCharts
                skillDistribution={plan.skillDistribution}
                interviewCoverage={plan.interviewCoverage}
                readinessScore={plan.candidate.readinessScore}
              />
            </div>

            <div className="space-y-4">
              <ReadinessCard
                score={plan.candidate.readinessScore}
                candidateName={plan.candidate.fullName}
              />
              <EstimatedDuration
                minutes={plan.summary.estimatedDurationMinutes}
                questionCount={plan.summary.expectedQuestionCount}
              />
              <InterviewSummary summary={plan.summary} />
              <InterviewChecklist items={plan.checklist} />
              <PlanningInsights
                candidate={plan.candidate}
                insights={plan.insights}
              />
            </div>
          </div>

          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.1 }}
            className="sticky bottom-4 z-10 flex flex-col gap-3 rounded-2xl border border-border/70 bg-[#0f1018]/95 p-4 backdrop-blur-xl sm:flex-row sm:items-center sm:justify-between"
          >
            <p className="text-sm text-muted-foreground">
              {checklistReady
                ? "All pre-flight checks passed. You can start the interview."
                : "Complete remaining checklist items before starting the interview."}
            </p>

            <div className="flex items-center gap-2">
              <Link
                href="/candidates/dossier"
                className={cn(
                  buttonVariants({ variant: "outline", size: "lg" }),
                  "h-11"
                )}
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                Back
              </Link>

              <motion.div
                whileHover={{ scale: isBusy ? 1 : 1.01 }}
                whileTap={{ scale: isBusy ? 1 : 0.99 }}
              >
                <Button
                  type="button"
                  className="h-11 glow-purple"
                  disabled={isBusy || !resolvedResumeId || !configuration.role}
                  aria-busy={isCreating}
                  onClick={async () => {
                    try {
                      if (!plannedHasId(plan) || planMutation.isError) {
                        await regeneratePlan();
                      }
                      const result = await createMutation.mutateAsync({});
                      router.push(`/interviews/room/${result.interviewId}`);
                    } catch {
                      // Error surfaces via createMutation / planMutation state.
                    }
                  }}
                >
                  {isCreating ? (
                    <>
                      <Loader2
                        className="h-4 w-4 animate-spin"
                        aria-hidden="true"
                      />
                      Starting...
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4" aria-hidden="true" />
                      Start Interview
                    </>
                  )}
                </Button>
              </motion.div>
            </div>
          </motion.div>
        </div>
      ) : null}
    </DashboardLayout>
  );
}

function plannedHasId(plan: { id: string }): boolean {
  return plan.id.trim().length > 0;
}
