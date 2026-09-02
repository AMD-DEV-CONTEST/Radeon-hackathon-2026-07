import {
  literalText,
  messageText,
  type DataQuality,
} from "../../runtime";
import type {
  DigitalEmployeeProjectionDto,
} from "../api/digitalEmployeeApiDtos";
import {
  projectDigitalEmployeeStage,
  projectDigitalEmployeeStatus,
  type CapabilityModule,
  type DigitalEmployeeCollection,
  type DigitalEmployeeView,
  type ResponsibilityView,
} from "../types";

const collectionQuality: DataQuality = {
  availability: "partial",
  unknownFields: ["observedAt", "employee_enrichment"],
  contractWarnings: [
    "The Runtime projection does not expose a collection observation time or enriched employee profile fields.",
  ],
};

const responsibilityQuality: DataQuality = {
  availability: "partial",
  unknownFields: ["scope", "responsibility_id"],
  contractWarnings: [
    "The Runtime projection exposes a responsibility summary, not a distinct Responsibility identifier or scope.",
  ],
};

const skillQuality: DataQuality = {
  availability: "partial",
  unknownFields: [
    "description",
    "availability",
    "sourceSkill.version",
  ],
  contractWarnings: [
    "The Runtime projection exposes only the observed Skill name.",
  ],
};

const metricsQuality: DataQuality = {
  availability: "unavailable",
  unknownFields: [
    "handled",
    "pending",
    "windowStartedAt",
    "observedAt",
  ],
  contractWarnings: [
    "The Runtime projection does not expose Digital Employee metrics.",
  ],
};

const permissionQuality: DataQuality = {
  availability: "unavailable",
  unknownFields: ["mode", "constraints"],
  contractWarnings: [
    "The Runtime projection does not expose an authorization or permission summary.",
  ],
};

const employeeQuality: DataQuality = {
  availability: "partial",
  unknownFields: [
    "description",
    "statusObservedAt",
    "stage",
    "currentTasks",
    "todayMetrics",
    "workRecords",
    "knowledge",
    "permissionSummary",
  ],
  contractWarnings: [
    "Only observed responsibility, status, current Event, and Skill facts are available from the Runtime projection.",
  ],
};

export function adaptDigitalEmployeeCollection(
  employees: readonly DigitalEmployeeProjectionDto[],
): DigitalEmployeeCollection {
  return {
    source: "http",
    employees: employees.map(adaptDigitalEmployee),
    observedAt: null,
    quality: collectionQuality,
  };
}

function adaptDigitalEmployee(
  employee: DigitalEmployeeProjectionDto,
): DigitalEmployeeView {
  const status = projectDigitalEmployeeStatus(employee.status);
  const stage = projectDigitalEmployeeStage(null);
  return {
    id: employee.id,
    name: literalText(employee.name),
    description: null,
    status: status.value,
    rawStatus: status.raw,
    statusLabel: status.label,
    statusTone: status.tone,
    statusObservedAt: null,
    currentEventId: employee.current_event_id,
    stage: stage.value,
    rawStage: stage.raw,
    stageLabel: stage.label,
    stageTone: stage.tone,
    responsibilities: [
      adaptResponsibility(employee.id, employee.responsibility),
    ],
    skills: employee.skills.map(adaptSkill),
    currentTasks: [],
    todayMetrics: {
      handled: null,
      pending: null,
      windowStartedAt: null,
      observedAt: null,
      quality: metricsQuality,
    },
    workRecords: [],
    knowledge: [],
    permissionSummary: {
      mode: "unknown",
      label: messageText("employees.value.unknown"),
      constraints: [],
      isAuthoritative: false,
      quality: permissionQuality,
    },
    quality: employeeQuality,
  };
}

function adaptResponsibility(
  employeeId: string,
  summary: string,
): ResponsibilityView {
  return {
    id: employeeId,
    label: literalText(summary),
    scope: null,
    quality: responsibilityQuality,
  };
}

function adaptSkill(
  skill: DigitalEmployeeProjectionDto["skills"][number],
): CapabilityModule {
  return {
    id: skill.name,
    name: literalText(skill.name),
    description: null,
    availability: "unknown",
    availabilityLabel: messageText("employees.value.unknown"),
    availabilityTone: "info",
    sourceSkill: null,
    quality: skillQuality,
  };
}
