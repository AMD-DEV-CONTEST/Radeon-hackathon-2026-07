import { describe, expect, it } from "vitest";
import { resolveLocalModelTag } from "../work-readiness";

/**
 * These expectations are not guesses -- each was checked against
 * scripts/ide/_tauri_driver.py's _build_local_config() directly:
 *
 *   'auto'                        -> None            (BLOCKED_NO_MODEL)
 *   'local/fast'                  -> None            (BLOCKED_NO_MODEL)
 *   ''                            -> WRITTEN         (driver's pinned default)
 *   'determinex-engineer-v11-dsl' -> WRITTEN
 *
 * A router alias is not an Ollama tag. Passing the model picker's raw value to
 * preview_idea_oracle/build_idea refused every verified build, and "Auto" is
 * the picker's default, so this was the out-of-the-box behavior.
 */
describe("resolveLocalModelTag", () => {
  it("maps the Auto route to empty so the driver uses its pinned default", () => {
    expect(resolveLocalModelTag("auto")).toBe("");
    expect(resolveLocalModelTag("")).toBe("");
    expect(resolveLocalModelTag(undefined)).toBe("");
  });

  it("resolves local route aliases to real Ollama tags", () => {
    expect(resolveLocalModelTag("local/fast")).toBe("qwen2.5-coder:3b-instruct");
    expect(resolveLocalModelTag("local/coder")).toBe("qwen2.5-coder:1.5b-instruct");
    expect(resolveLocalModelTag("determinex/engineer")).toBe("determinex-engineer-v11-dsl");
  });

  it("never forwards a cloud route to a local-only command", () => {
    // build_idea writes local_only=true config; a cloud id would be refused.
    expect(resolveLocalModelTag("cloud/claude-best")).toBe("");
    expect(resolveLocalModelTag("cloud/deepseek-coder")).toBe("");
  });

  it("passes a concrete tag through unchanged", () => {
    expect(resolveLocalModelTag("determinex-engineer-v11-dsl")).toBe("determinex-engineer-v11-dsl");
    expect(resolveLocalModelTag("ollama/qwen2.5-coder:7b-instruct")).toBe(
      "qwen2.5-coder:7b-instruct"
    );
  });
});
