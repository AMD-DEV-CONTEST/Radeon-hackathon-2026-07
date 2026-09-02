import { describe, expect, it } from "vitest";

import { formatEmployeeTime } from "./employeeTime";

describe("formatEmployeeTime", () => {
  it("preserves the source clock context for a fixed-offset timestamp", () => {
    expect(
      formatEmployeeTime(
        "2026-07-30T10:42:00-04:00",
        "en-US",
      ),
    ).toContain("10:42");
  });

  it("returns invalid source text unchanged", () => {
    expect(formatEmployeeTime("not-a-time", "en-US")).toBe(
      "not-a-time",
    );
  });
});
