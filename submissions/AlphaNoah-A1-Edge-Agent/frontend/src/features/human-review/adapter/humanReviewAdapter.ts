import type {
  RuntimeEventDetailDto,
  RuntimeTaskDto,
  RuntimeTimelineEntryDto,
} from "../../runtime/api/runtimeApiDtos";
import type {
  HumanReviewSnapshot,
  HumanReviewViewState,
} from "../models/humanReview";

const recommendationPrefix = "suggested_human_action=";

export function adaptHumanReviewSnapshot(
  event: RuntimeEventDetailDto,
  taskResponse: RuntimeTaskDto,
  timeline: readonly RuntimeTimelineEntryDto[],
): HumanReviewSnapshot {
  if (event.event_id !== taskResponse.event_id) {
    throw new Error("Human review Event and Task responses do not match.");
  }

  const analysis = event.analysis;
  const recommendation = analysis
    ? extractRecommendation(analysis.evidence)
    : null;

  return {
    eventId: event.event_id,
    eventStatus: event.status,
    state: reviewState(event.status, event.decision, taskResponse.task),
    analysis: analysis
      ? {
          finding: analysis.detected_issue,
          analysis: analysis.reasoning_summary,
          recommendation,
          confidence: analysis.confidence,
          severity: analysis.severity,
        }
      : null,
    decision: event.decision
      ? {
          id: event.decision.decision_id,
          status: event.decision.status,
          requiresHumanReview:
            event.decision.requires_human_review,
        }
      : null,
    task: taskResponse.task
      ? {
          id: taskResponse.task.task_id,
          status: taskResponse.task.status,
          owner: taskResponse.task.owner,
        }
      : null,
    timelineCount: timeline.length,
  };
}

function extractRecommendation(
  evidence: readonly string[],
): string | null {
  for (const entry of evidence) {
    if (!entry.startsWith(recommendationPrefix)) {
      continue;
    }
    const recommendation = entry.slice(recommendationPrefix.length).trim();
    if (recommendation) {
      return recommendation;
    }
  }
  return null;
}

function reviewState(
  eventStatus: string,
  decision: RuntimeEventDetailDto["decision"],
  task: RuntimeTaskDto["task"],
): HumanReviewViewState {
  if (eventStatus === "CLOSED") {
    return "closed";
  }
  if (eventStatus === "REJECTED" || decision?.status === "REJECTED") {
    return "rejected";
  }
  if (
    task !== null ||
    decision?.status === "APPROVED" ||
    [
      "APPROVED",
      "TASK_CREATED",
      "IN_PROGRESS",
      "EVIDENCE_SUBMITTED",
      "UNDER_REVIEW",
      "NEEDS_MORE_EVIDENCE",
    ].includes(eventStatus)
  ) {
    return "approved";
  }
  if (
    eventStatus === "PENDING_HUMAN_REVIEW" &&
    decision?.requires_human_review === true
  ) {
    return "pending";
  }
  return "not_required";
}
