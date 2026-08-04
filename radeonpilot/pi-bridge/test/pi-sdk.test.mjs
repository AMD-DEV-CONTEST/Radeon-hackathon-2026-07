import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { PI_SDK_PACKAGE, PI_SDK_VERSION } from "../src/config.mjs";
import { ROLE_NAMES } from "../src/sessions.mjs";
import { buildSystemPrompts } from "../src/orchestrator.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");

describe("Pi SDK pinning and model store", () => {
  it("pins the Pi SDK package and version", async () => {
    const pkg = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
    assert.equal(pkg.dependencies[PI_SDK_PACKAGE], PI_SDK_VERSION);
    assert.equal(PI_SDK_VERSION, "0.83.0");
  });

  it("defines a loopback model store entry for the configured provider", async () => {
    const models = JSON.parse(await readFile(resolve(root, "models.json"), "utf8"));
    const provider = models.providers["radeon-local"];
    assert.ok(provider);
    assert.ok(provider.models.some((model) => model.id === "qwen3-8b"));
    assert.equal(provider.api, "openai-completions");
  });

  it("declares the five GPU-ops roles", () => {
    assert.deepEqual(ROLE_NAMES, ["envdoctor", "deployplanner", "benchmarkrunner", "optimanalyst", "opscommander"]);
  });

  it("builds strict system prompts for every role", () => {
    const prompts = buildSystemPrompts();
    for (const role of ROLE_NAMES) {
      assert.ok(typeof prompts[role] === "string" && prompts[role].length > 0, role);
      assert.match(prompts[role], /JSON/);
    }
    assert.match(prompts.envdoctor, /Environment Doctor/);
    assert.match(prompts.opscommander, /OpsCommander/);
  });
});
