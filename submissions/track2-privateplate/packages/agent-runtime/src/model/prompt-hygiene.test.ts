import { describe, expect, it } from "vitest";
import {
  formatPromptHygieneReport,
  scanPromptHygiene
} from "./prompt-hygiene.js";

describe("prompt hygiene", () => {
  it("keeps system prompt and tool descriptions free of fixture ids and eval utterances", () => {
    const findings = scanPromptHygiene();
    expect(findings, formatPromptHygieneReport(findings)).toEqual([]);
  });
});
