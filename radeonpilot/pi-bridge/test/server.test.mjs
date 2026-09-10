import { after, before, describe, it } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHttpServer } from "../src/server.mjs";
import { loadConfig } from "../src/config.mjs";

async function listen(server) {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return `http://127.0.0.1:${server.address().port}`;
}

describe("radeonpilot pi bridge HTTP server", () => {
  let tempDir;
  let server;
  let baseUrl;

  before(async () => {
    tempDir = await mkdtemp(join(tmpdir(), "radeonpilot-bridge-test-"));
    const config = {
      ...loadConfig({
        PI_BRIDGE_HOST: "127.0.0.1",
        PORT: "0",
        CORS_ORIGINS: "http://allowed.example",
        AUDIT_LOG_PATH: join(tempDir, "audit.jsonl"),
        PI_MODEL_ID: "qwen3-8b",
        PI_PROVIDER_ID: "radeon-local",
        PI_API_KEY: "test-key",
        VLLM_BASE_URL: "http://127.0.0.1:8000/v1"
      }),
      port: 0,
      auditLogPath: join(tempDir, "audit.jsonl")
    };
    server = createHttpServer(config, async (body) => {
      if (body.user_message === "force failure") throw new Error("specialist failed");
      return {
        request_id: "test-request",
        session_id: body.session_id || "generated-session",
        model: { provider: "radeon-local", id: "qwen3-8b", baseUrl: "http://127.0.0.1:8000/v1" },
        agents: [],
        commander: { text: "{}", duration_ms: 1, events: {}, stats: {} },
        total_duration_ms: 1
      };
    });
    baseUrl = await listen(server);
  });

  after(async () => {
    await new Promise((resolve) => server.close(resolve));
    await rm(tempDir, { recursive: true, force: true });
  });

  it("returns health without a model request", async () => {
    const response = await fetch(`${baseUrl}/health`);
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.ok, true);
    assert.equal(body.pi.version, "0.83.0");
    assert.equal(body.model.provider, "radeon-local");
    assert.equal(body.model.id, "qwen3-8b");
    assert.equal(typeof body.runtime.radeon_attested, "boolean");
  });

  it("rejects invalid orchestrate JSON", async () => {
    const response = await fetch(`${baseUrl}/v1/orchestrate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{bad json"
    });
    assert.equal(response.status, 400);
    const body = await response.json();
    assert.equal(body.error.code, "invalid_json");
  });

  it("validates orchestrate request shape", async () => {
    const response = await fetch(`${baseUrl}/v1/orchestrate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ unexpected: true })
    });
    assert.equal(response.status, 400);
    const body = await response.json();
    assert.equal(body.error.code, "invalid_request");
  });

  it("accepts a valid GPU-ops orchestrate request through the injected orchestrator", async () => {
    const response = await fetch(`${baseUrl}/v1/orchestrate`, {
      method: "POST",
      headers: { "content-type": "application/json", origin: "http://allowed.example" },
      body: JSON.stringify({ session_id: "ops-123", environment: { gpu: "gfx1100" }, user_message: "diagnose" })
    });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("access-control-allow-origin"), "http://allowed.example");
    const body = await response.json();
    assert.equal(body.session_id, "ops-123");
  });

  it("rejects non-whitelisted CORS origins", async () => {
    const response = await fetch(`${baseUrl}/health`, { headers: { origin: "http://blocked.example" } });
    assert.equal(response.status, 403);
    const body = await response.json();
    assert.equal(body.error.code, "cors_forbidden");
  });

  it("maps an orchestration failure to a fail-closed 502", async () => {
    const response = await fetch(`${baseUrl}/v1/orchestrate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ environment: { gpu: "gfx1100" }, user_message: "force failure" })
    });
    assert.equal(response.status, 502);
    const body = await response.json();
    assert.equal(body.error.code, "orchestration_failed");
    assert.match(body.error.message, /specialist failed/);
  });

  it("refuses non-loopback bridge hosts", () => {
    assert.throws(() => loadConfig({ PI_BRIDGE_HOST: "0.0.0.0", PORT: "8787" }), /must bind to loopback/);
  });

  it("refuses non-loopback model endpoints", () => {
    assert.throws(
      () => loadConfig({ PI_BRIDGE_HOST: "127.0.0.1", VLLM_BASE_URL: "https://models.example.com/v1" }),
      /Model endpoint must be loopback/
    );
  });
});
