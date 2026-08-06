import { describe, expect, it } from "vitest";

import { enUS, zhCN } from "./messages";

describe("translation catalog", () => {
  it("keeps complete, non-empty locale catalogs", () => {
    expect(Object.keys(zhCN).sort()).toEqual(Object.keys(enUS).sort());

    for (const value of Object.values(enUS)) {
      expect(value.trim()).not.toBe("");
    }
    for (const value of Object.values(zhCN)) {
      expect(value.trim()).not.toBe("");
    }
  });
});
