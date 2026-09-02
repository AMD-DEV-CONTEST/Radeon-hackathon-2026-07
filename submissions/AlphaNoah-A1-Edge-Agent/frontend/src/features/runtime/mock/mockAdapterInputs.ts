import type {
  ActionSummaryAdapterInput,
} from "../adapter/actionSummaryAdapter";
import type { EventAdapterInput } from "../adapter/eventViewAdapter";
import type { HealthAdapterInput } from "../adapter/healthViewAdapter";
import type { PulseNoticeAdapterInput } from "../adapter/pulseNoticeAdapter";
import { messageText } from "../models";

const message = messageText;

/**
 * Local deterministic presentation inputs. They exercise the same adapters
 * as future Runtime reads but are not wire DTOs or declarations of a current
 * HTTP endpoint.
 */
export const mockEventInputs: readonly EventAdapterInput[] = [
  {
    eventId: "mock_activity_cooling_variance",
    status: "ANALYZED",
    severity: "MEDIUM",
    title: message("activity.event1.title"),
    detail: message("activity.event1.detail"),
    sourceLabel: message("activity.event1.source"),
    occurredAt: null,
    occurredLabel: message("activity.event1.time"),
    location: message("system.siteValue"),
    assetId: null,
    requiresHumanAction: false,
    actionSummaryId: "mock_action_cooling_variance",
  },
  {
    eventId: "mock_activity_evidence_ready",
    status: "EVIDENCE_SUBMITTED",
    severity: "LOW",
    title: message("activity.event2.title"),
    detail: message("activity.event2.detail"),
    sourceLabel: message("activity.event2.source"),
    occurredAt: null,
    occurredLabel: message("activity.event2.time"),
    location: message("system.siteValue"),
    assetId: null,
    actionSummaryId: "mock_action_evidence_ready",
  },
  {
    eventId: "mock_activity_changeover_review",
    status: "PENDING_HUMAN_REVIEW",
    severity: "HIGH",
    title: message("activity.event3.title"),
    detail: message("activity.event3.detail"),
    sourceLabel: message("activity.event3.source"),
    occurredAt: null,
    occurredLabel: message("activity.event3.time"),
    location: message("system.siteValue"),
    assetId: null,
    actionSummaryId: "mock_action_changeover_review",
  },
  {
    eventId: "mock_activity_heartbeat_recovered",
    status: "CLOSED",
    severity: "LOW",
    title: message("activity.event4.title"),
    detail: message("activity.event4.detail"),
    sourceLabel: message("activity.event4.source"),
    occurredAt: null,
    occurredLabel: message("activity.event4.time"),
    location: message("system.siteValue"),
    assetId: "A1-NORTH-07",
    actionSummaryId: "mock_action_heartbeat_recovered",
  },
];

export const mockActionInputs: readonly ActionSummaryAdapterInput[] = [
  {
    id: "mock_action_cooling_variance",
    eventId: "mock_activity_cooling_variance",
    heading: message("activity.event1.title"),
    facts: [message("summary.event1.facts")],
    aiUnderstanding: message("summary.event1.analysis"),
    rawSeverity: "MEDIUM",
    riskExplanation: message("summary.event1.risk"),
    suggestedAction: message("summary.event1.next"),
    humanDecision: message("summary.event1.decision"),
    decision: null,
    task: null,
    evidenceStatus: null,
    timeline: [],
  },
  {
    id: "mock_action_evidence_ready",
    eventId: "mock_activity_evidence_ready",
    heading: message("activity.event2.title"),
    facts: [message("summary.event2.facts")],
    aiUnderstanding: message("summary.event2.analysis"),
    rawSeverity: "LOW",
    riskExplanation: message("summary.event2.risk"),
    suggestedAction: message("summary.event2.next"),
    humanDecision: message("summary.event2.decision"),
    decision: null,
    task: null,
    evidenceStatus: "EVIDENCE_SUBMITTED",
    timeline: [],
  },
  {
    id: "mock_action_changeover_review",
    eventId: "mock_activity_changeover_review",
    heading: message("activity.event3.title"),
    facts: [message("summary.event3.facts")],
    aiUnderstanding: message("summary.event3.analysis"),
    rawSeverity: "HIGH",
    riskExplanation: message("summary.event3.risk"),
    suggestedAction: message("summary.event3.next"),
    humanDecision: message("summary.event3.decision"),
    decision: {
      id: "mock_decision_changeover_review",
      status: "PENDING_HUMAN_REVIEW",
      requiresHumanReview: true,
    },
    task: null,
    evidenceStatus: null,
    timeline: [],
  },
  {
    id: "mock_action_heartbeat_recovered",
    eventId: "mock_activity_heartbeat_recovered",
    heading: message("activity.event4.title"),
    facts: [message("summary.event4.facts")],
    aiUnderstanding: message("summary.event4.analysis"),
    rawSeverity: "LOW",
    riskExplanation: message("summary.event4.risk"),
    suggestedAction: message("summary.event4.next"),
    humanDecision: message("summary.event4.decision"),
    decision: null,
    task: null,
    evidenceStatus: null,
    timeline: [],
  },
];

export const mockNoticeInputs: readonly PulseNoticeAdapterInput[] = [
  {
    id: "mock_pulse_cooling_context",
    eventId: "mock_activity_cooling_variance",
    status: "ANALYZED",
    severity: "MEDIUM",
    title: message("pulse.notice.title"),
    summary: message("pulse.notice.summary"),
    facts: message("summary.event1.facts"),
    analysis: message("summary.event1.analysis"),
    nextAction: message("summary.event1.next"),
    requiresHumanAction: false,
    createdAt: null,
    sourceNotificationStatus: null,
  },
];

export const mockHealthInput: HealthAdapterInput = {
  state: "healthy",
  label: message("system.healthValue"),
  components: [
    {
      id: "health",
      label: message("system.health"),
      value: message("system.healthValue"),
      state: "healthy",
    },
    {
      id: "node",
      label: message("system.node"),
      value: message("system.nodeValue"),
      state: "healthy",
    },
    {
      id: "role",
      label: message("system.role"),
      value: message("system.roleValue"),
      state: "healthy",
    },
    {
      id: "site",
      label: message("system.site"),
      value: message("system.siteValue"),
      state: "healthy",
    },
    {
      id: "mode",
      label: message("system.mode"),
      value: message("system.modeValue"),
      state: "healthy",
    },
  ],
  observedAt: null,
};
