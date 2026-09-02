import { messageText } from "../../runtime";
import type {
  DigitalEmployeeOperationalStatus,
  DigitalEmployeeStage,
  DigitalEmployeeStateProjection,
} from "./digitalEmployee";

const stageProjection = {
  intern: {
    label: "employees.stage.intern",
    tone: "info",
  },
  trial: {
    label: "employees.stage.trial",
    tone: "attention",
  },
  production: {
    label: "employees.stage.production",
    tone: "info",
  },
  paused: {
    label: "employees.stage.paused",
    tone: "warning",
  },
  retired: {
    label: "employees.stage.retired",
    tone: "info",
  },
} as const;

const statusProjection = {
  online: {
    label: "employees.status.online",
    tone: "success",
  },
  offline: {
    label: "employees.status.offline",
    tone: "warning",
  },
  working: {
    label: "employees.status.working",
    tone: "attention",
  },
} as const;

export function projectDigitalEmployeeStage(
  rawStage: string | null,
): DigitalEmployeeStateProjection<DigitalEmployeeStage> {
  const normalized = rawStage?.trim().toLowerCase() ?? null;
  if (normalized && normalized in stageProjection) {
    const stage = normalized as DigitalEmployeeStage;
    const display = stageProjection[stage];
    return {
      value: stage,
      raw: rawStage,
      label: messageText(display.label),
      tone: display.tone,
    };
  }

  return {
    value: "unknown",
    raw: rawStage,
    label: messageText("employees.stage.unknown"),
    tone: "warning",
  };
}

export function projectDigitalEmployeeStatus(
  rawStatus: string | null,
): DigitalEmployeeStateProjection<DigitalEmployeeOperationalStatus> {
  const normalized = rawStatus?.trim().toLowerCase() ?? null;
  if (normalized && normalized in statusProjection) {
    const status = normalized as Exclude<
      DigitalEmployeeOperationalStatus,
      "unknown"
    >;
    const display = statusProjection[status];
    return {
      value: status,
      raw: rawStatus,
      label: messageText(display.label),
      tone: display.tone,
    };
  }

  return {
    value: "unknown",
    raw: rawStatus,
    label: messageText("employees.status.unknown"),
    tone: "info",
  };
}
