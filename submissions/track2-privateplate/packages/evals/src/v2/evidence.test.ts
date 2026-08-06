import { describe, expect, it } from "vitest";
import { parseRealModelEvidence } from "./evidence.js";

const hash = "a".repeat(64);

function evidence(overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: "2.0",
    scenarioId: "v2-dev-plan-basic",
    git: { sha: "0123456789abcdef0123456789abcdef01234567", dirty: false },
    sourceBinding: {
      mode: "clean_commit",
      commitSha: "0123456789abcdef0123456789abcdef01234567"
    },
    hashes: {
      runner: hash,
      scorer: hash,
      fixture: hash,
      toolSchema: hash
    },
    provider: {
      mode: "local_vllm",
      model: "local-model",
      chatEndpoint: "http://127.0.0.1:8000/v1",
      ragEndpoint: "http://localhost:8787/rag"
    },
    environment: { vllm: "0.8.5", rocm: "6.3", gpu: "Radeon" },
    trace: {
      rawNormalizedEffectivePersisted: [
        {
          tool: "get_day_context",
          responseId: "resp-1",
          nativeToolCalls: [{ id: "call-1", type: "function" }],
          raw: { dinerIds: ["mem-admin"] },
          normalized: { dinerIds: ["mem-admin"] },
          effective: { dinerIds: ["mem-admin"] },
          persisted: null
        }
      ],
      failureAttempts: [
        {
          attempt: 0,
          responseId: "resp-failed",
          reason: "schema_error",
          rawResponse: { arguments: "{}" }
        }
      ]
    },
    createdAt: "2026-08-03T10:00:00.000Z",
    ...overrides
  };
}

describe("v2 real-model evidence contract", () => {
  it("requires local loopback endpoints and preserves failed attempts", () => {
    const parsed = parseRealModelEvidence(evidence());
    expect(parsed.provider.mode).toBe("local_vllm");
    expect(parsed.trace.failureAttempts).toHaveLength(1);
    expect(parsed.trace.rawNormalizedEffectivePersisted[0]?.responseId).toBe(
      "resp-1"
    );
  });

  it("rejects a remote chat endpoint", () => {
    expect(() =>
      parseRealModelEvidence(
        evidence({
          provider: {
            mode: "local_vllm",
            model: "local-model",
            chatEndpoint: "https://example.com/v1",
            ragEndpoint: "http://localhost:8787/rag"
          }
        })
      )
    ).toThrow(/loopback/);
  });

  it("rejects a dirty worktree when evidence claims a clean commit", () => {
    expect(() =>
      parseRealModelEvidence(
        evidence({
          git: {
            sha: "0123456789abcdef0123456789abcdef01234567",
            dirty: true
          }
        })
      )
    ).toThrow(/clean_commit/);
  });

  it("accepts a dirty worktree only with a full source hash binding", () => {
    const parsed = parseRealModelEvidence(
      evidence({
        git: {
          sha: "0123456789abcdef0123456789abcdef01234567",
          dirty: true
        },
        sourceBinding: {
          mode: "full_tree_hash",
          sha256: hash,
          baseCommitSha: "0123456789abcdef0123456789abcdef01234567"
        }
      })
    );

    expect(parsed.sourceBinding.mode).toBe("full_tree_hash");
  });
});
