"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { EmptyState } from "@/components/feedback/empty-state";
import { QueryErrorState } from "@/components/feedback/query-error-state";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { AgentMetrics } from "@/features/agents/components/agent-metrics";
import { AgentStatusList } from "@/features/agents/components/agent-status-list";
import { AgentsOverview } from "@/features/agents/components/agents-overview";
import { AgentsSkeleton } from "@/features/agents/components/agents-skeleton";
import { AiThoughtsPanel } from "@/features/agents/components/ai-thoughts-panel";
import { CpuUsageCard } from "@/features/agents/components/cpu-usage-card";
import { ExecutionTimeline } from "@/features/agents/components/execution-timeline";
import { LatencyCard } from "@/features/agents/components/latency-card";
import { LogsPanel } from "@/features/agents/components/logs-panel";
import { MemoryUsageCard } from "@/features/agents/components/memory-usage-card";
import { NetworkCard } from "@/features/agents/components/network-card";
import { OrchestrationControls } from "@/features/agents/components/orchestration-controls";
import { OrchestrationErrorState } from "@/features/agents/components/orchestration-error-state";
import { OrchestrationPanel } from "@/features/agents/components/orchestration-panel";
import { ResourceSaturation } from "@/features/agents/components/resource-saturation";
import { SystemHealth } from "@/features/agents/components/system-health";
import { WorkflowGraph } from "@/features/agents/components/workflow-graph";
import { WorkflowProgress } from "@/features/agents/components/workflow-progress";
import {
  agentsQueryKeys,
  getAgentsErrorMessage,
  isNotFoundError,
  useAgentsMonitor,
} from "@/features/agents/hooks/use-agents";
import { useWorkflow } from "@/features/agents/hooks/use-workflow";
import type { WorkflowNodeId } from "@/features/agents/types/agents.types";

