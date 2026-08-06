import type {
  DigitalEmployeeCollection,
  DigitalEmployeeView,
} from "../../digital-employees";
import { messageText } from "../../runtime";
import type { ActivationSnapshot } from "../models";

export function overlayActivationOnEmployees(
  collection: DigitalEmployeeCollection | null,
  snapshot: ActivationSnapshot | null,
): DigitalEmployeeCollection | null {
  if (!collection || !snapshot?.activeEmployeeId) {
    return collection;
  }

  const hasTarget = collection.employees.some(
    (employee) => employee.id === snapshot.activeEmployeeId,
  );
  if (!hasTarget) {
    return collection;
  }

  return {
    ...collection,
    observedAt: snapshot.observedAt,
    employees: collection.employees.map((employee) =>
      employee.id === snapshot.activeEmployeeId
        ? overlayEmployee(employee, snapshot)
        : employee,
    ),
  };
}

function overlayEmployee(
  employee: DigitalEmployeeView,
  snapshot: ActivationSnapshot,
): DigitalEmployeeView {
  const isWorking =
    snapshot.state === "working" ||
    snapshot.state === "approval_required";
  const isInactive = snapshot.state === "inactive";
  return {
    ...employee,
    status: isWorking
      ? "working"
      : isInactive
        ? "online"
        : "unknown",
    rawStatus: isInactive
      ? employee.rawStatus
      : snapshot.event.rawRuntimeStatus,
    statusLabel: messageText(
      isWorking
        ? "activation.employee.working"
        : isInactive
          ? "employees.status.online"
          : "activation.employee.failed",
    ),
    statusTone: isWorking
      ? "attention"
      : isInactive
        ? "success"
        : "warning",
    statusObservedAt: snapshot.observedAt,
    currentTasks: isWorking && snapshot.employeeCurrentWork
      ? [snapshot.employeeCurrentWork]
      : [],
    workRecords: snapshot.workRecords,
    quality: snapshot.quality,
  };
}
