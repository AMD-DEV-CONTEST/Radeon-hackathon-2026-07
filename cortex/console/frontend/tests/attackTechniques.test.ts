import { describe, it, expect } from "vitest";
import { loadAttackTechniques } from "../src/data/attackTechniquesLoader";

describe("attack-techniques.tsv", () => {
  it("contains exactly 210 technique IDs in Txxxx.xxxx form", () => {
    const ids = loadAttackTechniques();
    expect(ids.length).toBe(210);
    for (const id of ids) expect(id).toMatch(/^T\d{4}(\.\d{3})?$/);
    expect(new Set(ids).size).toBe(210);
  });
});