export function AgentsView() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const candidateId = searchParams.get("candidateId")?.trim() || "";
  const resumeId = searchParams.get("resumeId")?.trim() || "";

  const { data, logs, isLoading, isError, error, refetch, isFetching } =
    useAgentsMonitor();

  const workflow = useWorkflow({
    candidateId: candidateId || undefined,
    resumeId: resumeId || undefined,
  });

  const logsPreview = useMemo(() => {
    if (workflow.history.length > 0) {
      return workflow.history
        .slice(-4)
        .reverse()
        .map(
          (entry) =>
            `[${entry.agentName}] ${entry.action}`
        );
    }

    return logs
      .slice(0, 4)
      .map((entry) => `[${entry.agent || "SYSTEM"}] ${entry.action}`);
  }, [logs, workflow.history]);

  const workflowNodes =
    workflow.status !== "idle" && workflow.workflowNodes.length > 0
      ? workflow.workflowNodes
      : data?.workflow ?? [];

  const activeNodeId: WorkflowNodeId =
    workflow.currentAgentId || data?.activeNodeId || "planner";

  const timeline =
    workflow.status !== "idle" && workflow.timeline.length > 0
      ? workflow.timeline
      : data?.timeline ?? [];

  const canStart = Boolean(candidateId && resumeId) && !workflow.isRunning;
  const canFinalize =
    Boolean(workflow.finalResult.interviewId) &&
    !workflow.isCompleted &&
    !workflow.isRunning;
  const canCancel = workflow.isRunning || workflow.status === "partial_success";

  return (
    <DashboardLayout
      breadcrumbs={[
        { label: "Interview Management" },
        { label: "Active Sessions", current: true },
      ]}
    >
      {isLoading && !data ? <AgentsSkeleton /> : null}

      {!isLoading && isError && !data ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          {isNotFoundError(error) ? (
            <EmptyState
              title="Agent monitoring unavailable"
              description={getAgentsErrorMessage(error)}
            />
          ) : (
            <QueryErrorState
              title="Unable to load agent monitoring"
              message={getAgentsErrorMessage(error)}
              onRetry={() => {
                void refetch();
              }}
            />
          )}
        </div>
      ) : null}

      {!isLoading && !isError && !data && workflow.status === "idle" ? (
        <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
          <EmptyState
            title="No agent telemetry available"
            description="Start an interview orchestration session to begin multi-agent monitoring."
          />
        </div>
      ) : null}

      {data || workflow.status !== "idle" ? (
        <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
          {data ? (
            <AgentsOverview
              data={data}
              onResetMetrics={() => {
                void queryClient.invalidateQueries({
                  queryKey: agentsQueryKeys.all,
                });
                void workflow.syncAgents();
              }}
            />
          ) : null}

          {isFetching ? (
            <p className="text-xs text-muted-foreground">
              Syncing agent telemetry...
            </p>
          ) : null}

          <section
            className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]"
            aria-label="Orchestration status"
          >
            <div className="space-y-4">
              <OrchestrationPanel
                currentStage={workflow.currentStage}
                progressPercent={workflow.progressPercent}
              />
              <WorkflowProgress
                progressPercent={workflow.progressPercent}
                status={workflow.status}
                stages={workflow.stages}
                currentStageLabel={workflow.currentStage?.label}
              />
            </div>
            <div className="space-y-4">
              <OrchestrationControls
                canStart={canStart}
                canFinalize={canFinalize}
                canRetry={workflow.canRetry}
                canCancel={canCancel}
                isRunning={workflow.isRunning}
                finalResult={workflow.finalResult}
                onStart={() => {
                  void workflow.start().catch(() => undefined);
                }}
                onFinalize={() => {
                  void workflow.finalize().catch(() => undefined);
                }}
                onRetry={() => {
                  void workflow.retry().catch(() => undefined);
                }}
                onCancel={() => {
                  if (workflow.isRunning) {
                    void workflow.cancel();
                    return;
                  }
                  workflow.reset();
                }}
              />
              <AiThoughtsPanel thoughts={workflow.thoughts} />
            </div>
          </section>

          {!candidateId || !resumeId ? (
            <EmptyState
              title="Orchestration inputs required"
              description="Provide candidateId and resumeId query params to start the AI agent workflow."
            />
          ) : null}

          {workflow.status === "failed" ||
          workflow.status === "partial_success" ||
          workflow.status === "cancelled" ? (
            <OrchestrationErrorState
              status={workflow.status}
              message={workflow.lastError}
              canRetry={workflow.canRetry}
              onRetry={() => {
                void workflow.retry().catch(() => undefined);
              }}
              onCancel={() => {
                workflow.reset();
              }}
            />
          ) : null}

          <section
            className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]"
            aria-label="Workflow and side metrics"
          >
            <div className="space-y-4">
              <WorkflowGraph
                nodes={workflowNodes}
                activeNodeId={activeNodeId}
                logsPreview={logsPreview}
              />
              <ExecutionTimeline lanes={timeline} />
            </div>

            {data ? (
              <div className="space-y-4">
                <LatencyCard
                  series={data.latencySeries}
                  avgLatencyMs={data.avgLatencyMs}
                  p99LatencyMs={data.p99LatencyMs}
                />
                <NetworkCard
                  series={data.resourceSeries}
                  networkGbps={data.resources.networkGbps}
                  communication={data.communication}
                  clusterNodes={data.clusterNodes}
                  shard={data.shard}
                  optimizationHint={data.optimizationHint}
                />
              </div>
            ) : (
              <AiThoughtsPanel thoughts={workflow.thoughts} />
            )}
          </section>

          {data ? (
            <>
              <section
                className="grid gap-4 lg:grid-cols-3"
                aria-label="Resource charts and agent status"
              >
                <CpuUsageCard
                  series={data.resourceSeries}
                  cpuPercent={data.resources.cpuPercent}
                />
                <MemoryUsageCard
                  series={data.resourceSeries}
                  memoryPercent={data.resources.memoryPercent}
                />
                <AgentStatusList
                  agents={data.agents}
                  activeNodeId={activeNodeId}
                />
              </section>

              <AgentMetrics
                agents={data.agents}
                resourceSeries={data.resourceSeries}
              />

              <section
                className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]"
                aria-label="Logs, resources, and system health"
              >
                <LogsPanel logs={logs} />
                <div className="space-y-4">
                  <ResourceSaturation
                    resources={data.resources}
                    session={data.session}
                  />
                  <SystemHealth services={data.systemHealth} />
                </div>
              </section>

              <footer className="flex flex-col gap-2 border-t border-white/10 pt-4 text-xs text-muted-foreground sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
                <p>{data.engineVersion}</p>
                <p>{data.infrastructure}</p>
                <p>{data.region}</p>
                <p>
                  Last sync:{" "}
                  {new Intl.DateTimeFormat("en-US", {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }).format(new Date(data.lastSyncedAt))}
                </p>
              </footer>
            </>
          ) : null}
        </div>
      ) : null}
    </DashboardLayout>
  );
}
