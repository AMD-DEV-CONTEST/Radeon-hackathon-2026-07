import {
  availableDataQuality,
  messageText,
  type DataQuality,
} from "../../runtime";
import {
  projectDigitalEmployeeStage,
  projectDigitalEmployeeStatus,
  type DigitalEmployeeCollection,
  type DigitalEmployeeView,
} from "../types";

const observedAt = "2026-07-30T10:42:00+08:00";
const windowStartedAt = "2026-07-30T00:00:00+08:00";

const nonAuthoritativeQuality: DataQuality = {
  availability: "partial",
  unknownFields: ["authoritative_permissions"],
  contractWarnings: [
    "F03-B permission copy is a non-authoritative Mock boundary.",
  ],
};

function employee(
  identity: Pick<DigitalEmployeeView, "id" | "name" | "description">,
  rawStatus: string,
  rawStage: string,
  detail: Omit<
    DigitalEmployeeView,
    | "id"
    | "name"
    | "description"
    | "status"
    | "rawStatus"
    | "statusLabel"
    | "statusTone"
    | "statusObservedAt"
    | "stage"
    | "rawStage"
    | "stageLabel"
    | "stageTone"
  >,
): DigitalEmployeeView {
  const status = projectDigitalEmployeeStatus(rawStatus);
  const stage = projectDigitalEmployeeStage(rawStage);

  return {
    ...identity,
    status: status.value,
    rawStatus: status.raw,
    statusLabel: status.label,
    statusTone: status.tone,
    statusObservedAt: observedAt,
    stage: stage.value,
    rawStage: stage.raw,
    stageLabel: stage.label,
    stageTone: stage.tone,
    ...detail,
  };
}

