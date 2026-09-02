"use client";

import { motion } from "framer-motion";
import { Loader2, Play, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { EmptyState } from "@/components/feedback/empty-state";
import { QueryErrorState } from "@/components/feedback/query-error-state";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { AiSummaryCard } from "@/features/candidate/components/ai-summary-card";
import { CandidateProfile } from "@/features/candidate/components/candidate-profile";
import { CompetencyRadar } from "@/features/candidate/components/competency-radar";
import { DossierSkeleton } from "@/features/candidate/components/dossier-skeleton";
import { EducationCard } from "@/features/candidate/components/education-card";
import { ExperienceCard } from "@/features/candidate/components/experience-card";
import { InterviewRoadmap } from "@/features/candidate/components/interview-roadmap";
import { ProjectsCard } from "@/features/candidate/components/projects-card";
import { ResumeMetaCard } from "@/features/candidate/components/resume-meta-card";
import { SkillsCard } from "@/features/candidate/components/skills-card";
import { StrengthsCard } from "@/features/candidate/components/strengths-card";
import { WeaknessesCard } from "@/features/candidate/components/weaknesses-card";
import {
  getUseAnalyzeErrorMessage,
  getUseCandidateErrorMessage,
  getUseResumeErrorMessage,
  useAnalyzeResume,
  useCandidate,
  useResume,
} from "@/features/candidate/hooks/use-candidate";
import { useResumeStore } from "@/features/resume/store/resume.store";
import { isNotFoundError } from "@/features/candidate/utils/candidate-errors";
import { cn } from "@/lib/utils";

function analysisBadgeLabel(status: string): string {
  if (status === "complete") {
    return "AI Analysis Complete";
  }
  if (status === "pending") {
    return "AI Analysis Pending";
  }
  if (status === "failed") {
    return "AI Analysis Failed";
  }
  return "AI Analysis Idle";
}

export function DossierView() {
  const searchParams = useSearchParams();
  const storedResume = useResumeStore((state) => state.currentResume);

  const candidateId =
    searchParams.get("id")?.trim() ||
    storedResume?.candidateId ||
    "";

  const resumeIdFromQuery = searchParams.get("resumeId")?.trim() || null;

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useCandidate(candidateId);

  const resumeId =
    resumeIdFromQuery || data?.profile.resumeId || storedResume?.id || undefined;

  const resumeQuery = useResume(resumeId);
  const analyzeResume = useAnalyzeResume();

  const showEmptyId = !candidateId;
  const candidateNotFound = isError && isNotFoundError(error);

  return (
    <DashboardLayout
      breadcrumbs={[
        { label: "Interview Management" },
        { label: "Active Sessions", current: true },
      ]}
    >
      {showEmptyId ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="No candidate selected"
            description="Open a candidate dossier with an id, or upload a resume first."
          />
        </div>
      ) : null}

      {!showEmptyId && isLoading ? <DossierSkeleton /> : null}

      {!showEmptyId && !isLoading && isError ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          {candidateNotFound ? (
            <EmptyState
              title="Candidate not found"
              description={getUseCandidateErrorMessage(error)}
            />
          ) : (
            <QueryErrorState
              title="Unable to load candidate dossier"
              message={getUseCandidateErrorMessage(error)}
              onRetry={() => {
                void refetch();
              }}
            />
          )}
        </div>
      ) : null}

      {!showEmptyId && !isLoading && !isError && !data ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="No candidate dossier found"
            description="Upload a resume and run analysis to generate a candidate dossier."
          />
        </div>
      ) : null}

      {!showEmptyId && !isLoading && !isError && data ? (
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
          <motion.header
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35 }}
            className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between"
          >
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant="purple" className="gap-1.5">
                  <Sparkles className="h-3 w-3" aria-hidden="true" />
                  {analysisBadgeLabel(data.analysisStatus)}
                </Badge>
                <span className="font-mono text-xs text-muted-foreground">
                  ID: {data.profile.id}
                </span>
                {isFetching ? (
                  <span className="text-xs text-muted-foreground">
                    Refreshing...
                  </span>
                ) : null}
              </div>
              <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
                Candidate Dossier
              </h1>
              <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
                Comprehensive technical evaluation and strategic interview
                roadmap for {data.profile.fullName}.
              </p>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Button
                type="button"
                variant="outline"
                className="h-11"
                disabled={isFetching}
                onClick={() => {
                  void refetch();
                  if (resumeId) {
                    void resumeQuery.refetch();
                  }
                }}
              >
                <RefreshCw
                  className={cn("h-4 w-4", isFetching && "animate-spin")}
                  aria-hidden="true"
                />
                Refresh
              </Button>

              <Button
                type="button"
                variant="outline"
                className="h-11"
                disabled={!resumeId || analyzeResume.isPending}
                aria-busy={analyzeResume.isPending}
                onClick={() => {
                  if (!resumeId) {
                    return;
                  }
                  void analyzeResume.mutateAsync({ resumeId });
                }}
              >
                {analyzeResume.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Sparkles className="h-4 w-4" aria-hidden="true" />
                )}
                Analyze Resume
              </Button>

              <Link
                href="/interviews/planning"
                className={cn(
                  buttonVariants({ size: "lg" }),
                  "h-11 shrink-0 glow-purple"
                )}
              >
                <Play className="h-4 w-4" aria-hidden="true" />
                Start Interview Process
              </Link>
            </div>
          </motion.header>

          {analyzeResume.isError ? (
            <div className="mb-4">
              <QueryErrorState
                title="Analysis failed"
                message={getUseAnalyzeErrorMessage(analyzeResume.error)}
                onRetry={() => {
                  if (!resumeId) {
                    return;
                  }
                  void analyzeResume.mutateAsync({ resumeId });
                }}
              />
            </div>
          ) : null}

          {resumeId && resumeQuery.isError ? (
            <div className="mb-4">
              <QueryErrorState
                title="Resume missing"
                message={getUseResumeErrorMessage(resumeQuery.error)}
                onRetry={() => {
                  void resumeQuery.refetch();
                }}
              />
            </div>
          ) : null}

          <div className="grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)_320px]">
            <div className="space-y-4">
              <CandidateProfile
                profile={data.profile}
                competencies={data.coreCompetencies}
              />
              {resumeQuery.data ? (
                <ResumeMetaCard resume={resumeQuery.data} />
              ) : null}
              <SkillsCard skills={data.skills} />
              <ExperienceCard experience={data.experience} />
              <ProjectsCard projects={data.projects} />
              <EducationCard
                education={data.education}
                certifications={data.certifications}
              />
            </div>

            <div className="space-y-4">
              <CompetencyRadar competencies={data.competencies} />
              <div className="grid gap-4 md:grid-cols-2">
                <StrengthsCard strengths={data.strengths} />
                <WeaknessesCard weaknesses={data.weaknesses} />
              </div>
            </div>

            <div className="space-y-4">
              <AiSummaryCard
                summary={data.aiSummary}
                experienceSummary={data.experienceSummary}
                educationSummary={data.educationSummary}
                readinessScore={data.roadmap.readinessScore}
                recommendedFocus={data.suggestedInterviewFocus}
              />
              <InterviewRoadmap roadmap={data.roadmap} />
            </div>
          </div>
        </div>
      ) : null}
    </DashboardLayout>
  );
}
