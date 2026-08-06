import { describe, expect, it } from "vitest";
import { loadRuntimeConfig, mockAgentTestConfig } from "./runtime-config.js";

describe("loadRuntimeConfig", () => {
  it("rejects the removed deterministic simulator", () => {
    expect(() =>
      loadRuntimeConfig({
        PRIVATEPLATE_APP_MODE: "demo",
        PRIVATEPLATE_AGENT_PROVIDER: "deterministic_dev"
      })
    ).toThrow(/removed|ScriptedProductProvider/i);
  });

  it("defaults the product dashboard to local_vllm with persistent sqlite", () => {
    const config = loadRuntimeConfig({
      PRIVATEPLATE_APP_MODE: "demo",
      PRIVATEPLATE_MODEL: "google/gemma-test",
      PRIVATEPLATE_VLLM_BASE_URL: "http://127.0.0.1:8000/v1"
    });

    expect(config).toMatchObject({
      appMode: "demo",
      providerMode: "local_vllm",
      model: "google/gemma-test",
      baseUrl: "http://127.0.0.1:8000/v1",
      databasePath: "./data/privateplate-demo.sqlite"
    });
    expect(config.provider?.mode).toBe("local_vllm");
  });

  it("refuses to start the dashboard without a model id", () => {
    expect(() =>
      loadRuntimeConfig({
        PRIVATEPLATE_APP_MODE: "demo"
      })
    ).toThrow(/PRIVATEPLATE_MODEL/);
  });

  it("builds a loopback vLLM provider for production", () => {
    const config = loadRuntimeConfig({
      PRIVATEPLATE_APP_MODE: "production",
      PRIVATEPLATE_AGENT_PROVIDER: "local_vllm",
      PRIVATEPLATE_DATABASE_PATH: "/tmp/privateplate-test.sqlite",
      PRIVATEPLATE_VLLM_BASE_URL: "http://127.0.0.1:8000/v1",
      PRIVATEPLATE_MODEL: "Qwen/Qwen2.5-7B-Instruct",
      PRIVATEPLATE_ACCESS_TOKEN: "test-access-token"
    });

    expect(config).toMatchObject({
      appMode: "production",
      providerMode: "local_vllm",
      model: "Qwen/Qwen2.5-7B-Instruct",
      baseUrl: "http://127.0.0.1:8000/v1"
    });
    expect(config.provider?.mode).toBe("local_vllm");
  });

  it("requires an access token before production can be exposed", () => {
    expect(() =>
      loadRuntimeConfig({
        PRIVATEPLATE_APP_MODE: "production",
        PRIVATEPLATE_AGENT_PROVIDER: "local_vllm",
        PRIVATEPLATE_MODEL: "test-model"
      })
    ).toThrow(/ACCESS_TOKEN/);
  });

  it("exposes a scripted mock fixture for offline server tests", () => {
    const config = mockAgentTestConfig();
    expect(config.providerMode).toBe("local_vllm");
    expect(config.provider.mode).toBe("scripted_mock");
    expect(config.provider).toBeTruthy();
  });
});