const equipmentMaintenance = employee(
  {
    id: "equipment-maintenance",
    name: messageText("employees.mock.maintenance.name"),
    description: messageText(
      "employees.mock.maintenance.description",
    ),
  },
  "working",
  "production",
  {
    currentEventId: "evt-cooling-loop-variance",
    responsibilities: [
      {
        id: "maintenance-condition",
        label: messageText(
          "employees.mock.maintenance.responsibility.condition",
        ),
        scope: messageText(
          "employees.mock.maintenance.responsibility.conditionScope",
        ),
        quality: availableDataQuality,
      },
      {
        id: "maintenance-review",
        label: messageText(
          "employees.mock.maintenance.responsibility.review",
        ),
        scope: messageText(
          "employees.mock.maintenance.responsibility.reviewScope",
        ),
        quality: availableDataQuality,
      },
    ],
    skills: [
      {
        id: "thermal-deviation",
        name: messageText(
          "employees.mock.maintenance.capability.thermal",
        ),
        description: messageText(
          "employees.mock.maintenance.capability.thermalDescription",
        ),
        availability: "available",
        availabilityLabel: messageText(
          "employees.capability.available",
        ),
        availabilityTone: "info",
        sourceSkill: {
          skillId: "cold-holding-monitor",
          version: "1.0.0",
        },
        quality: availableDataQuality,
      },
      {
        id: "maintenance-evidence",
        name: messageText(
          "employees.mock.maintenance.capability.evidence",
        ),
        description: messageText(
          "employees.mock.maintenance.capability.evidenceDescription",
        ),
        availability: "limited",
        availabilityLabel: messageText(
          "employees.capability.limited",
        ),
        availabilityTone: "attention",
        sourceSkill: {
          skillId: "equipment-evidence-review",
          version: "1.1.0",
        },
        quality: availableDataQuality,
      },
    ],
    currentTasks: [
      {
        id: "task-maintenance-cooling-review",
        title: messageText(
          "employees.mock.maintenance.task.cooling",
        ),
        runtimeStatus: "PENDING_HUMAN_REVIEW",
        statusLabel: messageText(
          "employees.task.awaitingConfirmation",
        ),
        statusTone: "attention",
        updatedAt: "2026-07-30T10:35:00+08:00",
        eventId: "evt-cooling-loop-variance",
        quality: availableDataQuality,
      },
    ],
    todayMetrics: {
      handled: 7,
      pending: 2,
      windowStartedAt,
      observedAt,
      quality: availableDataQuality,
    },
    workRecords: [
      {
        id: "maintenance-record-review",
        occurredAt: "2026-07-30T10:35:00+08:00",
        occurredLabel: messageText("employees.time.1035"),
        title: messageText(
          "employees.mock.maintenance.record.review",
        ),
        detail: messageText(
          "employees.mock.maintenance.record.reviewDetail",
        ),
        kind: "human_review",
        eventId: "evt-cooling-loop-variance",
        taskId: "task-maintenance-cooling-review",
        rawAction: "human_review_requested",
        quality: availableDataQuality,
      },
      {
        id: "maintenance-record-knowledge",
        occurredAt: "2026-07-30T10:33:00+08:00",
        occurredLabel: messageText("employees.time.1033"),
        title: messageText(
          "employees.mock.maintenance.record.knowledge",
        ),
        detail: messageText(
          "employees.mock.maintenance.record.knowledgeDetail",
        ),
        kind: "knowledge_lookup",
        eventId: "evt-cooling-loop-variance",
        taskId: null,
        rawAction: "knowledge_sources_read",
        quality: availableDataQuality,
      },
      {
        id: "maintenance-record-detected",
        occurredAt: "2026-07-30T10:32:00+08:00",
        occurredLabel: messageText("employees.time.1032"),
        title: messageText(
          "employees.mock.maintenance.record.detected",
        ),
        detail: messageText(
          "employees.mock.maintenance.record.detectedDetail",
        ),
        kind: "event_detected",
        eventId: "evt-cooling-loop-variance",
        taskId: null,
        rawAction: "event_created",
        quality: availableDataQuality,
      },
    ],
    knowledge: [
      {
        id: "maintenance-knowledge-manuals",
        label: messageText(
          "employees.mock.maintenance.knowledge.manuals",
        ),
        sourceType: "product_projection",
        quality: availableDataQuality,
      },
      {
        id: "maintenance-knowledge-history",
        label: messageText(
          "employees.mock.maintenance.knowledge.history",
        ),
        sourceType: "event_provenance",
        quality: availableDataQuality,
      },
    ],
    permissionSummary: {
      mode: "human_confirmed",
      label: messageText(
        "employees.mock.maintenance.boundary.label",
      ),
      constraints: [
        messageText(
          "employees.mock.maintenance.boundary.confirmation",
        ),
        messageText(
          "employees.mock.maintenance.boundary.noControl",
        ),
      ],
      isAuthoritative: false,
      quality: nonAuthoritativeQuality,
    },
    quality: availableDataQuality,
  },
);

