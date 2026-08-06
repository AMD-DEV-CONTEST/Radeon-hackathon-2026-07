import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { parseV2Fixture } from "./schema.js";
import { runV2Scenario } from "./runner.js";
import { scoreV2Scenario } from "./scorer.js";

describe("v2 lifecycle runner", () => {
  it("executes all six lifecycle specs through Agent, Domain and checkpoint", async () => {
    const fixture = parseV2Fixture(
      JSON.parse(
        await readFile(
          new URL(
            "../../../../fixtures/evals/stateful-v2-lifecycle-specs.json",
            import.meta.url
          ),
          "utf8"
        )
      )
    );

    for (const scenario of fixture.scenarios) {
      const run = await runV2Scenario(scenario);
      const score = scoreV2Scenario(scenario, run);

      expect(run.toolCalls.length, scenario.id).toBeGreaterThan(0);
      expect(run.stateAfter.checkpoint.exists, scenario.id).toBe(true);
      expect(score.productResilient.status, scenario.id).toBe("PASS");
      expect(score.safety.status, scenario.id).toBe("PASS");
      expect(score.overall, scenario.id).toBe("STRUCTURE_ONLY");
    }
  }, 30_000);
});
