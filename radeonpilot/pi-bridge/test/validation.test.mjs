import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { validateOrchestrateRequest, HttpError } from "../src/validation.mjs";

describe("orchestrate request validation", () => {
  it("fills defaults for a minimal request", () => {
    const body = validateOrchestrateRequest({ user_message: "diagnose my Radeon" });
    assert.equal(body.user_message, "diagnose my Radeon");
    assert.equal(body.role, "operator");
    assert.equal(body.environment, null);
  });

  it("rejects unknown fields", () => {
    assert.throws(() => validateOrchestrateRequest({ foo: 1 }), HttpError);
  });

  it("rejects an empty payload", () => {
    assert.throws(() => validateOrchestrateRequest({}), HttpError);
  });

  it("rejects a malformed session id", () => {
    assert.throws(() => validateOrchestrateRequest({ session_id: "bad id!", user_message: "x" }), HttpError);
  });

  it("accepts all GPU-ops evidence fields", () => {
    const body = validateOrchestrateRequest({
      session_id: "ops-1",
      environment: { gpu: "gfx1100", vram_gb: 48 },
      telemetry: { temp_c: 62 },
      benchmark: { ttft_ms: 120 },
      evidence: [{ id: "doc-1" }],
      memory: [{ turn: 1 }],
      user_message: "optimize",
      role: "sre"
    });
    assert.equal(body.role, "sre");
    assert.equal(body.environment.gpu, "gfx1100");
  });

  it("rejects deeply nested payloads", () => {
    let payload = { value: 1 };
    for (let i = 0; i < 20; i += 1) payload = { child: payload };
    assert.throws(() => validateOrchestrateRequest({ environment: payload }), HttpError);
  });
});
