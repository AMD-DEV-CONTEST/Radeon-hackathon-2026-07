import { describe, expect, it } from "vitest";

import {
  decodeDigitalEmployeeProjection,
} from "./digitalEmployeeApiDecoders";

const eventId = `event_${"a".repeat(32)}`;

const workingEmployee = {
  id: "maintenance_001",
  name: "Equipment Maintenance",
  status: "working",
  current_event_id: eventId,
  responsibility: "Equipment Maintenance",
  skills: [{ name: "restaurant-aircon-shutdown" }],
} as const;

describe("Digital Employee projection decoder", () => {
  it("allowlists the exact public fields and strips additive data", () => {
    const decoded = decodeDigitalEmployeeProjection([
      {
        ...workingEmployee,
        prompt: "must-not-cross-the-boundary",
        skills: [
          {
            name: "restaurant-aircon-shutdown",
            analysis_instructions: "private",
          },
        ],
      },
    ]);

    expect(decoded).toEqual([workingEmployee]);
    expect(JSON.stringify(decoded)).not.toMatch(
      /prompt|analysis_instructions|private/,
    );
  });

  it("accepts real empty and unknown-state projections", () => {
    expect(decodeDigitalEmployeeProjection([])).toEqual([]);
    expect(
      decodeDigitalEmployeeProjection([
        {
          ...workingEmployee,
          status: "unknown",
          current_event_id: null,
          skills: [],
        },
      ]),
    ).toEqual([
      {
        ...workingEmployee,
        status: "unknown",
        current_event_id: null,
        skills: [],
      },
    ]);
  });

  it.each([
    {
      label: "a non-array root",
      value: { employees: [workingEmployee] },
      message: "digital employees must be an array",
    },
    {
      label: "a missing field",
      value: [
        {
          id: workingEmployee.id,
          name: workingEmployee.name,
          status: workingEmployee.status,
          current_event_id: workingEmployee.current_event_id,
          skills: workingEmployee.skills,
        },
      ],
      message: "responsibility must be a bounded non-empty string",
    },
    {
      label: "an unsupported status",
      value: [{ ...workingEmployee, status: "online" }],
      message: "status does not match the projection contract",
    },
    {
      label: "an invalid Event ID",
      value: [
        {
          ...workingEmployee,
          current_event_id: "../private/event",
        },
      ],
      message: "current_event_id must be a valid Event ID or null",
    },
    {
      label: "working without a current Event",
      value: [{ ...workingEmployee, current_event_id: null }],
      message:
        "current_event_id is required while status is working",
    },
    {
      label: "unknown with a current Event",
      value: [{ ...workingEmployee, status: "unknown" }],
      message:
        "current_event_id must be null while status is unknown",
    },
    {
      label: "duplicate employee IDs",
      value: [workingEmployee, workingEmployee],
      message: "id must be unique",
    },
    {
      label: "duplicate Skill names",
      value: [
        {
          ...workingEmployee,
          skills: [
            workingEmployee.skills[0],
            workingEmployee.skills[0],
          ],
        },
      ],
      message: "name must be unique within an employee",
    },
  ])("rejects $label", ({ value, message }) => {
    expect(() => decodeDigitalEmployeeProjection(value)).toThrow(
      message,
    );
  });
});
