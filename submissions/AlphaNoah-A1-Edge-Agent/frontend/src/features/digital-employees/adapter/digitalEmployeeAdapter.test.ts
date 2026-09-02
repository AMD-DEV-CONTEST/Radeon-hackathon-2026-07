import { describe, expect, it } from "vitest";

import type {
  DigitalEmployeeProjectionDto,
} from "../api/digitalEmployeeApiDtos";
import {
  adaptDigitalEmployeeCollection,
} from "./digitalEmployeeAdapter";

const eventId = `event_${"b".repeat(32)}`;

const workingEmployee: DigitalEmployeeProjectionDto = {
  id: "maintenance_001",
  name: "Equipment Maintenance",
  status: "working",
  current_event_id: eventId,
  responsibility: "Equipment Maintenance",
  skills: [{ name: "restaurant-aircon-shutdown" }],
};

describe("Digital Employee projection adapter", () => {
  it("maps only observed Runtime facts into the rich View Model", () => {
    const collection = adaptDigitalEmployeeCollection([
      workingEmployee,
    ]);
    const employee = collection.employees[0];

    expect(collection).toMatchObject({
      source: "http",
      observedAt: null,
      quality: { availability: "partial" },
    });
    expect(employee).toMatchObject({
      id: "maintenance_001",
      name: {
        kind: "literal",
        value: "Equipment Maintenance",
      },
      description: null,
      status: "working",
      rawStatus: "working",
      statusObservedAt: null,
      currentEventId: eventId,
      stage: "unknown",
      rawStage: null,
      quality: { availability: "partial" },
    });
    expect(employee?.responsibilities).toEqual([
      expect.objectContaining({
        id: "maintenance_001",
        label: {
          kind: "literal",
          value: "Equipment Maintenance",
        },
        scope: null,
        quality: expect.objectContaining({
          availability: "partial",
        }),
      }),
    ]);
    expect(employee?.skills).toEqual([
      expect.objectContaining({
        id: "restaurant-aircon-shutdown",
        name: {
          kind: "literal",
          value: "restaurant-aircon-shutdown",
        },
        description: null,
        availability: "unknown",
        sourceSkill: null,
        quality: expect.objectContaining({
          availability: "partial",
        }),
      }),
    ]);
  });

  it("does not invent Task, stage, metric, record, knowledge, or permission facts", () => {
    const employee =
      adaptDigitalEmployeeCollection([workingEmployee]).employees[0];

    expect(employee?.currentTasks).toEqual([]);
    expect(employee?.todayMetrics).toMatchObject({
      handled: null,
      pending: null,
      windowStartedAt: null,
      observedAt: null,
      quality: { availability: "unavailable" },
    });
    expect(employee?.workRecords).toEqual([]);
    expect(employee?.knowledge).toEqual([]);
    expect(employee?.permissionSummary).toMatchObject({
      mode: "unknown",
      constraints: [],
      isAuthoritative: false,
      quality: { availability: "unavailable" },
    });
    expect(employee?.quality.unknownFields).toEqual(
      expect.arrayContaining([
        "stage",
        "currentTasks",
        "todayMetrics",
        "workRecords",
        "knowledge",
        "permissionSummary",
      ]),
    );
  });

  it("preserves a real unknown state and a real empty roster", () => {
    const unknown = adaptDigitalEmployeeCollection([
      {
        ...workingEmployee,
        status: "unknown",
        current_event_id: null,
        skills: [],
      },
    ]).employees[0];

    expect(unknown?.status).toBe("unknown");
    expect(unknown?.currentEventId).toBeNull();
    expect(unknown?.skills).toEqual([]);

    const empty = adaptDigitalEmployeeCollection([]);
    expect(empty.employees).toEqual([]);
    expect(empty.source).toBe("http");
    expect(empty.quality.availability).toBe("partial");
  });
});
