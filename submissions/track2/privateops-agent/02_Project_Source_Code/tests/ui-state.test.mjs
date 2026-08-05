import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import test from "node:test";

const modulePath = new URL("../web/ui-state.js", import.meta.url);
assert.ok(existsSync(modulePath), "web/ui-state.js must provide testable console state");
await import(modulePath);

const ui = globalThis.PrivateOpsUiState;

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    value: (key) => values.get(key),
  };
}

test("theme defaults to dark and persists only supported values", () => {
  const values = storage();
  assert.equal(ui.readTheme(values), "dark");
  assert.equal(ui.writeTheme(values, "light"), "light");
  assert.equal(values.value("privateops.theme"), "light");
  assert.equal(ui.writeTheme(values, "sepia"), "dark");
});

test("theme storage failures degrade to a normalized session value", () => {
  const blocked = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
  };
  assert.equal(ui.readTheme(blocked), "dark");
  assert.equal(ui.writeTheme(blocked, "light"), "light");
});

test("provider configuration is restored only when remembered", () => {
  const values = storage();
  const config = {
    endpoint: "https://example.com/v1/chat/completions",
    model: "Example-Model",
    apiKey: "browser-only-secret",
  };

  const remembered = ui.writeProviderConfig(values, config, true);
  assert.equal(remembered.remember, true);
  assert.deepEqual(ui.readProviderConfig(values), {...config, remember: true});

  const sessionOnly = ui.writeProviderConfig(values, config, false);
  assert.equal(sessionOnly.remember, false);
  assert.equal(values.value("privateops.provider"), undefined);
  assert.deepEqual(ui.readProviderConfig(values), {endpoint: "", model: "", apiKey: "", remember: false});
});

test("invalid or blocked provider storage returns an empty safe shape", () => {
  const invalid = storage({"privateops.provider": "not-json"});
  assert.deepEqual(ui.readProviderConfig(invalid), {endpoint: "", model: "", apiKey: "", remember: false});
  const blocked = {getItem: () => { throw new Error("blocked"); }};
  assert.deepEqual(ui.readProviderConfig(blocked), {endpoint: "", model: "", apiKey: "", remember: false});
});

test("remote and local provider profiles persist without cross-contamination", () => {
  const values = storage();
  const profiles = {
    activeMode: "rocm-local",
    remote: {
      endpoint: "https://example.com/v1/chat/completions",
      model: "Remote-Model",
      apiKey: "browser-only-secret",
    },
    local: {
      endpoint: "http://127.0.0.1:8000/v1/chat/completions",
      model: "Qwen/Qwen2.5-7B-Instruct",
      apiKey: "",
    },
  };

  const remembered = ui.writeProviderProfiles(values, profiles, true);

  assert.deepEqual(remembered, {...profiles, remember: true});
  assert.deepEqual(ui.readProviderProfiles(values), {...profiles, remember: true});
  assert.equal(JSON.parse(values.value("privateops.providers")).local.apiKey, "");

  const sessionOnly = ui.writeProviderProfiles(values, profiles, false);
  assert.deepEqual(sessionOnly, {...profiles, remember: false});
  assert.equal(values.value("privateops.providers"), undefined);
});

test("legacy provider configuration migrates to the remote profile", () => {
  const values = storage({
    "privateops.provider": JSON.stringify({
      endpoint: "https://example.com/v1/chat/completions",
      model: "Legacy-Remote",
      apiKey: "legacy-browser-secret",
    }),
  });

  assert.deepEqual(ui.readProviderProfiles(values), {
    activeMode: "remote",
    remote: {
      endpoint: "https://example.com/v1/chat/completions",
      model: "Legacy-Remote",
      apiKey: "legacy-browser-secret",
    },
    local: {
      endpoint: "http://127.0.0.1:8000/v1/chat/completions",
      model: "Qwen/Qwen2.5-7B-Instruct",
      apiKey: "",
    },
    remember: true,
  });
});

test("invalid profile mode and blocked storage return safe defaults", () => {
  const invalid = storage({
    "privateops.providers": JSON.stringify({activeMode: "invalid", remote: null, local: null}),
  });
  assert.equal(ui.readProviderProfiles(invalid).activeMode, "remote");
  const blocked = {getItem: () => { throw new Error("blocked"); }};
  assert.equal(ui.readProviderProfiles(blocked).activeMode, "remote");
  assert.equal(ui.readProviderProfiles(blocked).local.endpoint, "http://127.0.0.1:8000/v1/chat/completions");
});

test("fresh tunneled origin follows the live local ROCm runtime", () => {
  const profiles = ui.readProviderProfiles(storage());

  assert.equal(
    ui.initialProviderMode?.(profiles, {
      provider_mode: "rocm-local",
      runtime_mode: "rocm-local",
    }),
    "rocm-local",
  );
});

test("remembered remote choice is not replaced by the live runtime", () => {
  const profiles = {
    ...ui.readProviderProfiles(storage()),
    activeMode: "remote",
    remember: true,
  };

  assert.equal(
    ui.initialProviderMode?.(profiles, {runtime_mode: "rocm-local"}),
    "remote",
  );
});

test("RAG evidence takes precedence over successful tool observations", () => {
  const rag = [{evidence_id: "ev-1"}];
  const tools = [{name: "startup_inventory", status: "completed"}];
  assert.deepEqual(ui.classifyEvidence(rag, tools), {kind: "rag", items: rag});
});

test("completed and attention tools qualify as local evidence", () => {
  const tools = [
    {name: "startup_inventory", status: "completed"},
    {name: "security_status", status: "attention"},
    {name: "process_inventory", status: "failed"},
  ];
  assert.deepEqual(ui.classifyEvidence([], tools), {kind: "tools", items: tools.slice(0, 2)});
});

test("failed or unsupported tools do not claim local evidence", () => {
  const tools = [
    {name: "startup_inventory", status: "failed"},
    {name: "security_status", status: "unsupported"},
  ];
  assert.deepEqual(ui.classifyEvidence([], tools), {kind: "general", items: []});
});

test("active section follows the last section above the reading line", () => {
  const sections = [
    {id: "workspace", top: 0},
    {id: "evidence", top: 420},
    {id: "plan", top: 780},
  ];
  assert.equal(ui.activeSection(sections, -20), "workspace");
  assert.equal(ui.activeSection(sections, 500), "evidence");
  assert.equal(ui.activeSection(sections, 1000), "plan");
});

test("sections sharing one visual row prefer the first unless the user selected its peer", () => {
  const sections = [
    {id: "workspace", top: 0},
    {id: "evidence", top: 420},
    {id: "plan", top: 420},
    {id: "audit", top: 900},
  ];
  assert.equal(ui.activeSection(sections, 500, "workspace"), "evidence");
  assert.equal(ui.activeSection(sections, 500, "plan"), "plan");
});
