import { describe, expect, it } from "vitest";
import { parseTextToolCalls } from "../src/agent.js";

describe("parseTextToolCalls", () => {
  it("parses hermes xml tool calls from assistant content", () => {
    const content = `<tool_call>
{"name": "claim", "arguments": {"text": "hello", "type": "bugfix"}}
</tool_call>
<tool_call>
{"name": "git_diff", "arguments": {"mode": "worktree"}}
</tool_call>`;
    const calls = parseTextToolCalls(content);
    expect(calls).toHaveLength(2);
    expect(calls[0]?.function.name).toBe("claim");
    expect(JSON.parse(calls[0]!.function.arguments).text).toBe("hello");
    expect(calls[1]?.function.name).toBe("git_diff");
  });
});
