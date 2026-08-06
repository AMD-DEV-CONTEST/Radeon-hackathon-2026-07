import { access, readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { parseV2Fixture, V2_TOOL_NAMES } from "./schema.js";

async function readFixture(name: string): Promise<unknown> {
  const text = await readFile(
    new URL(`../../../../fixtures/evals/${name}`, import.meta.url),
    "utf8"
  );
  return JSON.parse(text);
}

describe("v2 evaluation contracts", () => {
  it("parses the eight-case public dev seed and covers every business tool", async () => {
    const fixture = parseV2Fixture(
      await readFixture("public-v2-dev-seed.json")
    );
    const covered = new Set(
      fixture.scenarios.flatMap((scenario) => scenario.requiredTools)
    );

    expect(fixture.role).toBe("dev_seed");
    expect(fixture.scenarios).toHaveLength(8);
    expect([...covered].sort()).toEqual([...V2_TOOL_NAMES].sort());
    expect(fixture.scenarios.some((scenario) => scenario.userTurns.length > 1)).toBe(
      true
    );
    expect(
      fixture.scenarios.every((scenario) =>
        scenario.stateOracle.after.checkpoint.containsSecret === false
      )
    ).toBe(true);
    expect(
      fixture.scenarios.some((scenario) => scenario.rawArgumentChecks.length > 0)
    ).toBe(true);
  });

  it("parses six lifecycle specifications and marks them structure_only", async () => {
    const fixture = parseV2Fixture(
      await readFixture("stateful-v2-lifecycle-specs.json")
    );
    const linkedTests = fixture.scenarios.flatMap(
      (scenario) => scenario.localStructureTests
    );

    expect(fixture.role).toBe("lifecycle_spec");
    expect(fixture.scenarios).toHaveLength(6);
    expect(
      fixture.scenarios.every(
        (scenario) => scenario.flags.evidenceClass === "structure_only"
      )
    ).toBe(true);
    expect(linkedTests).toContain("packages/domain/src/flagship-lifecycle.test.ts");
    expect(linkedTests).toContain("apps/server/src/product-e2e-mock.test.ts");
    for (const testPath of linkedTests) {
      await access(new URL(`../../../../${testPath}`, import.meta.url));
    }
    expect(
      fixture.scenarios.every((scenario) =>
        scenario.invariants.some((invariant) => invariant.kind === "state_oracle_reached")
      )
    ).toBe(true);
  });
});
