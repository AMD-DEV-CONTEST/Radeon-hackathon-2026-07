import { beforeEach, describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";

import {
  discoverIdea,
  generateSpec,
  injectSandboxContext,
  promoteToGarden,
  startSession,
  unleashThePack,
} from "../api";

const invokeMock = vi.mocked(invoke);

describe("API AI routing payloads", () => {
  beforeEach(() => {
    invokeMock.mockReset();
    invokeMock.mockResolvedValue({ ok: true, data: {} });
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: { transformCallback: vi.fn() },
    });
  });

  it("threads selected model routes through orchestration calls", async () => {
    await injectSandboxContext("fix parser", "thread-1", ["a.ts"], "cloud/claude-best");
    await promoteToGarden("thread-2", "history", "free/qwen3-coder");
    await unleashThePack("build app", {
      sentinel: "cloud/gpt4o",
      engineer: "determinex/engineer",
      observer: "determinex/observer",
    });

    expect(invokeMock).toHaveBeenNthCalledWith(1, "orchestrate_plan", {
      payload: {
        user_prompt: "fix parser",
        thread_id: "thread-1",
        contexts: ["a.ts"],
        model_override: "cloud/claude-best",
      },
    });
    expect(invokeMock).toHaveBeenNthCalledWith(2, "orchestrate_plan", {
      payload: {
        user_prompt: "history",
        thread_id: "thread-2",
        model_override: "free/qwen3-coder",
      },
    });
    expect(invokeMock).toHaveBeenNthCalledWith(3, "orchestrate_plan", {
      payload: {
        user_prompt: "build app",
        thread_id: expect.stringMatching(/^pack-/),
        topology: {
          sentinel: "cloud/gpt4o",
          engineer: "determinex/engineer",
          observer: "determinex/observer",
        },
      },
    });
  });

  it("threads selected model routes through idea and Hive creation calls", async () => {
    await discoverIdea("todo app", [], "cloud/gemini-flash");
    await generateSpec("todo app context", "cloud/deepseek-coder");
    await startSession("spec.md", "rust", 2, "determinex/engineer");

    expect(invokeMock).toHaveBeenNthCalledWith(1, "discover_idea", {
      payload: { idea: "todo app", attachments: [], model_override: "cloud/gemini-flash" },
    });
    expect(invokeMock).toHaveBeenNthCalledWith(2, "generate_spec", {
      payload: { idea: "todo app context", model_override: "cloud/deepseek-coder" },
    });
    expect(invokeMock).toHaveBeenNthCalledWith(3, "start_session", {
      payload: {
        spec_path: "spec.md",
        lang: "rust",
        budget: 2,
        model_override: "determinex/engineer",
      },
    });
  });
});
