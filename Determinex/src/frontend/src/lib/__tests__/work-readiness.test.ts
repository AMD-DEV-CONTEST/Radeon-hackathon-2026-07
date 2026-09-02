import { describe, expect, it } from "vitest";
import {
  evaluateWorkReadiness,
  expectedLocalModels,
  specGenerationBlockMessage,
  type InstalledModel,
} from "../work-readiness";

const models: InstalledModel[] = [
  {
    id: "qwen2.5-coder:3b-instruct",
    name: "qwen2.5-coder:3b-instruct",
    size_gb: 2,
    param_size: "3B",
    is_determinex: false,
  },
  {
    id: "qwen2.5-coder:1.5b-instruct",
    name: "qwen2.5-coder:1.5b-instruct",
    size_gb: 1,
    param_size: "1.5B",
    is_determinex: false,
  },
  {
    id: "determinex-engineer-v11-dsl:latest",
    name: "determinex-engineer-v11-dsl:latest",
    size_gb: 1.5,
    param_size: "1.5B",
    is_determinex: true,
  },
  {
    id: "determinex-observer-v6-dsl:latest",
    name: "determinex-observer-v6-dsl:latest",
    size_gb: 2.5,
    param_size: "3B",
    is_determinex: true,
  },
];

describe("work readiness", () => {
  it("maps local aliases to the installed instruct tags", () => {
    expect(expectedLocalModels("local/fast")).toEqual(["qwen2.5-coder:3b-instruct"]);
  });

  it("reports ready when every local role resolves to an installed model", () => {
    const readiness = evaluateWorkReadiness({
      ollamaOk: true,
      models,
      roles: {
        oracle: "local/fast",
        architect: "local/fast",
        builder: "determinex/engineer",
        monitor: "determinex/observer",
      },
    });

    expect(readiness.ready).toBe(true);
    expect(readiness.status).toBe("ready");
  });

  it("reports attention instead of allowing a missing model to reach spec generation", () => {
    const readiness = evaluateWorkReadiness({
      ollamaOk: true,
      models: models.filter((model) => !model.id.startsWith("qwen2.5-coder:3b")),
      roles: {
        oracle: "local/fast",
        architect: "local/fast",
        builder: "determinex/engineer",
        monitor: "determinex/observer",
      },
    });

    expect(readiness.ready).toBe(false);
    expect(readiness.summary).toContain("Missing local model coverage");
    expect(readiness.details.join(" ")).toContain("qwen2.5-coder:3b-instruct");
  });

  it("blocks cloud assignments until keys or local roles are confirmed", () => {
    const readiness = evaluateWorkReadiness({
      ollamaOk: true,
      models,
      roles: {
        oracle: "cloud/claude-best",
        architect: "local/fast",
        builder: "determinex/engineer",
        monitor: "determinex/observer",
      },
    });

    expect(readiness.ready).toBe(false);
    expect(readiness.label).toBe("Cloud Selected");
  });

  it("formats a user-safe spec generation block message", () => {
    const readiness = evaluateWorkReadiness({
      ollamaOk: true,
      models: models.filter((model) => !model.id.startsWith("qwen2.5-coder:3b")),
      roles: {
        oracle: "local/fast",
        architect: "local/fast",
        builder: "determinex/engineer",
        monitor: "determinex/observer",
      },
    });

    expect(specGenerationBlockMessage(readiness)).toContain(
      "I need model readiness fixed before I write the spec."
    );
    expect(specGenerationBlockMessage(readiness)).toContain("qwen2.5-coder:3b-instruct");
  });
});