const qualityEvidence = employee(
  {
    id: "quality-evidence",
    name: messageText("employees.mock.quality.name"),
    description: messageText(
      "employees.mock.quality.description",
    ),
  },
  "online",
  "trial",
  {
    currentEventId: "evt-inspection-evidence",
    responsibilities: [
      {
        id: "quality-evidence-completeness",
        label: messageText(
          "employees.mock.quality.responsibility.evidence",
        ),
        scope: messageText(
          "employees.mock.quality.responsibility.evidenceScope",
        ),
        quality: availableDataQuality,
      },
      {
        id: "quality-exception-summary",
        label: messageText(
          "employees.mock.quality.responsibility.exception",
        ),
        scope: messageText(
          "employees.mock.quality.responsibility.exceptionScope",
        ),
        quality: availableDataQuality,
      },
    ],
    skills: [
      {
        id: "evidence-completeness",
        name: messageText(
          "employees.mock.quality.capability.completeness",
        ),
        description: messageText(
          "employees.mock.quality.capability.completenessDescription",
        ),
        availability: "available",
        availabilityLabel: messageText(
          "employees.capability.available",
        ),
        availabilityTone: "info",
        sourceSkill: {
          skillId: "quality-evidence-check",
          version: "2.0.0",
        },
        quality: availableDataQuality,
      },
      {
        id: "quality-context",
        name: messageText(
          "employees.mock.quality.capability.context",
        ),
        description: messageText(
          "employees.mock.quality.capability.contextDescription",
        ),
        availability: "limited",
        availabilityLabel: messageText(
          "employees.capability.limited",
        ),
        availabilityTone: "attention",
        sourceSkill: {
          skillId: "quality-context-review",
          version: "1.0.0",
        },
        quality: availableDataQuality,
      },
    ],
    currentTasks: [
      {
        id: "task-quality-package-review",
        title: messageText(
          "employees.mock.quality.task.package",
        ),
        runtimeStatus: "WAITING_EVIDENCE",
        statusLabel: messageText(
          "employees.task.evidenceReady",
        ),
        statusTone: "info",
        updatedAt: "2026-07-30T10:36:00+08:00",
        eventId: "evt-inspection-evidence",
        quality: availableDataQuality,
      },
    ],
    todayMetrics: {
      handled: 12,
      pending: 1,
      windowStartedAt,
      observedAt,
      quality: availableDataQuality,
    },
    workRecords: [
      {
        id: "quality-record-package",
        occurredAt: "2026-07-30T10:36:00+08:00",
        occurredLabel: messageText("employees.time.1036"),
        title: messageText(
          "employees.mock.quality.record.package",
        ),
        detail: messageText(
          "employees.mock.quality.record.packageDetail",
        ),
        kind: "evidence",
        eventId: "evt-inspection-evidence",
        taskId: "task-quality-package-review",
        rawAction: "evidence_package_completed",
        quality: availableDataQuality,
      },
      {
        id: "quality-record-images",
        occurredAt: "2026-07-30T10:31:00+08:00",
        occurredLabel: messageText("employees.time.1031"),
        title: messageText(
          "employees.mock.quality.record.images",
        ),
        detail: messageText(
          "employees.mock.quality.record.imagesDetail",
        ),
        kind: "analysis",
        eventId: "evt-inspection-evidence",
        taskId: null,
        rawAction: "evidence_completeness_checked",
        quality: availableDataQuality,
      },
      {
        id: "quality-record-completed",
        occurredAt: "2026-07-30T09:58:00+08:00",
        occurredLabel: messageText("employees.time.0958"),
        title: messageText(
          "employees.mock.quality.record.completed",
        ),
        detail: messageText(
          "employees.mock.quality.record.completedDetail",
        ),
        kind: "completed",
        eventId: "evt-previous-quality-review",
        taskId: null,
        rawAction: "review_context_closed",
        quality: availableDataQuality,
      },
    ],
    knowledge: [
      {
        id: "quality-knowledge-criteria",
        label: messageText(
          "employees.mock.quality.knowledge.criteria",
        ),
        sourceType: "product_projection",
        quality: availableDataQuality,
      },
      {
        id: "quality-knowledge-provenance",
        label: messageText(
          "employees.mock.quality.knowledge.provenance",
        ),
        sourceType: "event_provenance",
        quality: availableDataQuality,
      },
    ],
    permissionSummary: {
      mode: "human_confirmed",
      label: messageText(
        "employees.mock.quality.boundary.label",
      ),
      constraints: [
        messageText(
          "employees.mock.quality.boundary.confirmation",
        ),
        messageText(
          "employees.mock.quality.boundary.noDisposition",
        ),
      ],
      isAuthoritative: false,
      quality: nonAuthoritativeQuality,
    },
    quality: availableDataQuality,
  },
);

