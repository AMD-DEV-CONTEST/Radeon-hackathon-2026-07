import { describe, expect, it } from "vitest";

import { DigitalEmployeeReadError } from "../types";
import { MockDigitalEmployeeDataSource } from "./MockDigitalEmployeeDataSource";
import { mockDigitalEmployeeCollection } from "./mockDigitalEmployees";

describe("MockDigitalEmployeeDataSource", () => {
  it("returns one deterministic collection from synchronous and asynchronous reads", async () => {
    const source = new MockDigitalEmployeeDataSource();

    expect(source.getInitialCollection()).toBe(
      mockDigitalEmployeeCollection,
    );
    await expect(source.getEmployees()).resolves.toBe(
      mockDigitalEmployeeCollection,
    );
    expect(source.source).toBe("mock");
  });

  it("contains the three stable product roles and no duplicate IDs", () => {
    const employees = mockDigitalEmployeeCollection.employees;

    expect(employees.map(({ id }) => id)).toEqual([
      "equipment-maintenance",
      "quality-evidence",
      "material-flow",
    ]);
    expect(new Set(employees.map(({ id }) => id)).size).toBe(
      employees.length,
    );
  });

  it("rejects an already-aborted read without replacing it with data", async () => {
    const source = new MockDigitalEmployeeDataSource();
    const controller = new AbortController();
    controller.abort();

    await expect(
      source.getEmployees({ signal: controller.signal }),
    ).rejects.toMatchObject({
      name: "DigitalEmployeeReadError",
      code: "aborted",
      source: "mock",
    } satisfies Partial<DigitalEmployeeReadError>);
  });
});
