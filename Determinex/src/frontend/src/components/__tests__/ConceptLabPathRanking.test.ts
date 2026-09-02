import { describe, expect, it } from "vitest";
import {
  detectProjectType,
  prioritizePathChoices,
  requestedProjectTypes,
  type PathInfo,
} from "../ConceptLab";

const cliPath: PathInfo = {
  id: "model-cli",
  name: "CLI Tool",
  description: "A command-line tool.",
  bestFor: "developers",
  stack: "Rust",
  complexity: "low",
  buildTime: "1-2 days",
  color: "#fb923c",
};

describe("ConceptLab path ranking", () => {
  it("prioritizes explicit website plus mobile intent over a CLI candidate", () => {
    const idea = "I want a website and mobile applications for customers";

    expect(requestedProjectTypes(idea)).toEqual(["Web + Mobile App", "Web App", "Mobile App"]);

    const ranked = prioritizePathChoices([cliPath], idea);

    expect(ranked.slice(0, 3).map((path) => path.name)).toEqual([
      "Web + Mobile App",
      "Web App",
      "Mobile App",
    ]);
    expect(ranked.find((path) => path.name === "CLI Tool")).toBeUndefined();
    expect(detectProjectType(ranked, idea)).toBe("Web + Mobile App");
  });

  it("keeps CLI first only when the user asks for a command-line tool", () => {
    const idea = "Build a CLI tool for renaming files in bulk";
    const ranked = prioritizePathChoices([cliPath], idea);

    expect(ranked[0].name).toBe("CLI Tool");
    expect(detectProjectType(ranked, idea)).toBe("CLI Tool");
  });
});
