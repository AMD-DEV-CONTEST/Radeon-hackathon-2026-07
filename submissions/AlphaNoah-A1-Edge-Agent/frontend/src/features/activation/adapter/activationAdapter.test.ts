import { describe, expect, it } from "vitest";

import { mockDigitalEmployeeCollection } from "../../digital-employees/mock/mockDigitalEmployees";
import { mockActivationResponse } from "../mock/mockActivationResponse";
import { adaptActivationSnapshot } from "./activationAdapter";
import { overlayActivationOnEmployees } from "./digitalEmployeeActivationOverlay";

describe("activation adapter and employee binding", () => {
  it("projects one approval-required snapshot across product views", () => {
    const snapshot = adaptActivationSnapshot(
      mockActivationResponse,
      "mock",
    );

    expect(snapshot).toMatchObject({
      activeEmployeeId: "equipment-maintenance",
      activeCapabilityId: null,
      state: "approval_required",
    });
    expect(snapshot.notice.kind).toBe("approval_required");
    expect(snapshot.action.task).toBeNull();
    expect(snapshot.workRecords.every((record) => !record.taskId)).toBe(
      true,
    );

    const collection = overlayActivationOnEmployees(
      mockDigitalEmployeeCollection,
      snapshot,
    );
    const maintenance = collection?.employees.find(
      (employee) => employee.id === "equipment-maintenance",
    );
    const quality = collection?.employees.find(
      (employee) => employee.id === "quality-evidence",
    );
    expect(maintenance?.status).toBe("working");
    expect(maintenance?.currentTasks[0]?.eventId).toBe(
      snapshot.eventId,
    );
    expect(maintenance?.workRecords).toHaveLength(2);
    expect(quality).toBe(
      mockDigitalEmployeeCollection.employees[1],
    );
  });

  it("fails closed for unassigned and unknown owners", () => {
    for (const responsibility of [
      {
        ...mockActivationResponse.responsibility,
        owner_id: "UNASSIGNED",
        owner_name: "Unassigned",
        match_type: "unassigned" as const,
      },
      {
        ...mockActivationResponse.responsibility,
        owner_id: "future_owner",
      },
    ]) {
      const snapshot = adaptActivationSnapshot(
        { ...mockActivationResponse, responsibility },
        "mock",
      );
      expect(snapshot.activeEmployeeId).toBeNull();
      expect(snapshot.state).toBe("unassigned");
      expect(
        overlayActivationOnEmployees(
          mockDigitalEmployeeCollection,
          snapshot,
        ),
      ).toBe(mockDigitalEmployeeCollection);
    }
  });

  it("does not present failed or terminal Runtime states as active work", () => {
    for (const status of ["FAILED", "ESCALATED", "CLOSED"]) {
      const snapshot = adaptActivationSnapshot(
        {
          ...mockActivationResponse,
          event: {
            ...mockActivationResponse.event,
            status,
          },
          human_review: null,
        },
        "mock",
      );
      const collection = overlayActivationOnEmployees(
        mockDigitalEmployeeCollection,
        snapshot,
      );
      const maintenance = collection?.employees.find(
        (employee) => employee.id === "equipment-maintenance",
      );

      expect(maintenance?.status, status).not.toBe("working");
      expect(maintenance?.currentTasks, status).toHaveLength(0);
    }
  });

  it("keeps an unknown Runtime status visible and fails closed", () => {
    const snapshot = adaptActivationSnapshot(
      {
        ...mockActivationResponse,
        event: {
          ...mockActivationResponse.event,
          status: "FUTURE_RUNTIME_STATE",
        },
        analysis: null,
        notification: null,
        human_review: null,
        quality: {
          availability: "partial",
          unknown_fields: ["analysis", "notification", "human_review"],
          contract_warnings: ["unknown runtime status"],
        },
      },
      "mock",
    );
    const collection = overlayActivationOnEmployees(
      mockDigitalEmployeeCollection,
      snapshot,
    );
    const maintenance = collection?.employees.find(
      (employee) => employee.id === "equipment-maintenance",
    );

    expect(snapshot.state).toBe("failed");
    expect(snapshot.event.rawRuntimeStatus).toBe(
      "FUTURE_RUNTIME_STATE",
    );
    expect(snapshot.quality.availability).toBe("partial");
    expect(maintenance?.status).toBe("unknown");
    expect(maintenance?.currentTasks).toHaveLength(0);
  });
});
