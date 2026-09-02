"use client";

import { EmptyState } from "@/components/feedback/empty-state";
import { QueryErrorState } from "@/components/feedback/query-error-state";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { ActiveInterviews } from "@/features/admin/components/active-interviews";
import { AdminHeader } from "@/features/admin/components/admin-header";
import { AdminSkeleton } from "@/features/admin/components/admin-skeleton";
import { AnalyticsCards } from "@/features/admin/components/analytics-cards";
import { CandidateTable } from "@/features/admin/components/candidate-table";
import { InterviewStatistics } from "@/features/admin/components/interview-statistics";
import { NotificationsPanel } from "@/features/admin/components/notifications-panel";
import { PlatformOverview } from "@/features/admin/components/platform-overview";
import { QuickActions } from "@/features/admin/components/quick-actions";
import { RecentActivity } from "@/features/admin/components/recent-activity";
import { SystemHealth } from "@/features/admin/components/system-health";
import { SystemMetrics } from "@/features/admin/components/system-metrics";
import { UsageChart } from "@/features/admin/components/usage-chart";
import {
  getAdminDashboardErrorMessage,
  isNotFoundError,
  useAdmin,
} from "@/features/admin/hooks/use-admin";

export function AdminView() {
  const { data, isLoading, isError, error, refetch, isFetching } = useAdmin();

  return (
    <DashboardLayout
      breadcrumbs={[
        { label: "Interview Management" },
        { label: "Active Sessions", current: true },
      ]}
    >
      {isLoading ? <AdminSkeleton /> : null}

      {!isLoading && isError ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          {isNotFoundError(error) ? (
            <EmptyState
              title="Admin dashboard unavailable"
              description={getAdminDashboardErrorMessage(error)}
            />
          ) : (
            <QueryErrorState
              title="Unable to load admin dashboard"
              message={getAdminDashboardErrorMessage(error)}
              onRetry={() => {
                void refetch();
              }}
            />
          )}
        </div>
      ) : null}

      {!isLoading && !isError && !data ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="Admin dashboard unavailable"
            description="Platform telemetry will appear once admin analytics endpoints return data."
          />
        </div>
      ) : null}

      {!isLoading && !isError && data ? (
        <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
          <AdminHeader overview={data.overview} />

          {isFetching ? (
            <p className="text-xs text-muted-foreground">
              Syncing platform telemetry...
            </p>
          ) : null}

          <PlatformOverview overview={data.overview} />
          <AnalyticsCards kpis={data.kpis} />
          <InterviewStatistics statistics={data.statistics} />

          <section
            className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]"
            aria-label="Trends and system health"
          >
            <div className="space-y-4">
              <UsageChart trends={data.interviewTrends} />
              <ActiveInterviews sessions={data.liveSessions} />
            </div>
            <SystemHealth
              services={data.systemHealth}
              agents={data.activeAgents}
            />
          </section>

          <SystemMetrics
            userGrowth={data.userGrowth}
            agentUsage={data.agentUsage}
            platformUsage={data.platformUsage}
            systemPerformance={data.systemPerformance}
            skillTrends={data.skillTrends}
          />

          <CandidateTable
            candidates={data.recentCandidates}
            interviews={data.recentInterviews}
          />

          <RecentActivity
            talentFeed={data.talentFeed}
            aiReports={data.aiReports}
            strategy={data.strategy}
          />

          <section
            className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]"
            aria-label="Actions and notifications"
          >
            <QuickActions actions={data.quickActions} />
            <NotificationsPanel notifications={data.notifications} />
          </section>

          <footer className="flex flex-col gap-2 border-t border-white/10 pt-4 text-xs text-muted-foreground sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            <p className="inline-flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-sky-400" aria-hidden="true" />
              {data.engineVersion}
            </p>
            <p>
              Last data sync:{" "}
              {new Intl.DateTimeFormat("en-US", {
                dateStyle: "medium",
                timeStyle: "short",
              }).format(new Date(data.lastSyncedAt))}
            </p>
          </footer>
        </div>
      ) : null}
    </DashboardLayout>
  );
}