const materialFlow = employee(
  {
    id: "material-flow",
    name: messageText("employees.mock.material.name"),
    description: messageText(
      "employees.mock.material.description",
    ),
  },
  "offline",
  "paused",
  {
    currentEventId: null,
    responsibilities: [
      {
        id: "material-changeover",
        label: messageText(
          "employees.mock.material.responsibility.changeover",
        ),
        scope: messageText(
          "employees.mock.material.responsibility.changeoverScope",
        ),
        quality: availableDataQuality,
      },
      {
        id: "material-verification",
        label: messageText(
          "employees.mock.material.responsibility.verification",
        ),
        scope: messageText(
          "employees.mock.material.responsibility.verificationScope",
        ),
        quality: availableDataQuality,
      },
    ],
    skills: [
      {
        id: "changeover-context",
        name: messageText(
          "employees.mock.material.capability.changeover",
        ),
        description: messageText(
          "employees.mock.material.capability.changeoverDescription",
        ),
        availability: "unavailable",
        availabilityLabel: messageText(
          "employees.capability.unavailable",
        ),
        availabilityTone: "warning",
        sourceSkill: {
          skillId: "material-changeover-context",
          version: "1.0.0",
        },
        quality: availableDataQuality,
      },
      {
        id: "verification-checkpoint",
        name: messageText(
          "employees.mock.material.capability.verification",
        ),
        description: messageText(
          "employees.mock.material.capability.verificationDescription",
        ),
        availability: "unavailable",
        availabilityLabel: messageText(
          "employees.capability.unavailable",
        ),
        availabilityTone: "warning",
        sourceSkill: {
          skillId: "local-verification-checkpoint",
          version: "1.0.0",
        },
        quality: availableDataQuality,
      },
    ],
    currentTasks: [],
    todayMetrics: {
      handled: 4,
      pending: null,
      windowStartedAt,
      observedAt,
      quality: {
        availability: "partial",
        unknownFields: ["pending"],
        contractWarnings: [
          "Pending count is intentionally unavailable in this fixture.",
        ],
      },
    },
    workRecords: [
      {
        id: "material-record-paused",
        occurredAt: "2026-07-30T10:28:00+08:00",
        occurredLabel: messageText("employees.time.1028"),
        title: messageText(
          "employees.mock.material.record.paused",
        ),
        detail: messageText(
          "employees.mock.material.record.pausedDetail",
        ),
        kind: "human_review",
        eventId: "evt-material-changeover",
        taskId: null,
        rawAction: "verification_waiting",
        quality: availableDataQuality,
      },
      {
        id: "material-record-context",
        occurredAt: "2026-07-30T10:26:00+08:00",
        occurredLabel: messageText("employees.time.1026"),
        title: messageText(
          "employees.mock.material.record.context",
        ),
        detail: messageText(
          "employees.mock.material.record.contextDetail",
        ),
        kind: "analysis",
        eventId: "evt-material-changeover",
        taskId: null,
        rawAction: "changeover_context_summarized",
        quality: availableDataQuality,
      },
      {
        id: "material-record-detected",
        occurredAt: "2026-07-30T10:24:00+08:00",
        occurredLabel: messageText("employees.time.1024"),
        title: messageText(
          "employees.mock.material.record.detected",
        ),
        detail: messageText(
          "employees.mock.material.record.detectedDetail",
        ),
        kind: "event_detected",
        eventId: "evt-material-changeover",
        taskId: null,
        rawAction: "changeover_checkpoint_entered",
        quality: availableDataQuality,
      },
    ],
    knowledge: [
      {
        id: "material-knowledge-checklist",
        label: messageText(
          "employees.mock.material.knowledge.checklist",
        ),
        sourceType: "product_projection",
        quality: availableDataQuality,
      },
      {
        id: "material-knowledge-history",
        label: messageText(
          "employees.mock.material.knowledge.history",
        ),
        sourceType: "event_provenance",
        quality: availableDataQuality,
      },
    ],
    permissionSummary: {
      mode: "read_only",
      label: messageText(
        "employees.mock.material.boundary.label",
      ),
      constraints: [
        messageText(
          "employees.mock.material.boundary.readOnly",
        ),
        messageText(
          "employees.mock.material.boundary.noDispatch",
        ),
      ],
      isAuthoritative: false,
      quality: nonAuthoritativeQuality,
    },
    quality: availableDataQuality,
  },
);

export const mockDigitalEmployeeCollection: DigitalEmployeeCollection = {
  source: "mock",
  employees: [
    equipmentMaintenance,
    qualityEvidence,
    materialFlow,
  ],
  observedAt,
  quality: availableDataQuality,
};
