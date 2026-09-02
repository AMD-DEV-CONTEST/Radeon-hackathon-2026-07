"use client";

import { EmptyState } from "@/components/feedback/empty-state";
import { QueryErrorState } from "@/components/feedback/query-error-state";
import { Button } from "@/components/ui/button";
import type { OrchestrationWorkflowStatus } from "@/features/agents/types/orchestration.types";

interface OrchestrationErrorStateProps {
  status: OrchestrationWorkflowStatus;
  message: string | null;
  canRetry: boolean;
  onRetry?: () => void;
  onCancel?: () => void;
}

export function OrchestrationErrorState({
  status,
  message,
  canRetry,
  onRetry,
  onCancel,
}: OrchestrationErrorStateProps) {
  if (status === "cancelled") {
    return (
      <EmptyState
        title="Workflow cancelled"
        description="The multi-agent orchestration was cancelled before completion."
      />
    );
  }

  if (status === "partial_success") {
    return (
      <div className="space-y-3">
        <EmptyState
          title="Partial success"
          description={
            message ||
            "Some agents completed successfully, but the workflow did not finish."
          }
        />
        <div className="flex flex-wrap justify-center gap-2">
          {canRetry && onRetry ? (
            <Button type="button" onClick={onRetry}>
              Retry Failed Stage
            </Button>
          ) : null}
          {onCancel ? (
            <Button type="button" variant="outline" onClick={onCancel}>
              Reset Workflow
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  if (status !== "failed" || !message) {
    return null;
  }

  return (
    <QueryErrorState
      title="Agent failed"
      message={message}
      onRetry={canRetry ? onRetry : undefined}
    />
  );
}
